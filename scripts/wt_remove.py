"""Remove a git worktree + its ``slice/<change-id>`` branch in the bare layout.

Mirror of :mod:`wt_add`. Use after a PR is merged or closed to retire the
worktree and its local branch in one step.

Per ``docs/concepts/git-worktree-bare-layout.md``, every consumer project that
has adopted the bare layout looks like::

    <project-root>/
    ├── .bare/
    ├── .git                # pointer "gitdir: ./.bare"
    ├── master/             # default-branch worktree
    └── <change-id>/        # worktree to remove

This script wraps ``git worktree remove`` + ``git branch -D`` with two safety
checks:

- The worktree directory must exist (else nothing to remove).
- The corresponding pull request must be MERGED or CLOSED (detected via
  ``gh pr view slice/<change-id>``). Override with ``--force`` to skip.

The companion :mod:`wt_sweep` covers the bulk-cleanup case.

CLI
---
    python scripts/wt_remove.py <change-id>
    python scripts/wt_remove.py <change-id> --force            # skip PR check
    python scripts/wt_remove.py <change-id> --keep-branch      # only remove worktree
    python scripts/wt_remove.py <change-id> --repo-root <path>
    python scripts/wt_remove.py <change-id> --dry-run

Exit codes
----------
    0 — success
    1 — layout violation (no ``.bare/``)
    2 — precondition failed (worktree/branch missing, or PR still open)
    3 — git command failed
    4 — usage error
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Force UTF-8 I/O — Windows default cp1252 cannot encode the ✅/⚠️/❌ sigils.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


@dataclass
class RemoveContext:
    repo_root: Path
    bare_dir: Path
    change_id: str
    branch: str
    worktree_dir: Path


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(3)
    return result


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".bare").is_dir():
            return candidate
    print(
        f"❌ No .bare/ directory found in {start} or its parents.\n"
        f"   This script requires the bare worktree layout "
        f"(docs/concepts/git-worktree-bare-layout.md).",
        file=sys.stderr,
    )
    raise SystemExit(1)


def assert_worktree_exists(ctx: RemoveContext) -> None:
    if not ctx.worktree_dir.exists():
        print(
            f"❌ Worktree directory does not exist: {ctx.worktree_dir}\n"
            f"   Nothing to remove. If the branch still exists locally, "
            f"delete it manually: git -C .bare branch -D {ctx.branch}",
            file=sys.stderr,
        )
        raise SystemExit(2)


def branch_exists(ctx: RemoveContext) -> bool:
    result = _run(
        ["git", "show-ref", "--verify", f"refs/heads/{ctx.branch}"],
        cwd=ctx.bare_dir,
        check=False,
    )
    return result.returncode == 0


def lookup_pr_state(branch: str, repo_root: Path) -> str | None:
    """Return ``'OPEN' | 'MERGED' | 'CLOSED' | None`` for the PR whose head is ``branch``.

    ``None`` means no PR was found (rare: an ad-hoc branch never pushed/PR'd).
    Returns ``None`` silently if ``gh`` is unavailable or unauthenticated — the
    caller decides whether that's a hard failure (only when not ``--force``).
    """
    if shutil.which("gh") is None:
        return None
    # `gh pr list --head <branch>` returns 0 with empty list if no PR exists.
    result = _run(
        ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "state", "--limit", "1"],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        return None
    import json

    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not items:
        return None
    state = items[0].get("state")
    return state if isinstance(state, str) else None


def assert_pr_resolved(ctx: RemoveContext, force: bool) -> None:
    state = lookup_pr_state(ctx.branch, ctx.repo_root)
    if state is None:
        # No PR or gh unavailable — only an issue if we cannot verify.
        # Without --force, refuse to proceed silently.
        if force:
            print(f"⚠️  No PR state available for {ctx.branch}; --force given, proceeding.")
            return
        print(
            f"⚠️  Could not determine PR state for {ctx.branch}.\n"
            f"   Either no PR exists, or `gh` is unavailable/unauthenticated.\n"
            f"   Pass --force to remove anyway.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if state == "OPEN" and not force:
        print(
            f"❌ Refusing to remove {ctx.branch}: PR is still OPEN.\n"
            f"   Close or merge the PR first, or pass --force to override.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(f"✅ PR state for {ctx.branch}: {state}")


def remove_worktree(ctx: RemoveContext, dry_run: bool) -> None:
    cmd = ["git", "worktree", "remove", "--force", str(ctx.worktree_dir)]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}  (cwd={ctx.bare_dir})")
        return
    _run(cmd, cwd=ctx.bare_dir)
    print(f"✅ Removed worktree: {ctx.worktree_dir}")
    # Belt + suspenders: some submodule directories survive --force on Windows.
    if ctx.worktree_dir.exists():
        try:
            shutil.rmtree(ctx.worktree_dir, ignore_errors=True)
        except OSError:
            pass


def delete_branch(ctx: RemoveContext, dry_run: bool) -> None:
    cmd = ["git", "branch", "-D", ctx.branch]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}  (cwd={ctx.bare_dir})")
        return
    if not branch_exists(ctx):
        print(f"⚠️  Branch {ctx.branch} does not exist locally; skipping branch delete.")
        return
    _run(cmd, cwd=ctx.bare_dir)
    print(f"✅ Deleted local branch: {ctx.branch}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove a git worktree + its slice/<change-id> branch (bare layout).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("change_id", help="OpenSpec change-id (kebab-case).")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing .bare/ (default: walk up from cwd).",
    )
    parser.add_argument(
        "--branch-prefix",
        default="slice/",
        help="Prefix prepended to change-id to form the branch name (default: slice/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip PR state check (allow removal even if PR is OPEN or unknown).",
    )
    parser.add_argument(
        "--keep-branch",
        action="store_true",
        help="Remove the worktree but keep the local branch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without executing them.",
    )
    args = parser.parse_args(argv)

    if not args.change_id:
        parser.error("change_id is required")

    repo_root = find_repo_root(args.repo_root)
    bare_dir = repo_root / ".bare"
    branch = f"{args.branch_prefix}{args.change_id}"
    worktree_dir = repo_root / args.change_id

    ctx = RemoveContext(
        repo_root=repo_root,
        bare_dir=bare_dir,
        change_id=args.change_id,
        branch=branch,
        worktree_dir=worktree_dir,
    )

    print(f"Project root: {ctx.repo_root}")
    print(f"Change ID:    {ctx.change_id}")
    print(f"Branch:       {ctx.branch}")
    print(f"Worktree dir: {ctx.worktree_dir}")

    assert_worktree_exists(ctx)
    assert_pr_resolved(ctx, force=args.force)

    remove_worktree(ctx, dry_run=args.dry_run)
    if not args.keep_branch:
        delete_branch(ctx, dry_run=args.dry_run)
    else:
        print(f"… --keep-branch given; leaving {ctx.branch} in place.")

    if args.dry_run:
        print("[dry-run] no changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
