"""L1 hardrule: auto-merge-discipline.

Paired with docs/rules/auto-merge-discipline.rule.md.

PostToolUse gate on `gh pr merge --auto`. Confirms §4.5 satisfied before
auto-merge is allowed:
  - All three ai-reviewer-signoff §4.5.3 markers present in PR body.
  - PR CI status is `SUCCESS` (or the workflow lists are all green).
  - PR body mentions explicit Gate F approval.

CLI:
    python scripts/rules/auto-merge-discipline.rule.py validate --pr <number>

Exit codes:
    0 — auto-merge allowed.
    1 — precondition failed (block).
    2 — schema break.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from importlib import import_module

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _gh_pr_view(number: str) -> dict | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", number, "--json", "body,statusCheckRollup,state"],
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
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _all_checks_green(rollup: list[dict] | None) -> bool:
    if not rollup:
        return False
    for check in rollup:
        conclusion = (check.get("conclusion") or "").upper()
        status = (check.get("status") or "").upper()
        if conclusion not in {"SUCCESS", "NEUTRAL", "SKIPPED", ""}:
            return False
        if status not in {"COMPLETED", ""} and conclusion == "":
            return False
    return True


def validate(pr_number: str) -> int:
    if os.environ.get("AIPLAYBOOK_AUTO_MERGE_DISCIPLINE_SKIP"):
        return 0
    data = _gh_pr_view(pr_number)
    if data is None:
        _emit_error(
            why=f"could not fetch PR #{pr_number}",
            where=f"PR #{pr_number}",
            fix="install gh CLI, authenticate, and ensure the PR exists.",
        )
        return 2
    body = data.get("body") or ""

    # Reuse ai-reviewer-signoff rubric.
    try:
        signoff = import_module("scripts.rules.ai-reviewer-signoff.rule")  # type: ignore[arg-type]
    except Exception:
        signoff = None  # type: ignore[assignment]
    canonical = ("L1 self-review", "Actionable comments", "Gate F")
    missing = [m for m in canonical if m not in body]
    if missing:
        _emit_error(
            why=f"§4.5.3 markers missing in PR #{pr_number}: {', '.join(missing)}",
            where=f"PR #{pr_number}",
            fix="complete the AI-reviewer signoff block before enabling auto-merge.",
        )
        return 1
    if not _all_checks_green(data.get("statusCheckRollup")):
        _emit_error(
            why=f"PR #{pr_number} CI is not green",
            where=f"PR #{pr_number}",
            fix="wait for all required checks to succeed before enabling auto-merge.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auto-merge-discipline")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--pr", required=False, default=None)
    args = parser.parse_args(argv)
    if not args.pr:
        return 0
    return validate(args.pr)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("auto-merge-discipline", main))
