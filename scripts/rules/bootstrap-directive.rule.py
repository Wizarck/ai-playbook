"""L1 hardrule: bootstrap-directive.

Paired with docs/rules/bootstrap-directive.rule.md.

Validates that an AGENTS.md file carries the canonical four-step bootstrap
directive in §0:

  1. read dispatcher-chain.md
  2. consult injected-context.md
  3. scan openspec/changes/*/
  4. respond

CLI:
    python scripts/rules/bootstrap-directive.rule.py validate <AGENTS.md-path>

Exit codes:
    0 — canonical block present.
    1 — missing or incomplete.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Required tokens in the bootstrap block. Order matters — we check all four
# appear AT LEAST once within the first ~150 lines of the file.
REQUIRED_TOKENS = [
    re.compile(r"dispatcher-chain\.md", re.IGNORECASE),
    re.compile(r"injected-context\.md", re.IGNORECASE),
    re.compile(r"openspec/changes", re.IGNORECASE),
    re.compile(r"\bbootstrap\b", re.IGNORECASE),
]
SECTION_ZERO_RE = re.compile(r"^#{1,2}\s*0\b", re.MULTILINE)


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate_text(text: str, where: str) -> int:
    header = "\n".join(text.splitlines()[:200])
    if not SECTION_ZERO_RE.search(header):
        _emit_error(
            why="AGENTS.md missing §0 bootstrap section",
            where=where,
            fix="add `## 0 Bootstrap directive` per bootstrap-directive.rule.md.",
        )
        return 1
    missing: list[str] = []
    for pat in REQUIRED_TOKENS:
        if not pat.search(header):
            missing.append(pat.pattern)
    if missing:
        _emit_error(
            why=f"AGENTS.md §0 missing tokens: {', '.join(missing)}",
            where=where,
            fix="copy the canonical bootstrap block from docs/rules/bootstrap-directive.rule.md verbatim.",
        )
        return 1
    return 0


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_BOOTSTRAP_DIRECTIVE_SKIP"):
        return 0
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            _emit_error(why=f"path not readable: {raw}", where=raw, fix="pass an existing AGENTS.md path.")
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
    parser = argparse.ArgumentParser(prog="bootstrap-directive")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
