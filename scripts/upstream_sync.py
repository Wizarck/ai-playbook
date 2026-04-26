"""upstream_sync.py — local inspection + manual-triage tool for tracked forks.

Populated in T23a. Implements the human-side half of `specs/upstream-sync.md`.
The LangGraph `upstream_refresher.py` workflow in eligia-core is the automated
half; this CLI is the read-only / manually-triggered counterpart.

Commands
--------
    python -m scripts.upstream_sync list
    python -m scripts.upstream_sync status <fork>
    python -m scripts.upstream_sync refresh <fork>           # fetch only; never merges
    python -m scripts.upstream_sync mark-merged <fork> <patch-id>

All commands accept ``--force-with-reason TEXT`` per specs/break-glass.md. The
only gate that accepts an override is "upstream unreachable" (network flakes);
parse errors and registry-missing do NOT accept overrides.

Registry
--------
``~/.ai-playbook/forks.yaml`` (per-dev, gitignored):

    schema: ai-playbook/forks-registry/v1
    forks:
      hindsight:
        path: C:/Projects/hindsight
        upstream: https://github.com/upstream/hindsight-repo
        owner: arturo6ramirez@gmail.com

Exit codes
----------
    0 success or override applied
    1 fork unreachable / parse error / PATCHES.md malformed
    2 registry missing or invalid schema
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 stdio — Windows default cp1252 cannot encode the sigils we emit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "upstream_sync.py"
DEFAULT_REGISTRY_PATH = Path.home() / ".ai-playbook" / "forks.yaml"
REGISTRY_SCHEMA = "ai-playbook/forks-registry/v1"

_PATCH_ROW_RE = re.compile(
    r"^\|\s*(?P<id>P\d+)\s*\|"
    r"\s*(?P<title>[^|]*)\|"
    r"\s*(?P<branch>[^|]*)\|"
    r"\s*(?P<pr>[^|]*)\|"
    r"\s*(?P<status>[^|]*)\|"
    r"\s*(?P<rebase>[^|]*)\|"
    r"\s*(?P<notes>[^|]*)\|\s*$"
)


# ---------------------------------------------------------------------------
# Canonical error emission (error-message-standard.md shape)
# ---------------------------------------------------------------------------

def _emit_error(*, why: str, where: str, fix: str, override: str = "none") -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class ForkEntry:
    name: str
    path: Path
    upstream: str
    owner: str


def load_registry(registry_path: Path | None = None) -> dict[str, ForkEntry]:
    """Load ``~/.ai-playbook/forks.yaml`` into a dict of ForkEntry.

    Raises:
        FileNotFoundError: if the registry file is missing. The CLI wraps this
                           in an exit(2).
        ValueError: if the schema is wrong.
    """
    path = registry_path or DEFAULT_REGISTRY_PATH
    if not path.is_file():
        raise FileNotFoundError(f"registry missing at {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"registry YAML parse failed: {exc}") from exc

    schema = raw.get("schema")
    if schema != REGISTRY_SCHEMA:
        raise ValueError(
            f"registry schema mismatch: expected {REGISTRY_SCHEMA!r}, got {schema!r}"
        )
    forks_raw = raw.get("forks") or {}
    if not isinstance(forks_raw, dict):
        raise ValueError("registry `forks:` must be a mapping")

    result: dict[str, ForkEntry] = {}
    for name, spec in forks_raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"fork {name!r}: entry must be a mapping")
        try:
            result[name] = ForkEntry(
                name=name,
                path=Path(spec["path"]),
                upstream=str(spec["upstream"]),
                owner=str(spec.get("owner", "unknown")),
            )
        except KeyError as exc:
            raise ValueError(f"fork {name!r}: missing required field {exc}") from exc
    return result


# ---------------------------------------------------------------------------
# PATCHES.md parsing
# ---------------------------------------------------------------------------

@dataclass
class PatchRow:
    id: str
    title: str
    branch: str
    upstream_pr: str
    status: str
    last_rebase: str
    notes: str


def parse_patches_md(text: str) -> list[PatchRow]:
    """Extract rows from the *Active patches* table of a PATCHES.md body."""
    rows: list[PatchRow] = []
    in_active = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_active = stripped.lower().startswith("## active patches")
            continue
        if not in_active:
            continue
        m = _PATCH_ROW_RE.match(line)
        if not m:
            continue
        rows.append(
            PatchRow(
                id=m.group("id").strip(),
                title=m.group("title").strip(),
                branch=m.group("branch").strip(),
                upstream_pr=m.group("pr").strip(),
                status=m.group("status").strip(),
                last_rebase=m.group("rebase").strip(),
                notes=m.group("notes").strip(),
            )
        )
    return rows


def rewrite_patch_status(text: str, patch_id: str, new_status: str) -> str:
    """Return a new PATCHES.md body with the row for ``patch_id`` updated.

    Raises ValueError if the patch is not found in the *Active patches* table.
    """
    lines = text.splitlines(keepends=True)
    in_active = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_active = stripped.lower().startswith("## active patches")
            continue
        if not in_active:
            continue
        m = _PATCH_ROW_RE.match(line)
        if not m:
            continue
        if m.group("id").strip() != patch_id:
            continue
        new_line = (
            f"| {m.group('id').strip()} | {m.group('title').strip()} | "
            f"{m.group('branch').strip()} | {m.group('pr').strip()} | "
            f"{new_status} | {m.group('rebase').strip()} | "
            f"{m.group('notes').strip()} |"
        )
        # Preserve trailing newline if the original had one.
        if line.endswith("\r\n"):
            new_line += "\r\n"
        elif line.endswith("\n"):
            new_line += "\n"
        lines[i] = new_line
        return "".join(lines)
    raise ValueError(f"patch {patch_id!r} not found in Active patches table")


# ---------------------------------------------------------------------------
# Git helpers (subprocess wrappers)
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def git_fetch_upstream(fork: ForkEntry) -> tuple[bool, str]:
    """Run `git fetch upstream` inside the fork. Return (ok, message)."""
    try:
        proc = _git(fork.path, "fetch", "upstream", check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"git fetch upstream failed: {exc}"
    if proc.returncode != 0:
        return False, proc.stderr.strip() or "git fetch upstream returned non-zero"
    return True, "ok"


def git_ahead_behind(fork: ForkEntry, *, upstream_ref: str = "upstream/main") -> tuple[int, int]:
    """Return (ahead, behind) commit counts vs upstream/main."""
    ahead = _git(fork.path, "rev-list", "--count", f"{upstream_ref}..main").stdout.strip()
    behind = _git(fork.path, "rev-list", "--count", f"main..{upstream_ref}").stdout.strip()
    return int(ahead or "0"), int(behind or "0")


def git_list_branches(fork: ForkEntry) -> list[str]:
    """Return all local branch names (no `refs/heads/` prefix)."""
    proc = _git(fork.path, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return [b.strip() for b in proc.stdout.splitlines() if b.strip()]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(registry: dict[str, ForkEntry]) -> int:
    if not registry:
        print("(no forks registered)")
        return 0
    for name, entry in sorted(registry.items()):
        print(f"{name}\t{entry.path}\t{entry.upstream}\t{entry.owner}")
    return 0


def cmd_status(
    registry: dict[str, ForkEntry],
    fork_name: str,
    *,
    force_reason: str | None = None,
    repo_root: Path | None = None,
) -> int:
    fork = registry.get(fork_name)
    if fork is None:
        _emit_error(
            why=f"fork {fork_name!r} not in registry",
            where=str(DEFAULT_REGISTRY_PATH),
            fix=f"add an entry for {fork_name!r} under `forks:` in the registry.",
        )
        return 1

    if not fork.path.is_dir():
        _emit_error(
            why=f"fork path missing: {fork.path}",
            where=str(DEFAULT_REGISTRY_PATH),
            fix="clone the fork at the registered path, or correct the `path:` entry.",
        )
        return 1

    patches_path = fork.path / "PATCHES.md"
    if not patches_path.is_file():
        _emit_error(
            why="PATCHES.md missing at fork root",
            where=str(patches_path),
            fix="copy templates/PATCHES.md.tmpl into the fork and fill in placeholders.",
        )
        return 1

    patches = parse_patches_md(patches_path.read_text(encoding="utf-8"))
    branches = set(git_list_branches(fork))

    listed_branches = {p.branch for p in patches if p.branch and p.branch != "—"}
    staged_ids = {p.id for p in patches if p.status == "staged"}

    # Mismatch A: patches listed but branch missing.
    missing_branches = sorted(b for b in listed_branches if b not in branches)
    # Mismatch B: tenant-prefixed branches that aren't in PATCHES.md.
    tenant_prefixes = ("eligia/", "palafito/")
    orphan_branches = sorted(
        b for b in branches
        if b.startswith(tenant_prefixes) and b not in listed_branches
    )

    try:
        ahead, behind = git_ahead_behind(fork)
        upstream_reachable = True
    except (subprocess.CalledProcessError, ValueError) as exc:
        # "upstream/main" missing locally or git errored — let break-glass rescue.
        result = apply_break_glass(
            gate="upstream-unreachable",
            script=SCRIPT_BASENAME,
            reason=force_reason,
            override_allowed=True,
            repo_root=repo_root or fork.path,
        )
        if not result.applied:
            _emit_error(
                why=f"cannot compute ahead/behind vs upstream/main: {exc}",
                where=str(fork.path),
                fix="run `git fetch upstream` inside the fork, then retry `status`.",
                override=(
                    f"python -m scripts.upstream_sync status {fork_name} "
                    f'--force-with-reason="network unreachable, offline triage"'
                ),
            )
            return 1
        ahead, behind, upstream_reachable = 0, 0, False
        print(f"⚠️ OVERRIDE APPLIED: {result.reason}")

    print(f"fork={fork_name} path={fork.path} upstream={fork.upstream}")
    if upstream_reachable:
        print(f"ahead={ahead} behind={behind}")
    else:
        print("upstream status: unreachable (override applied)")
    print(f"patches_total={len(patches)} staged={len(staged_ids)}")
    if missing_branches:
        print("missing_branches (listed in PATCHES.md but not in git):")
        for b in missing_branches:
            print(f"  - {b}")
    if orphan_branches:
        print("orphan_branches (in git, not in PATCHES.md):")
        for b in orphan_branches:
            print(f"  - {b}")
    if not missing_branches and not orphan_branches:
        print("no drift between PATCHES.md and branches")
    return 0


def cmd_refresh(
    registry: dict[str, ForkEntry],
    fork_name: str,
    *,
    force_reason: str | None = None,
    repo_root: Path | None = None,
) -> int:
    """Fetch upstream. NEVER merges; reports ahead/behind and conflicts.

    The actual merge/rebase is the workflow's job (behind HITL). This CLI is
    read-only by design.
    """
    fork = registry.get(fork_name)
    if fork is None:
        _emit_error(
            why=f"fork {fork_name!r} not in registry",
            where=str(DEFAULT_REGISTRY_PATH),
            fix=f"add an entry for {fork_name!r} under `forks:` in the registry.",
        )
        return 1

    ok, message = git_fetch_upstream(fork)
    if not ok:
        result = apply_break_glass(
            gate="upstream-unreachable",
            script=SCRIPT_BASENAME,
            reason=force_reason,
            override_allowed=True,
            repo_root=repo_root or fork.path,
        )
        if not result.applied:
            _emit_error(
                why=f"`git fetch upstream` failed: {message}",
                where=str(fork.path),
                fix="check network + `upstream` remote URL; retry.",
                override=(
                    f"python -m scripts.upstream_sync refresh {fork_name} "
                    f'--force-with-reason="offline; local triage only"'
                ),
            )
            return 1
        print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
        print("fetch skipped due to override; nothing to report.")
        return 0

    # Fetch succeeded. Report ahead/behind; do not merge.
    ahead, behind = git_ahead_behind(fork)
    print(f"fork={fork_name} fetched={message}")
    print(f"ahead={ahead} behind={behind}")
    print("NOTE: refresh is read-only. Use the upstream_refresher workflow "
          "(HITL-gated) to actually merge.")
    return 0


def cmd_mark_merged(
    registry: dict[str, ForkEntry],
    fork_name: str,
    patch_id: str,
) -> int:
    fork = registry.get(fork_name)
    if fork is None:
        _emit_error(
            why=f"fork {fork_name!r} not in registry",
            where=str(DEFAULT_REGISTRY_PATH),
            fix=f"add an entry for {fork_name!r} under `forks:` in the registry.",
        )
        return 1

    patches_path = fork.path / "PATCHES.md"
    if not patches_path.is_file():
        _emit_error(
            why="PATCHES.md missing at fork root",
            where=str(patches_path),
            fix="copy templates/PATCHES.md.tmpl into the fork and fill in placeholders.",
        )
        return 1

    body = patches_path.read_text(encoding="utf-8")
    try:
        new_body = rewrite_patch_status(body, patch_id, "merged")
    except ValueError as exc:
        _emit_error(
            why=str(exc),
            where=str(patches_path),
            fix=f"verify {patch_id!r} exists in the Active patches table.",
        )
        return 1

    patches_path.write_text(new_body, encoding="utf-8")
    print(f"marked {patch_id} as merged in {patches_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upstream_sync",
        description="Inspect + triage upstream-tracked forks (see specs/upstream-sync.md).",
    )
    parser.add_argument(
        "--registry", default=None,
        help=f"path to the forks registry YAML (default: {DEFAULT_REGISTRY_PATH}).",
    )
    add_break_glass_flag(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all registered forks")

    p_status = sub.add_parser("status", help="show fork vs upstream drift")
    p_status.add_argument("fork")

    p_refresh = sub.add_parser("refresh", help="fetch upstream (read-only)")
    p_refresh.add_argument("fork")

    p_mark = sub.add_parser("mark-merged", help="mark a patch row as merged in PATCHES.md")
    p_mark.add_argument("fork")
    p_mark.add_argument("patch_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    registry_path = Path(args.registry) if args.registry else DEFAULT_REGISTRY_PATH

    try:
        registry = load_registry(registry_path)
    except FileNotFoundError:
        _emit_error(
            why="forks registry missing",
            where=str(registry_path),
            fix=(
                f"create {registry_path} with schema: {REGISTRY_SCHEMA} and a "
                "`forks:` mapping. See docs/fork-inventory.md §3."
            ),
        )
        return 2
    except ValueError as exc:
        _emit_error(
            why=f"forks registry invalid: {exc}",
            where=str(registry_path),
            fix="fix the YAML per docs/fork-inventory.md §3.",
        )
        return 2

    if args.command == "list":
        return cmd_list(registry)
    if args.command == "status":
        return cmd_status(registry, args.fork, force_reason=args.force_reason)
    if args.command == "refresh":
        return cmd_refresh(registry, args.fork, force_reason=args.force_reason)
    if args.command == "mark-merged":
        return cmd_mark_merged(registry, args.fork, args.patch_id)

    # argparse `required=True` makes this unreachable, but belt-and-braces.
    _emit_error(
        why=f"unknown command: {args.command!r}",
        where="upstream_sync CLI",
        fix="pass one of list|status|refresh|mark-merged.",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
