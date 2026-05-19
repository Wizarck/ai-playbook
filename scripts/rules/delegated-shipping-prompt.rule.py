"""L1 hardrule: delegated-shipping-prompt.

Paired with docs/rules/delegated-shipping-prompt.rule.md.

Validates that a delegated-shipping spawn envelope embeds the §4.5.3
canonical signoff block (three markers + `release-management §4.5` reference).

CLI:
    python scripts/rules/delegated-shipping-prompt.rule.py validate --task <envelope-path>

Exit codes:
    0 — envelope contains the required canonical block.
    1 — envelope missing markers or §4.5 reference.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

CANONICAL_MARKERS = ("L1 self-review", "Actionable comments", "Gate F")
REFERENCE_LITERAL = "release-management §4.5"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate(envelope_file: Path) -> int:
    if os.environ.get("AIPLAYBOOK_DELEGATED_SHIPPING_PROMPT_SKIP"):
        return 0
    if not envelope_file.is_file():
        _emit_error(
            why=f"envelope file not readable: {envelope_file}",
            where=str(envelope_file),
            fix="pass an existing spawn-envelope file path.",
        )
        return 2
    try:
        body = envelope_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(envelope_file), fix="check file permissions.")
        return 2

    missing = [m for m in CANONICAL_MARKERS if m not in body]
    if missing:
        _emit_error(
            why=f"spawn envelope missing §4.5.3 markers: {', '.join(missing)}",
            where=str(envelope_file),
            fix="embed the three canonical markers verbatim in the spawn envelope.",
        )
        return 1
    if REFERENCE_LITERAL not in body:
        _emit_error(
            why=f"spawn envelope missing `{REFERENCE_LITERAL}` reference",
            where=str(envelope_file),
            fix=f"add the literal `{REFERENCE_LITERAL}` reference to the envelope.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="delegated-shipping-prompt")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("--task", type=Path, required=False, default=None)
    args = parser.parse_args(argv)
    if not args.task:
        return 0
    return validate(args.task)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("delegated-shipping-prompt", main))
