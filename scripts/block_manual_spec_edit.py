"""Pre-commit hook: block manual edits to `openspec/specs/*.md`.

Populated in T09. Supersedes the T11 stub. Updated in v0.8.0 to detect
file-modification (vs file-existence) — see "Bug history" below.

The OpenSpec workflow mandates that `openspec/specs/*.md` is updated only via
`openspec archive` of an approved change. Direct edits create drift between
proposal -> archive and silently corrupt the spec audit trail.

CLI
---
    python -m scripts.block_manual_spec_edit <changed-file>... [--force-with-reason TEXT]

Behaviour
---------
- For each `<changed-file>`: if the path matches `openspec/specs/**/*.md`
  AND was actually modified by the staged change (per `git diff --cached`
  or `git diff HEAD~1 HEAD`, depending on context — see _modified_files),
  the commit is BLOCKED unless the staged commit message contains the
  marker `openspec-archive:`.
- The commit message is resolved in this order:
    1. `$PRE_COMMIT_COMMIT_MSG_FILE` env var (set by pre-commit's
       `commit-msg` stage).
    2. `$PRE_COMMIT_TO_REF` and `$PRE_COMMIT_FROM_REF` env vars (set by
       pre-commit's `--from-ref/--to-ref` mode, e.g. CI on PRs).
    3. `<repo-root>/.git/COMMIT_EDITMSG` (fallback for `pre-commit` stage).
- If neither exists AND a protected file was staged, the commit is blocked.
- Files outside `openspec/specs/*.md` are ignored (exit 0).
- `--force-with-reason="<text>"`: allowed; logs override and exits 0.

Bug history
-----------
- v0.8.0-rc6 and earlier: the script considered a file "edited" if its
  PATH matched `openspec/specs/*.md`, regardless of whether the staged
  change actually modified it. Combined with `pre-commit run --all-files`
  in CI, this re-flagged every existing spec file on every PR — even when
  the PR didn't touch openspec/specs/ at all. PRs failed for `commit
  message unavailable` (HEAD has no archive marker because HEAD isn't an
  archive commit; the SPEC files came from an earlier merge). Fixed in
  v0.8.0 by intersecting the input list with the actual diff.

Exit codes
----------
    0 success (or no protected files, or override applied)
    1 manual edit to protected path without archive marker
"""
from __future__ import annotations

import argparse
import os
import subprocess
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
    """Resolve the staged commit message(s). Return None if unavailable.

    Resolution order (per v0.9.1 followup #3 — CI mode was previously broken):

    1. ``$PRE_COMMIT_COMMIT_MSG_FILE`` (commit-msg stage; set locally by
       pre-commit when the dev runs ``git commit``).
    2. ``$PRE_COMMIT_FROM_REF..$PRE_COMMIT_TO_REF`` (CI mode — set by
       ``pre-commit run --from-ref <base> --to-ref <head>``). We collect
       every commit message in that range and concatenate them so the
       ``openspec-archive:`` marker is detected if it appears in ANY of
       them. Without this branch, CI saw "commit message unavailable" on
       every archive PR (iguanatrader PR #57 was the surfacing case) and
       the hook fell through to the failure path.
    3. ``<repo-root>/.git/COMMIT_EDITMSG`` (fallback for the bare
       ``pre-commit`` stage and rare edge cases).
    """
    env_path = os.environ.get("PRE_COMMIT_COMMIT_MSG_FILE")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return None

    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        try:
            r = subprocess.run(
                [
                    "git",
                    "log",
                    "--format=%B%x00",  # NUL-delimit messages so blank lines inside don't fool us
                    f"{from_ref}..{to_ref}",
                ],
                cwd=str(repo_root),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout

        except (OSError, subprocess.SubprocessError):
            pass

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


def _modified_files(repo_root: Path) -> set[str] | None:
    """Return the set of files actually modified in the staged change, or None
    if we cannot determine (e.g. no git history / no staged changes).

    Resolution order, matching pre-commit's invocation modes:

    1. ``$PRE_COMMIT_FROM_REF..$PRE_COMMIT_TO_REF`` (set in `--from-ref/--to-ref`
       mode, e.g. CI on PRs running `pre-commit run --from-ref origin/main
       --to-ref HEAD`). The diff between those refs is the "real" PR diff.
    2. ``git diff --cached`` (staged changes; default for `pre-commit run`
       at commit time).
    3. ``git diff HEAD~1 HEAD`` (fallback for push-event CI without --from-ref).

    Returns paths relative to repo root. Pre-commit passes file arguments
    using forward slashes, so we normalize to forward slashes.
    """
    import subprocess

    def _run_diff(args: list[str]) -> set[str] | None:
        try:
            result = subprocess.run(
                args,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except FileNotFoundError:
            return None
        if result.returncode != 0:
            return None
        files = {ln.strip() for ln in result.stdout.splitlines() if ln.strip()}
        return files or None

    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        files = _run_diff(
            ["git", "diff", "--name-only", f"{from_ref}..{to_ref}"]
        )
        if files is not None:
            return files

    # Staged-mode (commit time): git diff --cached.
    files = _run_diff(["git", "diff", "--cached", "--name-only"])
    if files is not None:
        return files

    # Push-event CI fallback.
    files = _run_diff(["git", "diff", "--name-only", "HEAD~1", "HEAD"])
    if files is not None:
        return files

    return None  # Cannot determine — caller decides whether to fail open or closed.


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

    candidates = [f for f in args.files if is_protected_path(f)]
    if not candidates:
        return 0

    # Filter candidates to those ACTUALLY modified by the staged change.
    # Pre-commit may pass us files at protected paths that exist on the
    # current branch but were NOT touched by this commit (most common when
    # CI runs `pre-commit run --all-files` and the spec files were added
    # by a previous archive commit on main). The bug we fix here:
    # pre-v0.8.0 the script blocked every PR that touched ANY file as
    # long as `openspec/specs/*.md` existed, because it conflated
    # "file at protected path exists" with "file modified by this PR".
    modified = _modified_files(repo_root)
    if modified is not None:
        # Normalize: pre-commit passes argv with forward slashes; git diff
        # --name-only also uses forward slashes. So direct membership.
        protected = [f for f in candidates if f.replace("\\", "/") in modified]
        if not protected:
            # All candidate files are at protected paths but not in the
            # diff — nothing to enforce on, exit 0.
            return 0
    else:
        # Could not determine the diff — fall back to old (conservative)
        # behaviour: treat every input file as modified.
        protected = candidates

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
