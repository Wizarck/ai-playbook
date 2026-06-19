"""L1 hardrule: pr-tracker-reference.

Paired with docs/rules/pr-tracker-reference.rule.md.

Validates a PR title + body for at least one tracker reference:
  - GitHub: `Closes #N` | `Fixes #N` | `Resolves #N` in body (case-insensitive).
  - Jira:   `PROJ-N:` prefix in the title (uppercase PROJ + digits).

CLI:
    python scripts/rules/pr-tracker-reference.rule.py validate --pr-title <title> --pr-body-file <path>
    python scripts/rules/pr-tracker-reference.rule.py validate --pr <number>

Exit codes:
    0 — at least one tracker reference found.
    1 — none found.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

GITHUB_RE = re.compile(r"\b(?:closes|fixes|resolves)\s+#\d+\b", re.IGNORECASE)
JIRA_TITLE_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+\b")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _gh_pr(number: str) -> tuple[str, str] | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", number, "--json", "title,body"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout) or {}
    except json.JSONDecodeError:
        return None
    return str(data.get("title", "")), str(data.get("body", ""))


def validate_pair(title: str, body: str, where: str) -> int:
    if GITHUB_RE.search(body):
        return 0
    if JIRA_TITLE_RE.search(title):
        return 0
    _emit_error(
        why="PR missing tracker reference",
        where=where,
        fix="add `Closes #N`/`Fixes #N`/`Resolves #N` in PR body OR a `PROJ-N:` prefix to the title.",
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pr-tracker-reference")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--pr-title", default=None)
    parser.add_argument("--pr-body-file", type=Path, default=None)
    parser.add_argument("--pr", default=None)
    args = parser.parse_args(argv)
    if os.environ.get("AIPLAYBOOK_PR_TRACKER_REFERENCE_SKIP"):
        return 0
    if args.pr:
        pair = _gh_pr(args.pr)
        if pair is None:
            _emit_error(why=f"could not fetch PR #{args.pr}", where=f"PR #{args.pr}", fix="install gh CLI and authenticate.")
            return 2
        title, body = pair
        return validate_pair(title, body, f"PR #{args.pr}")
    if args.pr_title is not None and args.pr_body_file is not None:
        if not args.pr_body_file.is_file():
            _emit_error(why=f"body file not readable: {args.pr_body_file}", where=str(args.pr_body_file), fix="pass an existing file.")
            return 2
        body = args.pr_body_file.read_text(encoding="utf-8", errors="replace")
        return validate_pair(args.pr_title, body, str(args.pr_body_file))
    return 0


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("pr-tracker-reference", main))
