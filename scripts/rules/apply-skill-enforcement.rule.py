"""L1 hardrule: apply-skill-enforcement.

Paired with docs/rules/apply-skill-enforcement.rule.md.

Two surfaces:

1. `validate <change-id>` — thin wrapper around scripts/openspec_apply_marker.py
   to confirm an apply-phase session marker exists for a specific change.
   Used by the PreToolUse hook (`.claude/hooks/openspec-apply-enforce.py`) and
   by ad-hoc CLI invocations.

2. `validate-pr-diff --base <sha> --head <sha>` (v0.20.0+) — L3 server-side
   gate. Computes `git diff <base>...<head>` and verifies that every changed
   file falling under a declared `## Owns (write_paths)` section of some
   `openspec/changes/<id>/tasks.md` has a corresponding `start` record in
   `openspec/changes/<id>/.apply_log.jsonl`. Intended for the
   `.github/workflows/apply-skill-enforcement.rule.yml` workflow as a
   required check on PRs.

CLI:
    python scripts/rules/apply-skill-enforcement.rule.py validate <change-id>
    python scripts/rules/apply-skill-enforcement.rule.py validate-pr-diff \\
        --base origin/main --head HEAD

Exit codes:
    0 — clean (marker present, or no violations).
    1 — violation (marker missing for some path under a write_path).
    2 — schema break / fatal.

Helper-function duplication notice
----------------------------------
`_parse_write_paths` and `_path_matches` here are byte-equivalent copies of
the same helpers in `.claude/hooks/openspec-apply-enforce.py`. The
duplication is intentional: the PreToolUse hook runs as a stdlib-only
subprocess from the consumer project, so importing from `scripts.*` requires
fragile `sys.path` injection across consumers. The duplication is bounded
by `tests/test_apply_enforce_helpers_equivalence.py` which asserts byte-
identical behaviour on a shared fixture set.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MARKER_SCRIPT = REPO_ROOT / "scripts" / "openspec_apply_marker.py"

# Helpers duplicated from .claude/hooks/openspec-apply-enforce.py — see
# module docstring for rationale.
WRITE_PATHS_HEADING_RE = re.compile(r"^\s*##\s*owns\b.*write_paths", re.IGNORECASE)
NEXT_HEADING_RE = re.compile(r"^\s*##\s+")
BULLET_PATH_RE = re.compile(r"^\s*[*\-]\s+`([^`]+)`")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _parse_write_paths(tasks_md: Path) -> list[str]:
    if not tasks_md.is_file():
        return []
    out: list[str] = []
    in_section = False
    try:
        text = tasks_md.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if WRITE_PATHS_HEADING_RE.match(line):
            in_section = True
            continue
        if in_section and NEXT_HEADING_RE.match(line):
            break
        if in_section:
            m = BULLET_PATH_RE.match(line)
            if m:
                out.append(m.group(1).strip())
    return out


def _path_matches(target: str, write_path: str) -> bool:
    target = target.replace("\\", "/")
    write_path = write_path.replace("\\", "/")
    if write_path == target:
        return True
    if fnmatch.fnmatchcase(target, write_path):
        return True
    return write_path.endswith("/") and target.startswith(write_path)


# ----------------------------------------------------------------------------
# Subcommand 1: validate <change-id>
# ----------------------------------------------------------------------------


def validate(change_id: str) -> int:
    if os.environ.get("AIPLAYBOOK_APPLY_SKILL_SKIP"):
        return 0
    if not MARKER_SCRIPT.is_file():
        _emit_error(
            why=f"openspec_apply_marker.py missing at {MARKER_SCRIPT}",
            where=str(MARKER_SCRIPT),
            fix="restore scripts/openspec_apply_marker.py from main.",
        )
        return 2
    try:
        result = subprocess.run(
            [sys.executable, str(MARKER_SCRIPT), "session_started", "--change-id", change_id],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        _emit_error(
            why=f"apply-marker check failed: {exc}",
            where="apply-skill-enforcement",
            fix="run scripts/openspec_apply_marker.py session_started manually.",
        )
        return 2
    if result.returncode == 0:
        return 0
    _emit_error(
        why=f"no apply session marker for change `{change_id}`",
        where="apply-skill-enforcement",
        fix=(
            "invoke the openspec-apply-change skill OR run "
            f"`python -m scripts.openspec_apply_marker start --change-id {change_id}` "
            "before any Edit/Write on a declared write_path."
        ),
    )
    return 1


# ----------------------------------------------------------------------------
# Subcommand 2: validate-pr-diff --base <sha> --head <sha>
# ----------------------------------------------------------------------------


def _git_diff_names(base: str, head: str, repo_root: Path) -> list[str]:
    """Return paths changed between base..head (forward-slash normalized)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []
    return [
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _has_start_record(apply_log: Path, change_id: str) -> bool:
    """Return True if any `start` record for change_id exists in apply_log."""
    if not apply_log.is_file():
        return False
    try:
        text = apply_log.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Cheap substring scan first; only parse JSON when both tokens match.
        if '"event"' in line and '"start"' in line and change_id in line:
            try:
                rec = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(rec, dict) and rec.get("event") == "start" and rec.get("change_id") == change_id:
                return True
    return False


def validate_pr_diff(base: str, head: str, repo_root: Path | None = None) -> int:
    """L3 PR-diff gate. Returns 0/1/2 per module docstring."""
    repo = repo_root or Path.cwd()
    changes_root = repo / "openspec" / "changes"
    if not changes_root.is_dir():
        # Nothing to gate against in this repo.
        return 0

    changed_paths = _git_diff_names(base, head, repo)
    if not changed_paths:
        # No changes to inspect (or git failed silently — treat as clean).
        return 0

    # Cache write_paths per change_id.
    changes: list[tuple[str, list[str], Path]] = []
    for child in sorted(changes_root.iterdir()):
        if not child.is_dir():
            continue
        tasks_md = child / "tasks.md"
        if not tasks_md.is_file():
            continue
        write_paths = _parse_write_paths(tasks_md)
        if not write_paths:
            continue
        changes.append((child.name, write_paths, child / ".apply_log.jsonl"))

    if not changes:
        return 0

    violations: list[tuple[str, str, str]] = []  # (target, change_id, matched_pattern)
    for target in changed_paths:
        if target.startswith("openspec/changes/"):
            # Change-own folder — never gated.
            continue
        for change_id, write_paths, apply_log in changes:
            matched = next((wp for wp in write_paths if _path_matches(target, wp)), None)
            if not matched:
                continue
            if _has_start_record(apply_log, change_id):
                continue
            violations.append((target, change_id, matched))
            break  # one violation per target is enough

    if not violations:
        return 0

    print("❌ apply phase bypass detected on PR diff:", file=sys.stderr)
    for target, change_id, matched in violations:
        print(
            f"   {target} matches `{matched}` in change `{change_id}`",
            file=sys.stderr,
        )
        print(
            f"     no `start` record in openspec/changes/{change_id}/.apply_log.jsonl",
            file=sys.stderr,
        )
    print(
        "   FIX: in the PR branch, run the openspec-apply-change skill",
        file=sys.stderr,
    )
    print(
        "        for each cited change-id, then commit the updated `.apply_log.jsonl`.",
        file=sys.stderr,
    )
    print("   OVERRIDE: none (server-side gate; use a follow-up PR).", file=sys.stderr)
    return 1


# ----------------------------------------------------------------------------
# CLI entrypoint.
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply-skill-enforcement")
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.required = False  # allow legacy positional invocation

    p_validate = subparsers.add_parser("validate", help="check a single change-id marker")
    p_validate.add_argument("change_id", nargs="?", default="")

    p_diff = subparsers.add_parser(
        "validate-pr-diff",
        help="check PR diff against all active changes' write_paths",
    )
    p_diff.add_argument("--base", required=True, help="base ref (sha or ref name)")
    p_diff.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    p_diff.add_argument(
        "--repo-root",
        default=None,
        help="repo root (default: cwd)",
    )

    args = parser.parse_args(argv)

    if args.subcommand == "validate-pr-diff":
        repo_root = Path(args.repo_root) if args.repo_root else None
        return validate_pr_diff(args.base, args.head, repo_root=repo_root)

    # Default / legacy: validate <change_id>
    change_id = getattr(args, "change_id", "") or ""
    if not change_id:
        # Empty change_id is a no-op — telemetry-friendly when running on stdin events.
        return 0
    return validate(change_id)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("apply-skill-enforcement", main))
