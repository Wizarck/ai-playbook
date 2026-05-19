"""L1 hardrule: error-message-standard.

Paired with docs/rules/error-message-standard.rule.md.

Validates that every `❌` line in a stream / file is followed within 5 lines
by `   FIX:` and `   OVERRIDE:` (the canonical 4-line shape).

CLI:
    python scripts/rules/error-message-standard.rule.py validate <stream-or-script>

Exit codes:
    0 — clean.
    1 — `❌` line missing the canonical FIX/OVERRIDE follow-up.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ERROR_RE = re.compile(r"^❌ .+ at .+$", re.MULTILINE)
FIX_RE = re.compile(r"^\s+FIX:\s*.+$", re.MULTILINE)
OVERRIDE_RE = re.compile(r"^\s+OVERRIDE:\s*.+$", re.MULTILINE)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate_text(text: str, where: str) -> int:
    for m in ERROR_RE.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        # Look at next 5 lines for FIX + OVERRIDE.
        after_start = m.end()
        next_window_end = after_start
        nl_seen = 0
        for i, ch in enumerate(text[after_start:], start=after_start):
            if ch == "\n":
                nl_seen += 1
                if nl_seen == 5:
                    next_window_end = i
                    break
        else:
            next_window_end = len(text)
        window = text[after_start:next_window_end]
        if not FIX_RE.search(window):
            _emit_error(
                why="`❌` error line missing `FIX:` follow-up within 5 lines",
                where=f"{where}:{line_no}",
                fix="follow each ❌ error with `   FIX:` + `   OVERRIDE:` per error-message-standard.rule.md.",
            )
            return 1
        if not OVERRIDE_RE.search(window):
            _emit_error(
                why="`❌` error line missing `OVERRIDE:` follow-up within 5 lines",
                where=f"{where}:{line_no}",
                fix="add `   OVERRIDE: none` or the canonical break-glass invocation.",
            )
            return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_ERROR_MESSAGE_STANDARD_SKIP"):
        return 0
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(why=f"path not readable: {raw}", where=raw, fix="pass an existing file.")
            return 2
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _emit_error(why=str(exc), where=raw, fix="check file permissions.")
            return 2
        rc = validate_text(text, raw)
        if rc:
            return rc
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="error-message-standard")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
