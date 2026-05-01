"""Add a git worktree for an OpenSpec change in the canonical bare layout.

Per ``specs/git-worktree-bare-layout.md``, every consumer project that has
adopted the bare layout looks like::

    <project-root>/
    ├── .bare/
    ├── .git                # pointer "gitdir: ./.bare"
    ├── master/             # default-branch worktree
    └── <change-id>/        # one worktree per OpenSpec change in flight

This script wraps ``git worktree add`` with the playbook conventions:

- Worktree directory name == OpenSpec ``<change-id>`` (kebab-case folder under
  ``openspec/changes/``).
- Branch name == ``slice/<change-id>`` (prefix configurable via
  ``--branch-prefix``).
- Base branch auto-detected from ``origin/HEAD`` (or override with
  ``--base-branch``).
- Submodules initialised in the new worktree by default (skip with
  ``--no-submodules``).
- Refuses to create a worktree whose ``<change-id>`` does not match an
  existing ``openspec/changes/<id>/`` folder (skip with ``--no-slice-check``,
  analogous to ``/opsx:propose --no-slice``).

CLI
---
    python -m scripts.wt_add <change-id>                       # from project root
    python -m scripts.wt_add <change-id> --repo-root <path>    # explicit root
    python -m scripts.wt_add <change-id> --base-branch master  # explicit base
    python -m scripts.wt_add <change-id> --no-slice-check      # ad-hoc branches
    python -m scripts.wt_add <change-id> --dry-run             # preview only

Exit codes
----------
    0 — success (worktree created + submodules initialised)
    1 — layout violation (not a bare-layout project; no ``.bare/`` found)
    2 — precondition failed (worktree dir exists, branch exists, slice check)
    3 — git command failed
    4 — usage error (missing change-id, etc.)
"""

from __future__ import annotations

import argparse
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
class WorktreeContext:
    repo_root: Path
    bare_dir: Path
    change_id: str
    branch: str
    base_branch: str
    worktree_dir: Path


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing output. Print stderr on failure."""
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
    """Walk up from ``start`` looking for a directory containing ``.bare/``.

    Returns the first match, which is the canonical project parent dir.
    Raises SystemExit(1) if no bare layout is found above ``start``.
    """
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".bare").is_dir():
            return candidate
    print(
        f"❌ No .bare/ directory found in {start} or its parents.\n"
        f"   This script requires the bare worktree layout "
        f"(specs/git-worktree-bare-layout.md).\n"
        f"   Migrate via runbooks/git-worktree-bare-setup.md §3, or run from inside a bare-layout project.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def detect_default_branch(bare_dir: Path) -> str:
    """Return the project's default branch (e.g. ``master`` or ``main``)."""
    result = _run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=bare_dir,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        # Strip "origin/" prefix.
        ref = result.stdout.strip()
        return ref.removeprefix("origin/")
    # Fallback: probe common defaults.
    for candidate in ("master", "main"):
        probe = _run(
            ["git", "show-ref", "--verify", f"refs/remotes/origin/{candidate}"],
            cwd=bare_dir,
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    print(
        "❌ Could not detect default branch from origin/HEAD or fallback probe.\n"
        "   Pass --base-branch <name> explicitly.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def assert_slice_exists(repo_root: Path, change_id: str) -> None:
    """Refuse to add a worktree whose change-id has no matching openspec/changes folder."""
    slice_dir = repo_root / "master" / "openspec" / "changes" / change_id
    # Try common worktree names if `master/` doesn't exist (yet); fall back to default.
    if not slice_dir.is_dir():
        for wt in repo_root.iterdir():
            if wt.is_dir() and wt.name not in {".bare", ".git"}:
                candidate = wt / "openspec" / "changes" / change_id
                if candidate.is_dir():
                    return
        print(
            f"❌ openspec/changes/{change_id}/ not found in any worktree of {repo_root}.\n"
            f"   Either:\n"
            f"     - Run /opsx:propose {change_id} first to scaffold the change folder, OR\n"
            f"     - Pass --no-slice-check to bypass (ad-hoc branches that skip the slicing contract).",
            file=sys.stderr,
        )
        raise SystemExit(2)


def assert_no_collision(ctx: WorktreeContext) -> None:
    """Refuse to clobber an existing worktree directory or branch."""
    if ctx.worktree_dir.exists():
        print(
            f"❌ Worktree directory already exists: {ctx.worktree_dir}\n"
            f"   Remove it first with: git worktree remove --force {ctx.worktree_dir.name}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    branch_check = _run(
        ["git", "show-ref", "--verify", f"refs/heads/{ctx.branch}"],
        cwd=ctx.bare_dir,
        check=False,
    )
    if branch_check.returncode == 0:
        print(
            f"❌ Branch already exists: {ctx.branch}\n"
            f"   Use a different change-id or delete the branch first: git -C .bare branch -D {ctx.branch}",
            file=sys.stderr,
        )
        raise SystemExit(2)


def add_worktree(ctx: WorktreeContext, dry_run: bool) -> None:
    """Run ``git worktree add`` to create the worktree on a new branch."""
    cmd = [
        "git",
        "worktree",
        "add",
        str(ctx.worktree_dir),
        "-b",
        ctx.branch,
        f"origin/{ctx.base_branch}",
    ]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}  (cwd={ctx.bare_dir})")
        return
    _run(cmd, cwd=ctx.bare_dir)
    print(f"✅ Created worktree: {ctx.worktree_dir} on branch {ctx.branch}")


def init_submodules(ctx: WorktreeContext, dry_run: bool) -> None:
    """Initialise + clone submodules inside the new worktree."""
    cmd = ["git", "submodule", "update", "--init", "--recursive"]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}  (cwd={ctx.worktree_dir})")
        return
    if not (ctx.worktree_dir / ".gitmodules").is_file():
        # No submodules declared — silent skip.
        return
    _run(cmd, cwd=ctx.worktree_dir)
    print(f"✅ Initialised submodules in {ctx.worktree_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a git worktree for an OpenSpec change (bare layout).",
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
        "--base-branch",
        default=None,
        help="Branch to fork from (default: auto-detected from origin/HEAD).",
    )
    parser.add_argument(
        "--no-slice-check",
        action="store_true",
        help="Skip the openspec/changes/<id>/ existence check.",
    )
    parser.add_argument(
        "--no-submodules",
        action="store_true",
        help="Skip submodule init in the new worktree.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without executing them.",
    )
    args = parser.parse_args()

    if not args.change_id:
        parser.error("change_id is required")

    repo_root = find_repo_root(args.repo_root)
    bare_dir = repo_root / ".bare"

    base_branch = args.base_branch or detect_default_branch(bare_dir)
    branch = f"{args.branch_prefix}{args.change_id}"
    worktree_dir = repo_root / args.change_id

    ctx = WorktreeContext(
        repo_root=repo_root,
        bare_dir=bare_dir,
        change_id=args.change_id,
        branch=branch,
        base_branch=base_branch,
        worktree_dir=worktree_dir,
    )

    print(f"Project root: {ctx.repo_root}")
    print(f"Change ID:    {ctx.change_id}")
    print(f"Branch:       {ctx.branch}  (from origin/{ctx.base_branch})")
    print(f"Worktree dir: {ctx.worktree_dir}")

    if not args.no_slice_check:
        assert_slice_exists(ctx.repo_root, ctx.change_id)
    assert_no_collision(ctx)

    add_worktree(ctx, dry_run=args.dry_run)
    if not args.no_submodules:
        init_submodules(ctx, dry_run=args.dry_run)

    if args.dry_run:
        print("[dry-run] no changes made.")
    else:
        print(f"\nNext: cd {ctx.worktree_dir.relative_to(ctx.repo_root)} && start work on {ctx.change_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
