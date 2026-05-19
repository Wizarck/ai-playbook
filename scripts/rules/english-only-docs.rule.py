"""L1 hardrule: english-only-docs (paired with docs/rules/english-only-docs.rule.md).

Thin wrapper around `scripts/check_doc_language.py`. Default target is
`docs/`; extra paths may be passed positionally to the underlying check.

CLI:
    python scripts/rules/english-only-docs.rule.py validate [paths...]

Exit codes:
    0 — all clean (English-dominant prose).
    1 — non-English content detected (violation).
    2 — schema break / fatal (checker missing).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_doc_language.py"


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_DOC_LANG_SKIP"):
        return 0
    if not CHECKER.is_file():
        print(f"error: check_doc_language.py missing at {CHECKER}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(CHECKER), *paths]
    rc = subprocess.call(cmd)
    return 1 if rc != 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="english-only-docs")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*", default=["docs"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate(args.paths)
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("english-only-docs", main))
