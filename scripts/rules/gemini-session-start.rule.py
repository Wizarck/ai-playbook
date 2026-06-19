"""L1 hardrule: gemini-session-start (paired with docs/rules/gemini-session-start.rule.md).

Verifies that the canonical `scripts/gemini_start.py` wrapper exists and
that the always-loaded rules manifest is reachable. The actual injection
happens inside `gemini_start.py`; this hardrule is the pre-flight check.

CLI:
    python scripts/rules/gemini-session-start.rule.py validate

Exit codes:
    0 — wrapper present and manifest reachable.
    1 — wrapper missing or unreachable (violation).
    2 — schema break / fatal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "gemini_start.py"
ALWAYS_LOADED = REPO_ROOT / "docs" / "rules"


def validate() -> int:
    if not WRAPPER.is_file():
        print(f"error: gemini wrapper missing at {WRAPPER}", file=sys.stderr)
        return 1
    if not ALWAYS_LOADED.is_dir():
        print(f"error: always-loaded rules dir missing at {ALWAYS_LOADED}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gemini-session-start")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("gemini-session-start", main))
