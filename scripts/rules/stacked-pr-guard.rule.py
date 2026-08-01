"""L1 hardrule: stacked-pr-guard.

Paired with docs/rules/stacked-pr-guard.rule.md.

Pre-merge gate. A PR whose head branch is the base of another open PR has
dependents. Merging it — especially with `--delete-branch` — orphans them:
GitHub closes a PR whose base branch disappears, refuses to reopen it
("Could not open the pull request"), and refuses to retarget a closed PR
("Cannot change the base branch of a closed pull request"). The work is
recoverable only by opening a replacement PR, which loses the review thread.

The fix is ordering, not recovery: retarget every dependent onto this PR's
base BEFORE merging this PR.

CLI:
    python scripts/rules/stacked-pr-guard.rule.py validate --pr <number>
    python scripts/rules/stacked-pr-guard.rule.py validate --pr <number> --json

Exit codes:
    0 — no open dependents; merging is safe.
    1 — open dependents found (block until retargeted).
    2 — could not determine (gh missing, unauthenticated, PR not found).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

SKIP_ENV = "AIPLAYBOOK_STACKED_PR_GUARD_SKIP"


def _emit_error(why: str, where: str, fix: str, override: str = "none") -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override}", file=sys.stderr)


def _gh(args: list[str]) -> str | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return result.stdout if result.returncode == 0 else None


def find_dependents(pr_number: str) -> tuple[str, str, list[dict]] | None:
    """Return (head, base, dependents) for ``pr_number``, or None if undeterminable.

    A dependent is any OPEN pull request whose base branch is this PR's head
    branch. Draft state is irrelevant — a draft is orphaned just as thoroughly.
    """
    raw = _gh(["pr", "view", pr_number, "--json", "headRefName,baseRefName,state"])
    if raw is None:
        return None
    try:
        pr = json.loads(raw)
    except json.JSONDecodeError:
        return None
    head = pr.get("headRefName") or ""
    base = pr.get("baseRefName") or ""
    if not head:
        return None

    listing = _gh(["pr", "list", "--state", "open", "--json", "number,title,baseRefName,headRefName", "--limit", "200"])
    if listing is None:
        return None
    try:
        others = json.loads(listing)
    except json.JSONDecodeError:
        return None

    dependents = [p for p in others if p.get("baseRefName") == head and str(p.get("number")) != str(pr_number)]
    return head, base, dependents


def validate(pr_number: str, as_json: bool = False) -> int:
    if os.environ.get(SKIP_ENV, "").strip():
        print(f"⚠ stacked_pr_guard: skipped via {SKIP_ENV}", file=sys.stderr)
        return 0

    found = find_dependents(pr_number)
    if found is None:
        _emit_error(
            why=f"could not determine dependents of PR #{pr_number}",
            where=f"PR #{pr_number}",
            fix="install the gh CLI, authenticate it, and confirm the PR exists.",
            override=f"{SKIP_ENV}=1",
        )
        return 2

    head, base, dependents = found

    if as_json:
        print(json.dumps({"pr": pr_number, "head": head, "base": base,
                          "dependents": [d["number"] for d in dependents]}, indent=2))

    if not dependents:
        return 0

    listed = ", ".join(f"#{d['number']}" for d in dependents)
    retarget = " && ".join(f"gh pr edit {d['number']} --base {base}" for d in dependents)
    _emit_error(
        why=f"PR #{pr_number} (head `{head}`) is the base of {len(dependents)} open PR(s): {listed}",
        where=f"PR #{pr_number}",
        fix=(
            f"retarget the dependent(s) onto `{base}` FIRST, then merge this PR:\n"
            f"        {retarget}\n"
            "        A dependent whose base branch is deleted is closed by GitHub and "
            "cannot be reopened or retargeted — only replaced."
        ),
        override=f"{SKIP_ENV}=1",
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stacked-pr-guard")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--pr", required=False, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if not args.pr:
        return 0
    return validate(args.pr, as_json=args.as_json)


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("stacked-pr-guard", main))
