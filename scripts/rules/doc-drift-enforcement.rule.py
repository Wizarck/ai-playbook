"""L1 hardrule: doc-drift-enforcement.

Paired with docs/rules/doc-drift-enforcement.rule.md.

Thin wrapper around scripts/check_doc_drift.py that shares the rubric with
the L3 workflow `.github/workflows/doc-drift-enforcement.rule.yml`.

CLI:
    python scripts/rules/doc-drift-enforcement.rule.py validate [paths...]

Exit codes:
    0 — clean (no drift, or `[no-doc-impact]` PR title accepted).
    1 — drift detected.
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_doc_drift.py"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate(paths: list[str]) -> int:
    if os.environ.get("AIPLAYBOOK_DOC_DRIFT_SKIP"):
        return 0
    if not CHECKER.is_file():
        _emit_error(
            why=f"check_doc_drift.py missing at {CHECKER}",
            where=str(CHECKER),
            fix="restore scripts/check_doc_drift.py from main.",
        )
        return 2
    cmd = [sys.executable, str(CHECKER), *paths]
    try:
        rc = subprocess.call(cmd, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        _emit_error(
            why=f"check_doc_drift invocation failed: {exc}",
            where="doc-drift-enforcement",
            fix="run scripts/check_doc_drift.py manually to diagnose.",
        )
        return 2
    return 1 if rc != 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doc-drift-enforcement")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    return validate(args.paths)


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("doc-drift-enforcement", main))
