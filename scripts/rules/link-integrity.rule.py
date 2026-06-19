"""L1 hardrule: link-integrity (paired with docs/rules/link-integrity.rule.md).

Thin wrapper around `scripts/check_link_integrity.py`. Default target is
`docs/`; extra paths may be passed positionally to the underlying check.

CLI:
    python scripts/rules/link-integrity.rule.py validate [paths...]

Exit codes:
    0 — all relative links resolve on disk.
    1 — at least one dead link (violation).
    2 — schema break / fatal (checker missing).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_link_integrity.py"


def validate(paths: list[str]) -> int:
    if not CHECKER.is_file():
        print(f"error: check_link_integrity.py missing at {CHECKER}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(CHECKER), *paths]
    rc = subprocess.call(cmd)
    return 1 if rc != 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="link-integrity")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*", default=["docs"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate(args.paths)
    return 2


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("link-integrity", main))
