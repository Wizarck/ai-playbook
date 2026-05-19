"""L1 hardrule: github-project-board-schema.

Paired with docs/rules/github-project-board-schema.rule.md.

Validates a GitHub Project board carries the canonical schema:
  - Status field with exactly five options in order:
      Todo, In Progress, In Review, Blocked, Done.
  - Text fields `Slice ID` and `Last Update` present.

CLI:
    python scripts/rules/github-project-board-schema.rule.py validate --project <id>

Exit codes:
    0 — schema matches.
    1 — schema drift detected.
    2 — schema break (no gh, project not reachable).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

CANONICAL_STATUS = ["Todo", "In Progress", "In Review", "Blocked", "Done"]
REQUIRED_TEXT_FIELDS = ("Slice ID", "Last Update")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _gh_field_list(project_id: str) -> list[dict] | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "project", "field-list", project_id, "--format", "json"],
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
        data = json.loads(result.stdout) or {}
    except json.JSONDecodeError:
        return None
    fields = data.get("fields")
    return fields if isinstance(fields, list) else None


def validate(project_id: str) -> int:
    if os.environ.get("AIPLAYBOOK_GITHUB_PROJECT_BOARD_SCHEMA_SKIP"):
        return 0
    fields = _gh_field_list(project_id)
    if fields is None:
        _emit_error(
            why=f"could not fetch field list for project `{project_id}`",
            where=f"project {project_id}",
            fix="install gh CLI, authenticate with `read:project` scope.",
        )
        return 2
    by_name = {str(f.get("name")): f for f in fields if isinstance(f, dict)}
    status = by_name.get("Status")
    if status is None:
        _emit_error(why="`Status` field missing", where=f"project {project_id}", fix="add a single-select `Status` field with the canonical five options.")
        return 1
    options = [str(o.get("name")) for o in (status.get("options") or []) if isinstance(o, dict)]
    if options != CANONICAL_STATUS:
        _emit_error(
            why=f"`Status` options drift: {options} != {CANONICAL_STATUS}",
            where=f"project {project_id}",
            fix="reorder/rename Status options to match the canonical five in order.",
        )
        return 1
    missing_text = [n for n in REQUIRED_TEXT_FIELDS if n not in by_name]
    if missing_text:
        _emit_error(
            why=f"required text fields missing: {missing_text}",
            where=f"project {project_id}",
            fix="add the text fields `Slice ID` and `Last Update` to the project.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="github-project-board-schema")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--project", required=False, default="")
    args = parser.parse_args(argv)
    if not args.project:
        return 0
    return validate(args.project)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("github-project-board-schema", main))
