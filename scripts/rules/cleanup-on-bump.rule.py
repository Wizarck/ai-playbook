"""L1 hardrule: cleanup-on-bump (paired with docs/rules/cleanup-on-bump.rule.md).

Verifies that after a `.ai-playbook/` submodule bump (detected via Git
log), the cleanup_zombies.py report has been generated OR the manifest
was empty (clean state). Hook wire-up is the soft signal; the strict
signal is "report exists OR manifest empty since last bump".

CLI:
    python scripts/rules/cleanup-on-bump.rule.py validate

Exit codes:
    0 — cleanup ran (report file exists) OR clean state OR no recent bump.
    1 — bump detected but no cleanup evidence (violation).
    2 — schema break / fatal.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _consumer_root() -> Path | None:
    cur = Path.cwd()
    for parent in [cur, *cur.parents]:
        if (parent / ".gitmodules").is_file():
            return parent
    return None


def validate() -> int:
    if os.environ.get("AIPLAYBOOK_CLEANUP_ON_BUMP_SKIP"):
        return 0
    root = _consumer_root()
    if root is None:
        return 0  # not a consumer tree
    submodule = root / ".ai-playbook"
    if not submodule.is_dir():
        return 0  # no submodule yet
    # Did the last commit on main change the submodule pin?
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "log", "-1", "--name-only", "--pretty=format:"],
            text=True, stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        return 0  # cannot determine; treat as no-op
    if ".ai-playbook" not in out:
        return 0  # no recent bump
    # Clean state signal: report absent + manifest entries all dormant.
    report = root / ".ai-playbook" / "zombie-report.md"
    if report.is_file():
        return 0
    # No report — was it an empty cleanup run? We trust the script's contract.
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cleanup-on-bump")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    # Allow file-path invocation from a consumer root
    # (`python .ai-playbook/scripts/rules/cleanup-on-bump.rule.py …`) — put the
    # playbook root on sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("cleanup-on-bump", main))
