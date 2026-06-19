"""L1 hardrule: bare-layout (paired with docs/rules/bare-layout.rule.md).

Detects whether a consumer repository uses the canonical bare-repo + per-branch
worktree layout, or the legacy single-tree default.

The `apply` subcommand is **plan-only**: it prints the migration plan (the
sequence of git + filesystem commands from runbook §3) but does NOT execute
them. Migration stays operator-driven by design — folder renames and bare-repo
swaps are high-blast-radius and warrant manual review.

CLI:
    python scripts/rules/bare-layout.rule.py validate
    python scripts/rules/bare-layout.rule.py apply [--dry-run]

Exit codes:
    0 — bare layout detected, or no git repo here (not applicable).
    1 — single-tree layout detected (drift). Run `apply` to see the migration plan.
    2 — fatal (filesystem error, malformed `.git` file, etc.).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKIP_ENV = "AIPLAYBOOK_BARE_LAYOUT_SKIP"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {SKIP_ENV}=1", file=sys.stderr)


def _consumer_root(cwd: Path | None = None) -> Path | None:
    """Locate the consumer root by walking up for a `.git` (file or dir) or `.bare/`.

    Bare-layout consumers have `.git` (a file) + `.bare/` (a dir) at the root.
    Single-tree consumers have `.git/` (a dir) at the root.
    The lookup walks parents until either is found.
    """
    cur = (cwd or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / ".bare").is_dir() or (p / ".git").exists():
            return p
    return None


def _detect_layout(root: Path) -> str:
    """Return one of: 'bare', 'single_tree', 'malformed', 'none'."""
    bare_dir = root / ".bare"
    git_path = root / ".git"
    if bare_dir.is_dir() and git_path.is_file():
        try:
            content = git_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return "malformed"
        if content.startswith("gitdir:") and ".bare" in content:
            return "bare"
        return "malformed"
    if git_path.is_dir():
        return "single_tree"
    return "none"


def validate(cwd: Path | None = None) -> int:
    if os.environ.get(SKIP_ENV):
        return 0
    root = _consumer_root(cwd)
    if root is None:
        # Not applicable — not a git repo here.
        return 0
    layout = _detect_layout(root)
    if layout == "bare":
        return 0
    if layout == "none":
        return 0
    if layout == "malformed":
        _emit_error(
            why="`.git` pointer or `.bare/` is malformed",
            where=str(root),
            fix="reconcile by hand; see docs/concepts/git-worktree-bare-layout.md §Invariants.",
        )
        return 2
    # single_tree
    _emit_error(
        why="single-tree layout detected (drift)",
        where=str(root),
        fix="run `python .ai-playbook/scripts/rules/bare-layout.rule.py apply` to see migration plan.",
    )
    return 1


def _build_plan(root: Path) -> list[str]:
    """Return the migration plan as a list of human-readable steps + shell commands."""
    repo_name = root.name
    parent = root.parent
    sibling_new = parent / f"{repo_name}-new"
    backup = parent / f"{repo_name}.pre-migration"
    return [
        "Migration plan: single-tree → bare-repo + per-branch worktree",
        f"  source : {root}",
        f"  sibling: {sibling_new}  (transient build location)",
        f"  backup : {backup}        (rename of source after swap; manual cleanup later)",
        "",
        "Steps (run each from a terminal OUTSIDE the source repo):",
        "",
        "  # 1. Pre-flight: confirm clean state, no unpushed commits.",
        f"  cd {root}",
        "  git status --short        # must be empty",
        "  git log --oneline @{upstream}..HEAD   # must be empty",
        "  git worktree list         # note additional worktrees",
        "",
        "  # 2. Build the new layout as a sibling.",
        f"  mkdir {sibling_new} && cd {sibling_new}",
        f"  git clone --bare $(git -C {root} remote get-url origin) .bare",
        '  git -C .bare config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"',
        "  git -C .bare fetch origin --prune",
        '  echo "gitdir: ./.bare" > .git',
        "",
        "  # 3. Add default-branch worktree.",
        "  DEFAULT=$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')",
        "  git worktree add $DEFAULT $DEFAULT",
        "",
        "  # 4. Add per-branch worktrees for every branch noted in step 1.",
        "  # git worktree add <change-id> slice/<change-id>",
        "",
        "  # 5. Swap dirs.",
        f"  mv {root} {backup}",
        f"  mv {sibling_new} {root}",
        f"  git -C {root}/.bare worktree repair",
        "",
        "  # 6. Verify, then (later, after confirming everything works):",
        f"  #    rm -rf {backup}",
        "",
        "Reference: docs/runbooks/git-worktree-bare-setup.md §3 (Migrate a legacy single-tree clone).",
    ]


def apply(*, dry_run: bool, cwd: Path | None = None) -> int:
    """Print the migration plan. Always plan-only — never executes.

    The `--dry-run` flag is accepted for contract uniformity with other rules,
    but bare-layout's `apply` is plan-only by design (migrations stay
    operator-driven). `dry_run=True` and `dry_run=False` produce identical
    output and exit code; the only difference is the header banner.
    """
    root = _consumer_root(cwd)
    if root is None:
        print("ok: no git repo detected here (not applicable)")
        return 0
    layout = _detect_layout(root)
    if layout == "bare":
        print(f"ok: {root} already uses bare layout (no-op)")
        return 0
    if layout == "none":
        print(f"ok: {root} is not a git repo (not applicable)")
        return 0
    if layout == "malformed":
        print(
            f"refuse: {root} has a malformed `.git` / `.bare` state; "
            "reconcile by hand before re-running apply.",
            file=sys.stderr,
        )
        return 2
    # single_tree: emit plan.
    banner = "[plan only — bare-layout apply does NOT execute the migration]"
    if dry_run:
        banner = "[dry-run] " + banner
    print(banner)
    print()
    for line in _build_plan(root):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bare-layout")
    parser.add_argument("subcommand", choices=["validate", "apply"])
    parser.add_argument("--dry-run", action="store_true", help="With 'apply': add a dry-run banner.")
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    if args.subcommand == "apply":
        return apply(dry_run=args.dry_run)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("bare-layout", main))
