"""L1 hardrule: auto-pr-stream-closure.

Paired with docs/rules/auto-pr-stream-closure.rule.md.

Before opening a new auto-PR on a stream, this gate confirms no prior open
PR matches the stream's branch prefix. Emits the prior PR numbers (JSON)
when there is one, so the wrapper can close them with
`gh pr close <num> --comment "Superseded by #<new>"`.

CLI:
    python scripts/rules/auto-pr-stream-closure.rule.py before-create --stream chore/bump-playbook

Exit codes:
    0 — no prior open PR (safe to open new).
    1 — prior PR(s) exist; close them first.
    2 — schema break (no gh).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _gh_list(prefix: str) -> list[dict] | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--search",
                f"head:{prefix}",
                "--json",
                "number,headRefName,title",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout) or []
    except json.JSONDecodeError:
        return None


def before_create(stream: str) -> int:
    if os.environ.get("AIPLAYBOOK_AUTO_PR_STREAM_CLOSURE_SKIP"):
        return 0
    if not stream:
        return 0
    prs = _gh_list(stream)
    if prs is None:
        _emit_error(
            why=f"could not list PRs for stream `{stream}`",
            where="auto-pr-stream-closure",
            fix="install gh CLI and authenticate.",
        )
        return 2
    # Filter strictly to PRs whose head ref starts with the stream prefix.
    prior = [pr for pr in prs if isinstance(pr, dict) and str(pr.get("headRefName", "")).startswith(stream)]
    if prior:
        nums = [pr["number"] for pr in prior]
        print(json.dumps({"prior_open": nums}))
        _emit_error(
            why=f"open PR(s) already on stream `{stream}`: {nums}",
            where="auto-pr-stream-closure",
            fix=f"close prior PR(s) first: gh pr close {' '.join(str(n) for n in nums)} --comment 'Superseded by #<new>'.",
        )
        return 1
    print(json.dumps({"prior_open": []}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auto-pr-stream-closure")
    parser.add_argument("subcommand", choices=["before-create"])
    parser.add_argument("--stream", required=False, default="")
    args = parser.parse_args(argv)
    return before_create(args.stream)


if __name__ == "__main__":
    raise SystemExit(main())
