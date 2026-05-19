"""L1 hardrule: alembic-migration-naming.

Paired with docs/rules/alembic-migration-naming.rule.md.

Validates that every Alembic migration file uses the verbose
``revision = "<NNNN>_<topic>"`` literal matching the basename
``<NNNN>_<topic>.py``. The bare-integer form ``revision = "0010"`` is
rejected.

CLI:
    python scripts/rules/alembic-migration-naming.rule.py validate <path-or-dir>

Exit codes:
    0 — every checked file conforms.
    1 — at least one bare-integer revision or filename/revision mismatch.
    2 — schema break (file not readable).
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

REVISION_BARE_RE = re.compile(r"^\d{4}$")
FILENAME_PREFIX_RE = re.compile(r"^(\d{4,})_(.+)$")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_ALEMBIC_MIGRATION_NAMING_SKIP=1 (audited)", file=sys.stderr)


def _extract_revision(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "revision":
                    val = node.value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        return val.value
    return None


def validate_file(p: Path) -> int:
    if not p.is_file():
        _emit_error(why=f"path not readable: {p}", where=str(p), fix="pass an existing file.")
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(p), fix="check file permissions.")
        return 2
    revision = _extract_revision(text)
    if revision is None:
        return 0  # not an Alembic migration; skip.
    basename = p.stem
    if REVISION_BARE_RE.match(revision):
        _emit_error(
            why=f"bare-integer revision '{revision}' in {p.name}",
            where=str(p),
            fix='use the verbose form revision = "<NNNN>_<topic>" matching the filename.',
        )
        return 1
    m = FILENAME_PREFIX_RE.match(basename)
    if not m:
        return 0  # filename not in NNNN_topic shape — likely not an Alembic file
    if revision != basename:
        _emit_error(
            why=f"revision/filename drift: revision='{revision}' vs file='{basename}'",
            where=str(p),
            fix="set the revision literal byte-equal to the filename stem.",
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
    if os.environ.get("AIPLAYBOOK_ALEMBIC_MIGRATION_NAMING_SKIP"):
        return 0
    parser = argparse.ArgumentParser(prog="alembic-migration-naming")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
