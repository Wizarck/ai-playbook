"""Bulk-clean zombie ``slice/<id>`` branches (and optionally their worktrees).

After PRs are merged — especially via squash-merge — local ``slice/<id>``
branches accumulate because:

1. ``git worktree remove`` does not delete the underlying branch.
2. Squash-merge creates a new commit on the default branch; the original
   slice tip is not reachable from main, so ``git branch --merged`` cannot
   detect it.

This sweeper scans every local ``slice/*`` branch, queries GitHub for the
state of the matching PR, and prints a deletion plan. ``--apply`` actually
executes it. Branches whose PR is still OPEN — or whose PR cannot be
determined — are left alone.

Companion to :mod:`wt_add` and :mod:`wt_remove`. Use periodically (or after a
backlog reset) to keep ``git branch --list 'slice/*'`` honest.

CLI
---
    python scripts/wt_sweep.py                          # dry-run, print plan
    python scripts/wt_sweep.py --apply                  # execute the plan
    python scripts/wt_sweep.py --apply --remote         # also push --delete origin
    python scripts/wt_sweep.py --include-worktrees      # also remove dangling worktrees
    python scripts/wt_sweep.py --branch-prefix slice/

Exit codes
----------
    0 — success (dry-run or apply both succeed)
    1 — layout violation (no ``.bare/``)
    2 — ``gh`` CLI missing / unauthenticated
    3 — git/gh command failed during apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


@dataclass
class BranchEntry:
    name: str
    tip: str
    has_worktree: bool
    pr_number: int | None
    pr_state: str | None  # OPEN / MERGED / CLOSED / None

    @property
    def is_safe_to_delete(self) -> bool:
        return self.pr_state in {"MERGED", "CLOSED"}

    @property
    def action(self) -> str:
        if self.pr_state == "OPEN":
            return "skip (PR OPEN)"
        if self.pr_state in {"MERGED", "CLOSED"}:
            wt = " + worktree" if self.has_worktree else ""
            return f"DELETE branch{wt}"
        if self.pr_state is None and self.pr_number is None:
            return "skip (no PR found)"
        return "skip (unknown PR state)"


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
        f"❌ No .bare/ directory found in {start} or its parents.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def require_gh() -> None:
    if shutil.which("gh") is None:
        print(
            "❌ `gh` CLI not found in PATH.\n"
            "   Install: https://cli.github.com/  then `gh auth login`.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    # Quick auth probe.
    result = _run(["gh", "auth", "status"], check=False)
    if result.returncode != 0:
        print(
            "❌ `gh` is not authenticated.\n"
            "   Run: gh auth login",
            file=sys.stderr,
        )
        raise SystemExit(2)


def list_local_branches(bare_dir: Path, prefix: str) -> list[tuple[str, str]]:
    """Return ``(branch_name, short_tip)`` for every local branch with ``prefix``."""
    result = _run(
        ["git", "for-each-ref", "--format=%(refname:short)\t%(objectname:short)", f"refs/heads/{prefix}"],
        cwd=bare_dir,
    )
    out: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, tip = line.partition("\t")
        out.append((name.strip(), tip.strip()))
    return out


def list_worktree_dirs(repo_root: Path, bare_dir: Path) -> set[str]:
    """Return the set of worktree directory *names* (not paths) currently linked."""
    result = _run(["git", "worktree", "list", "--porcelain"], cwd=bare_dir)
    names: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ").strip())
            try:
                rel = path.resolve().relative_to(repo_root.resolve())
                names.add(rel.parts[0])
            except (ValueError, OSError):
                continue
    return names


def lookup_pr(branch: str, repo_root: Path) -> tuple[int | None, str | None]:
    result = _run(
        ["gh", "pr", "list", "--head", branch, "--state", "all",
         "--json", "number,state", "--limit", "1"],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        return (None, None)
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return (None, None)
    if not items:
        return (None, None)
    item = items[0]
    return (item.get("number"), item.get("state"))


def gather_entries(
    repo_root: Path,
    bare_dir: Path,
    prefix: str,
) -> list[BranchEntry]:
    branches = list_local_branches(bare_dir, prefix)
    worktree_names = list_worktree_dirs(repo_root, bare_dir)
    entries: list[BranchEntry] = []
    for name, tip in branches:
        change_id = name.removeprefix(prefix)
        has_wt = change_id in worktree_names
        pr_num, pr_state = lookup_pr(name, repo_root)
        entries.append(BranchEntry(
            name=name,
            tip=tip,
            has_worktree=has_wt,
            pr_number=pr_num,
            pr_state=pr_state,
        ))
    return entries


def print_plan(entries: list[BranchEntry]) -> None:
    if not entries:
        print("No matching local branches found.")
        return
    name_w = max(len(e.name) for e in entries)
    print(f"{'BRANCH'.ljust(name_w)}  {'TIP':<8}  {'PR':<6}  {'STATE':<10}  WT  ACTION")
    print("-" * (name_w + 60))
    for e in entries:
        pr_label = f"#{e.pr_number}" if e.pr_number is not None else "-"
        state = e.pr_state or "-"
        wt = "yes" if e.has_worktree else "no"
        print(f"{e.name.ljust(name_w)}  {e.tip:<8}  {pr_label:<6}  {state:<10}  {wt:<3} {e.action}")
    safe = [e for e in entries if e.is_safe_to_delete]
    print()
    print(f"Total: {len(entries)} branches | safe to delete: {len(safe)}")


def apply_deletes(
    entries: list[BranchEntry],
    repo_root: Path,
    bare_dir: Path,
    include_worktrees: bool,
    delete_remote: bool,
) -> int:
    deleted = 0
    for e in entries:
        if not e.is_safe_to_delete:
            continue
        if e.has_worktree:
            if include_worktrees:
                change_id = e.name.removeprefix("slice/")  # convention
                wt_dir = repo_root / change_id
                _run(["git", "worktree", "remove", "--force", str(wt_dir)], cwd=bare_dir, check=False)
                print(f"✅ Removed worktree: {wt_dir}")
                if wt_dir.exists():
                    shutil.rmtree(wt_dir, ignore_errors=True)
            else:
                print(f"⚠️  Skipping {e.name}: has worktree (pass --include-worktrees to remove it).")
                continue
        _run(["git", "branch", "-D", e.name], cwd=bare_dir, check=False)
        print(f"✅ Deleted local branch: {e.name}")
        if delete_remote:
            push = _run(["git", "push", "origin", "--delete", e.name], cwd=bare_dir, check=False)
            if push.returncode == 0:
                print(f"✅ Deleted remote branch: origin/{e.name}")
            else:
                # Likely already deleted (e.g. delete_branch_on_merge=true).
                print(f"… origin/{e.name}: already absent or push failed (non-fatal).")
        deleted += 1
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-clean zombie slice/<id> branches whose PR is merged or closed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing .bare/ (default: walk up from cwd).",
    )
    parser.add_argument(
        "--branch-prefix",
        default="slice/",
        help="Branch prefix to scan (default: slice/).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the deletion plan (default: dry-run, print plan only).",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Also delete the remote branch via `git push --delete origin <branch>`. Implies --apply.",
    )
    parser.add_argument(
        "--include-worktrees",
        action="store_true",
        help="Also remove worktrees for branches whose PR is merged/closed.",
    )
    args = parser.parse_args(argv)

    repo_root = find_repo_root(args.repo_root)
    bare_dir = repo_root / ".bare"

    require_gh()

    entries = gather_entries(repo_root, bare_dir, args.branch_prefix)
    print_plan(entries)

    do_apply = args.apply or args.remote
    if not do_apply:
        print("\n(dry-run — pass --apply to execute, --remote to also delete origin/*.)")
        return 0

    print()
    deleted = apply_deletes(
        entries,
        repo_root=repo_root,
        bare_dir=bare_dir,
        include_worktrees=args.include_worktrees,
        delete_remote=args.remote,
    )
    print(f"\nDone. {deleted} branch(es) deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
