"""Pre-commit hook: block manual edits to `openspec/specs/*.md`.

Populated in T09. Supersedes the T11 stub.

The OpenSpec workflow mandates that `openspec/specs/*.md` is updated only via
`openspec archive` of an approved change. Direct edits create drift between
proposal -> archive and silently corrupt the spec audit trail.

CLI
---
    python -m scripts.block_manual_spec_edit <changed-file>... [--force-with-reason TEXT]

Behaviour
---------
- For each `<changed-file>`: if the path matches `openspec/specs/**/*.md`,
  the commit is BLOCKED unless the staged commit message contains the
  marker `openspec-archive:`.
- The commit message is resolved in this order:
    1. `$PRE_COMMIT_COMMIT_MSG_FILE` env var (set by pre-commit's
       `commit-msg` stage).
    2. `<repo-root>/.git/COMMIT_EDITMSG` (fallback for `pre-commit` stage).
- If neither exists AND a protected file was staged, the commit is blocked.
- Files outside `openspec/specs/*.md` are ignored (exit 0).
- `--force-with-reason="<text>"`: allowed; logs override and exits 0.

Exit codes
----------
    0 success (or no protected files, or override applied)
    1 manual edit to protected path without archive marker
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PurePosixPath

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "block_manual_spec_edit.py"
GATE_NAME = "openspec-specs-handedit"
ARCHIVE_MARKER = "openspec-archive:"


def emit_error(
    *, why: str, where: str, fix: str, override_invocation: str | None
) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    if override_invocation is None:
        print("   OVERRIDE: none", file=sys.stderr)
    else:
        print(f"   OVERRIDE: {override_invocation}", file=sys.stderr)


def is_protected_path(path_str: str) -> bool:
    """Return True if path matches `openspec/specs/**/*.md`."""
    normalised = path_str.replace("\\", "/")
    parts = PurePosixPath(normalised).parts
    if len(parts) < 3:
        return False
    # Find an `openspec/specs/` prefix anywhere in the path.
    for i in range(len(parts) - 2):
        if parts[i] == "openspec" and parts[i + 1] == "specs":
            tail = parts[i + 2 :]
            if tail and tail[-1].endswith(".md"):
                return True
    return False


def read_commit_message(repo_root: Path) -> str | None:
    """Resolve the staged commit message. Return None if unavailable."""
    env_path = os.environ.get("PRE_COMMIT_COMMIT_MSG_FILE")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return None
    editmsg = repo_root / ".git" / "COMMIT_EDITMSG"
    if editmsg.is_file():
        try:
            return editmsg.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` looking for a `.git` directory. Fallback to `start`."""
    for candidate in (start, *start.resolve().parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="block_manual_spec_edit",
        description=(
            "Block manual edits to openspec/specs/*.md unless the commit is an "
            "`openspec archive` run."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Changed file paths (pre-commit passes these as argv).",
    )
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path.cwd())

    protected = [f for f in args.files if is_protected_path(f)]
    if not protected:
        return 0

    commit_msg = read_commit_message(repo_root)
    if commit_msg and ARCHIVE_MARKER in commit_msg:
        return 0

    first = protected[0]
    emit_error(
        why=(
            "openspec/specs/*.md edited directly (not via `openspec archive`)"
            if commit_msg
            else "openspec/specs/*.md hand-edit detected and commit message unavailable"
        ),
        where=first,
        fix=(
            "revert the hand-edit and land the change through "
            "`openspec apply` + `openspec archive` of an open change. "
            f"Archive commits carry the `{ARCHIVE_MARKER}<change-id>` marker "
            "and bypass this check automatically."
        ),
        override_invocation=(
            'python -m scripts.block_manual_spec_edit '
            + " ".join(f'"{p}"' for p in protected)
            + ' --force-with-reason="<>=10 char reason"'
        ),
    )

    result = apply_break_glass(
        gate=GATE_NAME,
        script=SCRIPT_BASENAME,
        reason=args.force_reason,
        override_allowed=True,
        repo_root=repo_root,
    )
    if result.applied:
        print(f"⚠️ OVERRIDE APPLIED: {result.reason}")
        print(
            f"   logged: {(repo_root / '.ai-playbook' / 'overrides.log').as_posix()}"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
