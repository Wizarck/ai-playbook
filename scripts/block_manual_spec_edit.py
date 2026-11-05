"""Pre-commit hook: block manual edits to `openspec/specs/*.md`.

Populated in T09. Supersedes the T11 stub. Updated in v0.8.0 to detect
file-modification (vs file-existence) — see "Bug history" below.

The OpenSpec workflow mandates that `openspec/specs/*.md` is updated only via
`openspec archive` of an approved change. Direct edits create drift between
proposal -> archive and silently corrupt the spec audit trail.

CLI
---
    # commit-msg stage (local commits) — pre-commit appends the message file:
    python -m scripts.block_manual_spec_edit --commit-msg-file <msg-file>
    # pre-commit stage / CI (`pre-commit run --from-ref A --to-ref B`):
    python -m scripts.block_manual_spec_edit <changed-file>... [--force-with-reason TEXT]

Behaviour
---------
- For each protected path (`openspec/specs/**/*.md`) actually modified by
  the change (per `git diff`, see _modified_files), the commit is BLOCKED
  unless the commit message contains the marker `openspec-archive:`.
- `--commit-msg-file` (commit-msg stage, the local mode): the message is
  read from that file and the protected paths from `git diff --cached`.
  git also runs this stage for merge commits; there a path counts only if
  its staged content is in no parent and is not git's automatic merge (see
  _commit_paths), so merging in a spec archived on another branch passes.
  This is the only local stage where the message being committed exists:
  git runs the `pre-commit` hook BEFORE writing it, so `.git/COMMIT_EDITMSG`
  at that point holds the PREVIOUS commit's message (the old fallback to it
  let hand-edits through after an archive commit and blocked real archives).
- Without `--commit-msg-file` the message is resolved in this order:
    1. `$PRE_COMMIT_COMMIT_MSG_FILE` env var (manual override; pre-commit
       itself never sets it).
    2. `$PRE_COMMIT_TO_REF` and `$PRE_COMMIT_FROM_REF` env vars (set by
       pre-commit's `--from-ref/--to-ref` mode, e.g. CI on PRs).
    3. Nothing staged (e.g. CI `--all-files` on a pushed commit): HEAD's
       message, matching the `HEAD~1..HEAD` diff used in that case.
- Local pre-commit stage (staged changes, no message yet): exit 0 with a
  notice when a commit-msg hook will run this guard (_commit_msg_stage_wired)
  — that stage decides. Otherwise (e.g. a pre-commit-stage entry kept from
  v0.24.1) the commit is blocked with the steps to move the hook, instead of
  passing unchecked. If the message cannot be resolved for any other reason
  AND a protected file changed, the commit is blocked.
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
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

# Force UTF-8 stdio.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


# Make `from scripts...` resolve when run by path (`python .ai-playbook/scripts/...`), not just via -m.
_PLAYBOOK_ROOT = str(Path(__file__).resolve().parents[1])
if _PLAYBOOK_ROOT not in sys.path:
    sys.path.insert(0, _PLAYBOOK_ROOT)

from scripts._break_glass import add_break_glass_flag, apply_break_glass  # noqa: E402

SCRIPT_BASENAME = "block_manual_spec_edit.py"
GATE_NAME = "openspec-specs-handedit"
ARCHIVE_MARKER = "openspec-archive:"
# git's cut line (`git commit -v`, --cleanup=scissors): everything from it on is dropped.
_SCISSORS_RE = re.compile(r"^\S -{24} >8 -{24}[ \t]*$", re.MULTILINE)


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


def _has_staged(repo_root: Path) -> bool | None:
    """True/False = index differs from HEAD or not; None = cannot tell (no repo)."""
    try:
        rc = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(repo_root), check=False, capture_output=True,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: False, 1: True}.get(rc)


def _read_message_file(path: Path) -> str | None:
    """The message as git will record it, from a message file.

    The file holds more than the message: git's ``#`` comment lines (status
    template, ``# Conflicts:``) and, under ``git commit -v``, the diff below the
    scissors line — a marker quoted there must not count. It need not be UTF-8
    (e.g. ``git commit -F`` of an ANSI file): undecodable bytes become U+FFFD.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cut = _SCISSORS_RE.search(raw)
    if cut:
        raw = raw[: cut.start()]
    return "\n".join(ln for ln in raw.splitlines() if not ln.startswith("#"))


def read_commit_message(repo_root: Path) -> str | None:
    """Resolve the commit message(s) for pre-commit-stage / CI runs.

    The commit-msg stage passes ``--commit-msg-file`` and never gets here.
    Resolution order (per v0.9.1 followup #3 — CI mode was previously broken):

    1. ``$PRE_COMMIT_COMMIT_MSG_FILE`` (manual override; pre-commit never
       sets it).
    2. ``$PRE_COMMIT_FROM_REF..$PRE_COMMIT_TO_REF`` (CI mode — set by
       ``pre-commit run --from-ref <base> --to-ref <head>``). We collect
       every commit message in that range and concatenate them so the
       ``openspec-archive:`` marker is detected if it appears in ANY of
       them. Without this branch, CI saw "commit message unavailable" on
       every archive PR (consumer-e PR #57 was the surfacing case) and
       the hook fell through to the failure path.
    3. Nothing staged: HEAD's message (the change under test is HEAD, cf.
       the ``HEAD~1 HEAD`` diff fallback). With staged changes the message
       being committed does not exist yet — ``.git/COMMIT_EDITMSG`` is the
       PREVIOUS commit's — so return ``None``.
    """
    env_path = os.environ.get("PRE_COMMIT_COMMIT_MSG_FILE")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return _read_message_file(p)

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
                errors="replace",
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout

        except (OSError, subprocess.SubprocessError):
            pass

    try:
        if _has_staged(repo_root) is False:  # nothing staged → the change is HEAD
            r = subprocess.run(
                ["git", "log", "-1", "--format=%B", "HEAD"],
                cwd=str(repo_root), check=False, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                return r.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _diff_names(repo_root: Path, *diff_args: str) -> set[str] | None:
    """Paths ``git diff --name-only <diff_args>`` lists; None when git fails.

    ``-z`` output is never C-quoted, so a non-ASCII path such as
    ``openspec/specs/métricas/spec.md`` arrives verbatim (as in pre-commit's
    argv) instead of as ``"openspec/specs/m\\303\\251tricas/spec.md"``, which
    ``is_protected_path`` would not recognise.
    """
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "-z", *diff_args],
            cwd=str(repo_root), check=False, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


def _git_out(repo_root: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(repo_root), check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def _merge_heads(repo_root: Path) -> list[str]:
    """The other parents of the merge being concluded (``MERGE_HEAD``), or []."""
    rc, out = _git_out(repo_root, "rev-parse", "--git-path", "MERGE_HEAD")
    if rc != 0:
        return []
    path = Path(out.strip())
    try:
        return (path if path.is_absolute() else repo_root / path).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        return []


def _commit_paths(repo_root: Path) -> set[str]:
    """Paths whose content the commit being made introduces (commit-msg stage).

    For a merge, a path counts only if its staged content matches no parent and
    is not git's own automatic merge of it: the rest came unchanged from one side
    (e.g. a spec archived on the merged branch) or from a clean merge of both,
    and each side was judged when it was committed. Conflict resolutions and
    edits slipped into the merge are still judged.
    """
    paths = _diff_names(repo_root, "--cached") or set()
    heads = _merge_heads(repo_root)
    for head in heads:
        other = _diff_names(repo_root, "--cached", head)
        if other is None:
            return paths  # cannot tell: judge the whole merge
        paths &= other
    if paths and len(heads) == 1:
        # `merge-tree --write-tree` needs git >= 2.38; rc 1 = conflicts (tree still written).
        rc, out = _git_out(repo_root, "merge-tree", "--write-tree", "HEAD", heads[0])
        tree = out.split("\n", 1)[0].strip()
        if rc in (0, 1) and re.fullmatch(r"[0-9a-f]{40,64}", tree):
            auto = _diff_names(repo_root, "--cached", tree)
            if auto is not None:
                paths &= auto
    return paths


def _commit_msg_stage_wired(repo_root: Path) -> bool:
    """Whether a commit-msg hook will run this guard with ``--commit-msg-file``.

    The hook must exist (``--git-path`` honours core.hooksPath) and either call
    this script itself, or be pre-commit's with a config that wires the
    ``--commit-msg-file`` mode. It only decides whether the pre-commit stage may
    defer: a miss blocks with migration steps instead of passing unchecked.
    """
    rc, out = _git_out(repo_root, "rev-parse", "--git-path", "hooks/commit-msg")
    if rc != 0:
        return False
    hook = Path(out.strip())
    try:
        hook_text = (hook if hook.is_absolute() else repo_root / hook).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "block_manual_spec_edit" in hook_text:
        return "--commit-msg-file" in hook_text
    if "pre-commit" not in hook_text:
        return False
    m = re.search(r"--config[= ]([^\s)\"']+)", hook_text)
    try:
        config = (repo_root / (m.group(1) if m else ".pre-commit-config.yaml")).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return False
    code = "\n".join(ln.split("#", 1)[0] for ln in config.splitlines())
    return "block_manual_spec_edit" in code and "--commit-msg-file" in code


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
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        files = _diff_names(repo_root, f"{from_ref}..{to_ref}")
        if files:
            return files

    # Staged-mode (commit time): git diff --cached.
    files = _diff_names(repo_root, "--cached")
    if files:
        return files

    # Push-event CI fallback.
    files = _diff_names(repo_root, "HEAD~1", "HEAD")
    if files:
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
    parser.add_argument(
        "--commit-msg-file",
        default=None,
        help="commit-msg stage: the message file pre-commit passes. Protected "
        "paths are then taken from `git diff --cached`, not from argv.",
    )
    add_break_glass_flag(parser)
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path.cwd())

    if args.commit_msg_file:
        args.files = sorted(_commit_paths(repo_root))

    candidates = [f for f in args.files if is_protected_path(f)]
    if not candidates:
        return 0

    commit_msg: str | None = None
    if args.commit_msg_file:
        commit_msg = _read_message_file(Path(args.commit_msg_file))

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

    unwired = False
    if not args.commit_msg_file:
        commit_msg = read_commit_message(repo_root)
        if commit_msg is None and _has_staged(repo_root):
            # Local pre-commit stage: git has not written this commit's message
            # yet, so there is nothing honest to check. The commit-msg stage
            # (`--commit-msg-file`) decides — if it is wired; otherwise passing
            # here would leave the commit unchecked (a pre-commit-stage entry
            # kept from v0.24.1 or earlier).
            if _commit_msg_stage_wired(repo_root):
                print(
                    "ℹ️  block_manual_spec_edit: message not written yet at the pre-commit "
                    "stage; deferring to the commit-msg stage.",
                    file=sys.stderr,
                )
                return 0
            unwired = True
    if commit_msg and ARCHIVE_MARKER in commit_msg:
        return 0

    first = protected[0]
    fix = (
        "revert the hand-edit and land the change through "
        "`openspec apply` + `openspec archive` of an open change. "
        f"Archive commits carry the `{ARCHIVE_MARKER}<change-id>` marker "
        "and bypass this check automatically."
    )
    if unwired:
        why = ("openspec/specs/*.md change checked at the pre-commit stage, where the "
               "commit message does not exist yet, and no commit-msg hook runs this guard")
        fix = ("move the hook to the commit-msg stage: entry `python .ai-playbook/scripts/"
               "block_manual_spec_edit.py --commit-msg-file` with `stages: [commit-msg]` (see "
               ".ai-playbook/templates/new-project/.pre-commit-config.yaml.tmpl), top-level "
               "`default_stages: [pre-commit]`, then `pre-commit install --hook-type commit-msg`.")
    elif commit_msg:
        why = "openspec/specs/*.md edited directly (not via `openspec archive`)"
    else:
        why = "openspec/specs/*.md hand-edit detected and commit message unavailable"
    emit_error(
        why=why,
        where=first,
        fix=fix,
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
