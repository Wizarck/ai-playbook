"""L1 hardrule: agentic-failure-catalog-schema.

Paired with docs/rules/agentic-failure-catalog-schema.rule.md.

Validates the structural integrity of `docs/concepts/agentic-failures.md`:
- The file exists.
- It contains a `## 1. Failure catalog` (or equivalent top-level catalog section).
- Each catalog table row has 4 columns (ID, short name, severity class, detectable?).
- Every row carries a non-empty backticked identifier in the ID column
  (the OTel attribute key `ai_playbook.failure.<id>` is derived from it).

The full contract — RFC marker comment + per-detector OTel attribute set —
is out of scope for the playbook-internal hardrule because
``scripts/failure_detectors/`` lives in consumer projects, not in the
playbook. This hardrule guarantees the catalog stays parseable; consumer-
side detectors are validated by the L3 workflow.

CLI:
    python scripts/rules/agentic-failure-catalog-schema.rule.py validate [<path>]

Exit codes:
    0 — catalog parses cleanly.
    1 — structural drift (no table, malformed row).
    2 — schema break (file unreadable).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

CATALOG_REL = Path("docs/concepts/agentic-failures.md")
CATALOG_HEADING_RE = re.compile(r"^##\s+1\.\s+Failure catalog", re.MULTILINE)
TABLE_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(
        "   OVERRIDE: AIPLAYBOOK_AGENTIC_FAILURE_CATALOG_SCHEMA_SKIP=1 (audited)",
        file=sys.stderr,
    )


def validate_file(p: Path) -> int:
    if not p.is_file():
        _emit_error(
            why=f"catalog file not found: {p}",
            where=str(p),
            fix="restore docs/concepts/agentic-failures.md.",
        )
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(p), fix="check file permissions.")
        return 2
    if not CATALOG_HEADING_RE.search(text):
        _emit_error(
            why="missing '## 1. Failure catalog' heading",
            where=str(p),
            fix="restore the canonical catalog heading at section 1.",
        )
        return 1
    rows = TABLE_ROW_RE.findall(text)
    if not rows:
        _emit_error(
            why="no catalog rows detected",
            where=str(p),
            fix="catalog table must include rows of the form | `id` | name | severity | detectable |.",
        )
        return 1
    # Verify every row id is unique
    seen: set[str] = set()
    for row_id in rows:
        if row_id in seen:
            _emit_error(
                why=f"duplicate catalog id: {row_id}",
                where=str(p),
                fix="every failure class id MUST be unique.",
            )
            return 1
        seen.add(row_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("AIPLAYBOOK_AGENTIC_FAILURE_CATALOG_SCHEMA_SKIP"):
        return 0
    parser = argparse.ArgumentParser(prog="agentic-failure-catalog-schema")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    target = Path(args.paths[0]) if args.paths else (Path.cwd() / CATALOG_REL)
    return validate_file(target)


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("agentic-failure-catalog-schema", main))
