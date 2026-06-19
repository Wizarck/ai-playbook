"""L1 hardrule: subagent-envelope-schema.

Paired with docs/rules/subagent-envelope-schema.rule.md.

Validates a spawn or return envelope against `schemas/schema-agent-contract.json`.
Direction inferred from shape — `parent_to_child` envelopes carry `slug` +
`isolation` + `success_criteria`; `child_to_parent` envelopes carry
`verdict` + `findings`.

CLI:
    python scripts/rules/subagent-envelope-schema.rule.py validate <envelope.json>

Exit codes:
    0 — envelope validates.
    1 — schema validation failed.
    2 — schema break (file unreadable, schema missing).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import jsonschema  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — jsonschema is part of dev deps.
    jsonschema = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "schema-agent-contract.json"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def _load_schema() -> dict | None:
    if not SCHEMA_PATH.is_file():
        return None
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _select_subschema(schema: dict, envelope: dict) -> dict | None:
    # Schemas can be flat or contain a `$defs` block keyed by direction.
    defs = schema.get("$defs") or schema.get("definitions") or {}
    if isinstance(defs, dict):
        if "findings" in envelope or "verdict" in envelope:
            sub = defs.get("child_to_parent") or defs.get("ChildToParent")
        else:
            sub = defs.get("parent_to_child") or defs.get("ParentToChild")
        if isinstance(sub, dict):
            return sub
    return schema


def validate(envelope_path: Path) -> int:
    if os.environ.get("AIPLAYBOOK_SUBAGENT_ENVELOPE_SCHEMA_SKIP"):
        return 0
    if not envelope_path.is_file():
        _emit_error(
            why=f"envelope not readable: {envelope_path}",
            where=str(envelope_path),
            fix="pass an existing JSON envelope file.",
        )
        return 2
    try:
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _emit_error(why=f"envelope JSON unreadable: {exc}", where=str(envelope_path), fix="ensure the envelope is valid JSON.")
        return 2
    schema = _load_schema()
    if schema is None:
        _emit_error(
            why=f"schema missing at {SCHEMA_PATH}",
            where=str(SCHEMA_PATH),
            fix="restore schemas/schema-agent-contract.json from main.",
        )
        return 2
    if jsonschema is None:
        _emit_error(
            why="jsonschema package not installed",
            where="subagent-envelope-schema",
            fix="`pip install jsonschema` (already in pyproject dev deps).",
        )
        return 2
    sub = _select_subschema(schema, envelope) or schema
    try:
        jsonschema.validate(envelope, sub)
    except jsonschema.ValidationError as exc:
        _emit_error(
            why=f"envelope failed schema validation: {exc.message}",
            where=str(envelope_path),
            fix="align the envelope shape to schemas/schema-agent-contract.json.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="subagent-envelope-schema")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("path", type=Path, nargs="?")
    args = parser.parse_args(argv)
    if not args.path:
        return 0
    return validate(args.path)


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("subagent-envelope-schema", main))
