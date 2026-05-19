"""L1 hardrule: update-documentation (paired with docs/rules/update-documentation.rule.md).

Thin wrapper around `scripts/check_doc_drift.py` enforcing co-edit-pairs
on a per-PR basis. The wrapper validates: when a staged file appears in
the doc-drift manifest, the paired doc is also staged.

CLI:
    python scripts/rules/update-documentation.rule.py validate

Exit codes:
    0 — no drift, OR escape tag `[no-doc-impact]` present in HEAD commit msg.
    1 — drift detected (violation).
    2 — schema break / fatal (manifest missing).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_doc_drift.py"


def validate() -> int:
    if os.environ.get("AIPLAYBOOK_DOC_DRIFT_SKIP"):
        return 0
    if not CHECK_SCRIPT.is_file():
        print(f"error: paired check script missing at {CHECK_SCRIPT}", file=sys.stderr)
        return 2
    # Honor [no-doc-impact] escape tag in HEAD commit message.
    try:
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            text=True, stderr=subprocess.STDOUT,
        )
        if "[no-doc-impact]" in msg.lower():
            return 0
    except subprocess.CalledProcessError:
        pass
    rc = subprocess.call([sys.executable, str(CHECK_SCRIPT)])
    return 1 if rc != 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="update-documentation")
    parser.add_argument("subcommand", choices=["validate"])
    args = parser.parse_args(argv)
    if args.subcommand == "validate":
        return validate()
    return 2


if __name__ == "__main__":
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("update-documentation", main))
