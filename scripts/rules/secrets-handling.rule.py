"""L1 hardrule: secrets-handling (paired with docs/rules/secrets-handling.rule.md).

Thin wrapper around `scripts/secrets_scan.py`. Per the rule contract,
this gate declares `OVERRIDE: none` — break-glass is refused.

CLI:
    python scripts/rules/secrets-handling.rule.py validate

Exit codes:
    0 — no secrets detected in staged content.
    1 — likely secret hit (violation).
    2 — schema break / fatal (scanner missing).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCANNER = REPO_ROOT / "scripts" / "secrets_scan.py"


def validate() -> int:
    if not SCANNER.is_file():
        print(f"error: secrets_scan.py missing at {SCANNER}", file=sys.stderr)
        return 2
    rc = subprocess.call([sys.executable, str(SCANNER)])
    return 1 if rc != 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secrets-handling")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("secrets-handling", main))
