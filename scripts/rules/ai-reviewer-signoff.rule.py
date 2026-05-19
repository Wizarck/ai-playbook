"""L1 hardrule: ai-reviewer-signoff.

Paired with docs/rules/ai-reviewer-signoff.rule.md.

Validates a PR body for the three §4.5.3 canonical markers:
  - `L1 self-review`
  - `Actionable comments`
  - `Gate F`

CLI:
    python scripts/rules/ai-reviewer-signoff.rule.py validate --pr-body <file>
    python scripts/rules/ai-reviewer-signoff.rule.py validate --pr <number>

Exit codes:
    0 — all three markers present.
    1 — at least one marker missing.
    2 — schema break (file unreadable, gh not installed).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CANONICAL_MARKERS = ("L1 self-review", "Actionable comments", "Gate F")
HEADING_RE = re.compile(r"^#+\s+4\.5\b", re.MULTILINE)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _gh_pr_body(number: str) -> str | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", number, "--json", "body", "-q", ".body"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def validate_body(body: str, where: str) -> int:
    missing = [m for m in CANONICAL_MARKERS if m not in body]
    if missing:
        _emit_error(
            why=f"PR body missing §4.5.3 markers: {', '.join(missing)}",
            where=where,
            fix="populate the AI-reviewer signoff block with all three canonical markers (substring-match).",
        )
        return 1
    if not HEADING_RE.search(body):
        _emit_error(
            why="PR body missing §4.5 heading",
            where=where,
            fix="add `## 4.5 AI-reviewer signoff` per release-management contract.",
        )
        return 1
    return 0


def validate(body_file: Path | None, pr_number: str | None) -> int:
    if os.environ.get("AIPLAYBOOK_AI_REVIEWER_SIGNOFF_SKIP"):
        return 0
    body: str | None = None
    where = ""
    if body_file is not None:
        if not body_file.is_file():
            _emit_error(why=f"file not readable: {body_file}", where=str(body_file), fix="pass an existing path.")
            return 2
        body = body_file.read_text(encoding="utf-8", errors="replace")
        where = str(body_file)
    elif pr_number:
        body = _gh_pr_body(pr_number)
        where = f"PR #{pr_number}"
        if body is None:
            _emit_error(why=f"could not fetch PR #{pr_number} body", where=where, fix="install gh CLI and authenticate.")
            return 2
    else:
        return 0  # no input — no-op for telemetry.
    return validate_body(body, where)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-reviewer-signoff")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--pr-body", type=Path, default=None)
    parser.add_argument("--pr", default=None)
    args = parser.parse_args(argv)
    return validate(args.pr_body, args.pr)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("ai-reviewer-signoff", main))
