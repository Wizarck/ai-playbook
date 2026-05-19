"""L1 hardrule: apply-skill-enforcement.

Paired with docs/rules/apply-skill-enforcement.rule.md.

Thin wrapper around scripts/openspec_apply_marker.py to confirm an
apply-phase session marker exists for the change whose write_paths cover
the target file.

CLI:
    python scripts/rules/apply-skill-enforcement.rule.py validate <change-id>

Exit codes:
    0 — apply marker present for the change-id.
    1 — apply marker missing (block).
    2 — schema break.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MARKER_SCRIPT = REPO_ROOT / "scripts" / "openspec_apply_marker.py"


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print("   OVERRIDE: none", file=sys.stderr)


def validate(change_id: str) -> int:
    if os.environ.get("AIPLAYBOOK_APPLY_SKILL_SKIP"):
        return 0
    if not MARKER_SCRIPT.is_file():
        _emit_error(
            why=f"openspec_apply_marker.py missing at {MARKER_SCRIPT}",
            where=str(MARKER_SCRIPT),
            fix="restore scripts/openspec_apply_marker.py from main.",
        )
        return 2
    try:
        result = subprocess.run(
            [sys.executable, str(MARKER_SCRIPT), "session_started", "--change-id", change_id],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        _emit_error(
            why=f"apply-marker check failed: {exc}",
            where="apply-skill-enforcement",
            fix="run scripts/openspec_apply_marker.py session_started manually.",
        )
        return 2
    if result.returncode == 0:
        return 0
    _emit_error(
        why=f"no apply session marker for change `{change_id}`",
        where="apply-skill-enforcement",
        fix=(
            "invoke the openspec-apply-change skill OR run "
            f"`python -m scripts.openspec_apply_marker start --change-id {change_id}` "
            "before any Edit/Write on a declared write_path."
        ),
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply-skill-enforcement")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("change_id", nargs="?", default="")
    args = parser.parse_args(argv)
    if not args.change_id:
        # Empty change_id is a no-op — telemetry-friendly when running on stdin events.
        return 0
    return validate(args.change_id)


if __name__ == "__main__":
    raise SystemExit(main())
