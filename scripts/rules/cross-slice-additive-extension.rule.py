"""L1 hardrule: cross-slice-additive-extension.

Paired with docs/rules/cross-slice-additive-extension.rule.md.

Static analysis on an Alembic migration file: refuses ``ALTER TABLE … ADD
COLUMN … NOT NULL`` *without* a `DEFAULT` clause (the most common
additive-migration footgun — Shape B requires a sentinel default).

The rule's full contract also covers slot reservations and read-side
discipline; those surfaces remain advisory because they depend on
project-specific slicing artefacts. This hardrule scopes to the
mechanical NOT-NULL-without-default check, which is the failure mode the
hook can detect with confidence.

CLI:
    python scripts/rules/cross-slice-additive-extension.rule.py validate <path-or-dir>

Exit codes:
    0 — every checked file is OK (or out of scope).
    1 — at least one NOT NULL ADD COLUMN without a DEFAULT clause.
    2 — schema break (file not readable).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+[\w.\"`]+\s+ADD\s+COLUMN\s+[\w\"`]+\s+[\w()\[\]<>\s,]+?NOT\s+NULL(?!\s+DEFAULT)",
    re.IGNORECASE,
)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(
        "   OVERRIDE: AIPLAYBOOK_CROSS_SLICE_ADDITIVE_EXTENSION_SKIP=1 (audited)",
        file=sys.stderr,
    )


def validate_file(p: Path) -> int:
    if not p.is_file():
        _emit_error(why=f"path not readable: {p}", where=str(p), fix="pass an existing file.")
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(p), fix="check file permissions.")
        return 2
    matches = list(ADD_COLUMN_RE.finditer(text))
    if matches:
        for m in matches:
            _emit_error(
                why=f"ADD COLUMN ... NOT NULL without DEFAULT: {m.group(0)[:120]}",
                where=str(p),
                fix="add a safe sentinel DEFAULT (Shape B) or drop NOT NULL (Shape A).",
            )
        return 1
    return 0


def validate(paths: list[str]) -> int:
    rc = 0
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*.py")):
                rc = max(rc, validate_file(child))
        else:
            rc = max(rc, validate_file(p))
    return rc


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("AIPLAYBOOK_CROSS_SLICE_ADDITIVE_EXTENSION_SKIP"):
        return 0
    parser = argparse.ArgumentParser(prog="cross-slice-additive-extension")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("cross-slice-additive-extension", main))
