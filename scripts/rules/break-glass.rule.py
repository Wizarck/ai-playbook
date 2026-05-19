"""L1 hardrule: break-glass.

Paired with docs/rules/break-glass.rule.md.

Validates that a blocking playbook script either:
1. Imports the shared helper `scripts._break_glass` and registers
   `--force-with-reason` via `add_break_glass_flag`, OR
2. Declares an explicit `OVERRIDE: none` marker in the script docstring /
   comments (the rule allows refusing override entirely for scripts
   protecting credentials / safety invariants / data loss).

Scripts that do neither are non-compliant: they may block without
offering the audited escape hatch, breaking the uniform contract.

CLI:
    python scripts/rules/break-glass.rule.py validate <script-path>

Exit codes:
    0 — script complies (uses helper, OR declares OVERRIDE: none, OR is
        non-blocking — heuristic: contains no `sys.exit(1)` / `exit 1`).
    1 — blocking script missing both signals.
    2 — schema break (file unreadable).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HELPER_IMPORT_RE = re.compile(
    r"(from\s+scripts\._break_glass\s+import|import\s+scripts\._break_glass)"
)
ADD_FLAG_RE = re.compile(r"\badd_break_glass_flag\b")
OVERRIDE_NONE_RE = re.compile(r"OVERRIDE[:\s]+none\b", re.IGNORECASE)
BLOCKING_RE = re.compile(r"(sys\.exit\([^0]\)|exit\s*1\b|SystemExit\([^0]\))")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: AIPLAYBOOK_BREAK_GLASS_SKIP=1 (audited)", file=sys.stderr)


def validate_file(p: Path) -> int:
    if not p.is_file():
        _emit_error(why=f"path not readable: {p}", where=str(p), fix="pass an existing file.")
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _emit_error(why=str(exc), where=str(p), fix="check file permissions.")
        return 2
    if not BLOCKING_RE.search(text):
        return 0  # non-blocking script — out of scope.
    if HELPER_IMPORT_RE.search(text) and ADD_FLAG_RE.search(text):
        return 0
    if OVERRIDE_NONE_RE.search(text):
        return 0
    _emit_error(
        why="blocking script missing break-glass surface",
        where=str(p),
        fix=(
            "either import scripts._break_glass and call add_break_glass_flag(...) "
            "OR declare OVERRIDE: none in the docstring/comments."
        ),
    )
    return 1


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
    if os.environ.get("AIPLAYBOOK_BREAK_GLASS_SKIP"):
        return 0
    parser = argparse.ArgumentParser(prog="break-glass")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
