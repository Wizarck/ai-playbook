"""PR-time gate that fails when a code-doc pair drifts (one side touched, other not).

Slice: doc-drift-enforcement (v0.16.0).

Reads `specs/co-edit-pairs.yaml` (declarative pair manifest). Computes the set
of files changed in the current branch via `git diff --name-only origin/main...HEAD`
(triple-dot — only changes introduced by THIS branch's merge-base, not all of
HEAD ^ main). For each Tier 1 pair: if exactly one side was touched, record
drift. Honours the `[no-doc-impact]` (case-insensitive) escape hatch in the
PR title.

Contracts:
- specs/doc-drift-enforcement.md (this script's contract, in full)
- specs/co-edit-pairs.yaml (canonical manifest)
- specs/error-message-standard.md (WHY/FIX/OVERRIDE shape on exit 1 + 2)
- specs/break-glass.md (exit-code convention)

CLI
---
    python -m scripts.check_doc_drift                          # default: check current branch
    python -m scripts.check_doc_drift --pr-title "feat: foo"   # honour escape hatch
    python -m scripts.check_doc_drift --base-ref origin/main   # override base ref
    python -m scripts.check_doc_drift --head-ref HEAD          # override head ref
    python -m scripts.check_doc_drift --diff-files a.py b.md   # explicit file list (tests / synthetic probes)
    python -m scripts.check_doc_drift --manifest <path>        # override (tests)
    python -m scripts.check_doc_drift validate                 # schema check; exit 0/2

Exit codes
----------
    0 = pass (no drift, OR escape hatch honoured)
    1 = drift detected (Tier 1 violation, no escape hatch)
    2 = schema break (manifest malformed, missing field, YAML parse error, git failure)
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# UTF-8 stdio for Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


SCRIPT_NAME = "check_doc_drift"
DEFAULT_MANIFEST_REL = Path("specs/co-edit-pairs.yaml")
ESCAPE_HATCH = "[no-doc-impact]"
ALLOWED_TIERS = {1, 2, 3}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
MANIFEST_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Pair:
    id: str
    tier: int
    code: str
    doc: str
    reason: str
    introduced_in: str


# ---------------------------------------------------------------------------
# Error emission (canonical WHY/FIX/OVERRIDE shape)
# ---------------------------------------------------------------------------


def _emit_schema_error(why: str, where: str, fix: str, override: str = "none — manifest contract") -> int:
    """Exit 2 path. Mirrors `scripts/_break_glass.py` shape."""
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override}", file=sys.stderr)
    print("   See: specs/doc-drift-enforcement.md §2 (manifest schema).", file=sys.stderr)
    return 2


def _emit_drift_block(pairs_drifted: list[tuple[Pair, list[str]]]) -> int:
    """Exit 1 path — Tier 1 drift detected, no escape hatch."""
    n = len(pairs_drifted)
    print(f"❌ Doc-drift violation detected for {n} pair(s):", file=sys.stderr)
    print("", file=sys.stderr)
    for pair, touched in pairs_drifted:
        # Identify which side was touched
        code_hits = [f for f in touched if _glob_match(f, pair.code)]
        doc_hits = [f for f in touched if _glob_match(f, pair.doc)]
        print(f"   • {pair.id} (tier {pair.tier})", file=sys.stderr)
        if code_hits and not doc_hits:
            print(f"     code (touched): {', '.join(code_hits)}", file=sys.stderr)
            print(f"     doc  (missing): {pair.doc}", file=sys.stderr)
        elif doc_hits and not code_hits:
            print(f"     code (missing): {pair.code}", file=sys.stderr)
            print(f"     doc  (touched): {', '.join(doc_hits)}", file=sys.stderr)
        print(f"     reason: {pair.reason}", file=sys.stderr)
        print("", file=sys.stderr)
    print("   FIX: edit the missing side in the same PR, OR add `[no-doc-impact]`", file=sys.stderr)
    print("        to the PR title if this change truly does not affect the doc contract.", file=sys.stderr)
    print('   OVERRIDE: add `[no-doc-impact]` (case-insensitive) anywhere in PR title.', file=sys.stderr)
    print("   See: specs/doc-drift-enforcement.md §5 (escape hatch).", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Manifest load + validation
# ---------------------------------------------------------------------------


REQUIRED_PAIR_FIELDS = ("id", "tier", "code", "doc", "reason", "introduced_in")


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, int | None]:
    """Load YAML; return (data, None) on success or (None, exit_code) on error."""
    if not path.is_file():
        rc = _emit_schema_error(
            why="manifest not found",
            where=str(path),
            fix=f"ensure {path} exists or pass --manifest <path>.",
        )
        return None, rc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        rc = _emit_schema_error(
            why=f"manifest YAML parse error: {e.__class__.__name__}",
            where=str(path),
            fix="fix YAML syntax (run yamllint locally).",
        )
        return None, rc
    if not isinstance(data, dict):
        rc = _emit_schema_error(
            why="manifest must be a YAML mapping at the top level",
            where=str(path),
            fix='wrap entries under `version:`, `manifest_version:`, `pairs:` keys.',
        )
        return None, rc
    return data, None


def _validate_manifest(data: dict[str, Any], path: Path) -> tuple[list[Pair] | None, int | None]:
    """Validate schema; return (pairs, None) on success or (None, exit_code) on error."""
    # Top-level keys
    for key in ("version", "manifest_version", "pairs"):
        if key not in data:
            rc = _emit_schema_error(
                why=f"missing required top-level key `{key}`",
                where=str(path),
                fix=f"add `{key}:` to the manifest (see specs/doc-drift-enforcement.md §2).",
            )
            return None, rc
    if data["version"] != SCHEMA_VERSION:
        rc = _emit_schema_error(
            why=f"unsupported schema version `{data['version']}` (expected `{SCHEMA_VERSION}`)",
            where=str(path),
            fix=f"set `version: \"{SCHEMA_VERSION}\"` or upgrade the checker.",
        )
        return None, rc
    if not isinstance(data["manifest_version"], str) or not MANIFEST_VERSION_RE.match(data["manifest_version"]):
        rc = _emit_schema_error(
            why=f"manifest_version `{data['manifest_version']!r}` does not match `YYYY-MM-DD.N`",
            where=str(path),
            fix='use e.g. `manifest_version: "2026-05-19.1"`.',
        )
        return None, rc
    pairs_raw = data["pairs"]
    if not isinstance(pairs_raw, list) or not pairs_raw:
        rc = _emit_schema_error(
            why="`pairs:` must be a non-empty list",
            where=str(path),
            fix="add at least one pair entry (see specs/co-edit-pairs.yaml for examples).",
        )
        return None, rc

    pairs: list[Pair] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(pairs_raw):
        if not isinstance(raw, dict):
            rc = _emit_schema_error(
                why=f"pairs[{i}] is not a mapping",
                where=str(path),
                fix="each entry must be a YAML mapping with id/tier/code/doc/reason/introduced_in.",
            )
            return None, rc
        for field in REQUIRED_PAIR_FIELDS:
            if field not in raw:
                rc = _emit_schema_error(
                    why=f"pairs[{i}] missing required field `{field}`",
                    where=str(path),
                    fix=f"add `{field}:` to the entry.",
                )
                return None, rc
        pid = raw["id"]
        if not isinstance(pid, str) or not ID_RE.match(pid):
            rc = _emit_schema_error(
                why=f"pair id `{pid!r}` does not match `^[a-z][a-z0-9-]{{1,40}}$`",
                where=str(path),
                fix="use a kebab-case slug, ≤ 41 chars, starting with a lowercase letter.",
            )
            return None, rc
        if pid in seen_ids:
            rc = _emit_schema_error(
                why=f"duplicate pair id `{pid}`",
                where=str(path),
                fix="each entry's `id:` must be unique within the file.",
            )
            return None, rc
        seen_ids.add(pid)
        tier = raw["tier"]
        if tier not in ALLOWED_TIERS:
            rc = _emit_schema_error(
                why=f"pair `{pid}` tier `{tier}` not in {sorted(ALLOWED_TIERS)}",
                where=str(path),
                fix="set tier to 1 (strict), 2 (soft, reserved), or 3 (informational, reserved).",
            )
            return None, rc
        if not isinstance(raw["code"], str) or not raw["code"]:
            rc = _emit_schema_error(
                why=f"pair `{pid}` `code:` must be a non-empty string",
                where=str(path),
                fix="set `code:` to a project-relative path or fnmatch glob.",
            )
            return None, rc
        if not isinstance(raw["doc"], str) or not raw["doc"]:
            rc = _emit_schema_error(
                why=f"pair `{pid}` `doc:` must be a non-empty string",
                where=str(path),
                fix="set `doc:` to a project-relative path or fnmatch glob.",
            )
            return None, rc
        if raw["code"] == raw["doc"]:
            rc = _emit_schema_error(
                why=f"pair `{pid}` has identical `code` and `doc` paths",
                where=str(path),
                fix="a pair must have two distinct sides.",
            )
            return None, rc
        pairs.append(
            Pair(
                id=pid,
                tier=int(tier),
                code=raw["code"].replace("\\", "/"),
                doc=raw["doc"].replace("\\", "/"),
                reason=str(raw["reason"]),
                introduced_in=str(raw["introduced_in"]),
            )
        )
    return pairs, None


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


def _glob_match(path: str, pattern: str) -> bool:
    """Forward-slash-normalised fnmatch with an exact-string fast-path."""
    p = path.replace("\\", "/")
    pat = pattern.replace("\\", "/")
    if p == pat:
        return True
    if fnmatch.fnmatchcase(p, pat):
        return True
    # Trailing "/" = directory prefix match (e.g. "templates/new-project/").
    return pat.endswith("/") and p.startswith(pat)


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------


def _git_diff_files(base_ref: str, head_ref: str, repo_root: Path) -> tuple[list[str] | None, int | None]:
    """Return changed paths (forward-slash) or (None, exit_code) on error."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        rc = _emit_schema_error(
            why="git executable not found on PATH",
            where=str(repo_root),
            fix="install git, or pass --diff-files explicitly (tests / synthetic probes).",
        )
        return None, rc
    if result.returncode != 0:
        rc = _emit_schema_error(
            why=f"`git diff {base_ref}...{head_ref}` failed (rc={result.returncode})",
            where=str(repo_root),
            fix=(
                f"ensure `{base_ref}` and `{head_ref}` resolve. In CI, fetch full history "
                "with `actions/checkout@v4` `fetch-depth: 0`."
            ),
        )
        if result.stderr:
            print(f"   git stderr: {result.stderr.strip()}", file=sys.stderr)
        return None, rc
    files = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    return files, None


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def _detect_drift(pairs: list[Pair], changed: list[str]) -> list[tuple[Pair, list[str]]]:
    """Return list of (pair, touched_files_matching_this_pair) for Tier 1 drift pairs."""
    drift: list[tuple[Pair, list[str]]] = []
    for pair in pairs:
        if pair.tier != 1:
            # v0.16.0 only enforces Tier 1; Tier 2/3 reserved.
            continue
        code_hits = [f for f in changed if _glob_match(f, pair.code)]
        doc_hits = [f for f in changed if _glob_match(f, pair.doc)]
        if bool(code_hits) != bool(doc_hits):
            drift.append((pair, code_hits + doc_hits))
    return drift


def _escape_hatch_active(pr_title: str | None) -> bool:
    if not pr_title:
        return False
    return ESCAPE_HATCH in pr_title.lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _repo_root(start: Path) -> Path:
    """Walk up until a directory containing `specs/co-edit-pairs.yaml` (or `.git`) is found."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / DEFAULT_MANIFEST_REL).is_file() or (candidate / ".git").exists():
            return candidate
    return start.resolve()


def cmd_check(args: argparse.Namespace) -> int:
    root = _repo_root(Path(args.repo_root) if args.repo_root else Path.cwd())
    manifest_path = Path(args.manifest) if args.manifest else (root / DEFAULT_MANIFEST_REL)
    data, rc = _load_manifest(manifest_path)
    if rc is not None:
        return rc
    pairs, rc = _validate_manifest(data, manifest_path)
    if rc is not None:
        return rc

    if args.diff_files is not None:
        changed = [f.replace("\\", "/") for f in args.diff_files]
    else:
        changed, rc = _git_diff_files(args.base_ref, args.head_ref, root)
        if rc is not None:
            return rc

    if not changed:
        if not args.quiet:
            print(f"✅ {SCRIPT_NAME}: no files changed; nothing to gate.")
        return 0

    drift = _detect_drift(pairs, changed)

    if not drift:
        if not args.quiet:
            print(f"✅ {SCRIPT_NAME}: {len(changed)} file(s) changed; no Tier-1 drift detected.")
        return 0

    if _escape_hatch_active(args.pr_title):
        if not args.quiet:
            print(
                f"⚠ {SCRIPT_NAME}: {len(drift)} Tier-1 pair(s) drifted but PR title carries "
                f"`{ESCAPE_HATCH}`; allowing.",
                file=sys.stderr,
            )
            print(
                f"   Pairs bypassed: {', '.join(p.id for p, _ in drift)}",
                file=sys.stderr,
            )
        return 0

    return _emit_drift_block(drift)


def cmd_validate(args: argparse.Namespace) -> int:
    root = _repo_root(Path(args.repo_root) if args.repo_root else Path.cwd())
    manifest_path = Path(args.manifest) if args.manifest else (root / DEFAULT_MANIFEST_REL)
    data, rc = _load_manifest(manifest_path)
    if rc is not None:
        return rc
    pairs, rc = _validate_manifest(data, manifest_path)
    if rc is not None:
        return rc
    if not args.quiet:
        print(f"✅ {SCRIPT_NAME}: manifest valid; {len(pairs)} pair(s); version={data['version']}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="PR-time gate that fails on doc-drift (paired (code, doc) tuples).",
    )
    parser.add_argument("--manifest", help="override manifest path (default: specs/co-edit-pairs.yaml)")
    parser.add_argument("--repo-root", help="override repo root resolution (tests)")
    parser.add_argument("--quiet", action="store_true", help="suppress success stdout")

    subparsers = parser.add_subparsers(dest="cmd")

    p_check = subparsers.add_parser("check", help="run the drift check (default if no subcommand)")
    p_check.add_argument("--base-ref", default="origin/main", help="git base ref (default: origin/main)")
    p_check.add_argument("--head-ref", default="HEAD", help="git head ref (default: HEAD)")
    p_check.add_argument("--pr-title", default="", help="PR title (honoured for [no-doc-impact] escape hatch)")
    p_check.add_argument(
        "--diff-files",
        nargs="*",
        default=None,
        help="explicit changed-file list; bypasses git diff (tests / synthetic probes)",
    )

    subparsers.add_parser("validate", help="validate manifest schema only; exit 0/2")
    # No additional args.

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(argv) if argv is not None else sys.argv[1:]
    # Default subcommand: `check`. If no subcommand is present (after optional
    # global flags), inject it. Global flags before the subcommand are: --manifest,
    # --repo-root, --quiet.
    known_subcmds = {"check", "validate"}
    if not any(tok in known_subcmds for tok in raw):
        # Find first non-global-flag token; inject `check` before any subcommand-specific args.
        # Simplest reliable approach: re-route via prepending `check` at the right boundary.
        # We splice `check` after the last global flag (`--quiet` / `--manifest VAL` / `--repo-root VAL`).
        # In practice argparse parses left-to-right; the unambiguous safe approach is to insert
        # `check` at the END only if no subcommand-specific arg precedes a value.
        # Heuristic: insert `check` right before the first token that's NOT a recognised global flag/value.
        global_flags_with_value = {"--manifest", "--repo-root"}
        global_flags_solo = {"--quiet"}
        i = 0
        injected = list(raw)
        while i < len(injected):
            tok = injected[i]
            if tok in global_flags_with_value:
                i += 2  # consume flag + value
                continue
            if tok in global_flags_solo:
                i += 1
                continue
            # First non-global token → insert `check` here.
            injected.insert(i, "check")
            break
        else:
            # All tokens were global flags → append `check` at end.
            injected.append("check")
        args = parser.parse_args(injected)
    else:
        args = parser.parse_args(raw)
    if args.cmd == "validate":
        return cmd_validate(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
