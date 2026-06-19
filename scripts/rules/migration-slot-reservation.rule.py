"""L1 hardrule: migration-slot-reservation.

Paired with docs/rules/migration-slot-reservation.rule.md.

The full contract spans Alembic / Prisma / Flyway slot reservations,
gotcha-ID claims, and ADR-INDEX entries, all gated by a project-side
``docs/openspec-slice.md`` "Slot reservations" table. The playbook
cannot inspect that file (it lives in each consumer); this hardrule
ships the mechanical check that travels with every consumer:
**no two Alembic migration files in the same directory may claim the
same integer prefix**.

CLI:
    python scripts/rules/migration-slot-reservation.rule.py validate <dir>

Exit codes:
    0 — every checked directory has unique migration slots.
    1 — at least one slot collision detected.
    2 — schema break (path not readable).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

SLOT_RE = re.compile(r"^(\d{4,})_")


def _emit_error(why: str, where: str, fix: str) -> None:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(
        "   OVERRIDE: AIPLAYBOOK_MIGRATION_SLOT_RESERVATION_SKIP=1 (audited)",
        file=sys.stderr,
    )


def _collect_slots(directory: Path) -> dict[str, list[Path]]:
    slots: dict[str, list[Path]] = defaultdict(list)
    for child in sorted(directory.rglob("*.py")):
        m = SLOT_RE.match(child.stem)
        if m:
            slots[m.group(1)].append(child)
    return slots


def validate_dir(directory: Path) -> int:
    if not directory.is_dir():
        _emit_error(
            why=f"path is not a directory: {directory}",
            where=str(directory),
            fix="pass an existing directory of Alembic migrations.",
        )
        return 2
    slots = _collect_slots(directory)
    collisions = {slot: files for slot, files in slots.items() if len(files) > 1}
    if collisions:
        for slot, files in collisions.items():
            names = ", ".join(f.name for f in files)
            _emit_error(
                why=f"slot {slot} claimed by {len(files)} files: {names}",
                where=str(directory),
                fix="reserve disjoint slots in docs/openspec-slice.md; rename one migration.",
            )
        return 1
    return 0


def validate(paths: list[str]) -> int:
    rc = 0
    for raw in paths:
        rc = max(rc, validate_dir(Path(raw)))
    return rc


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("AIPLAYBOOK_MIGRATION_SLOT_RESERVATION_SKIP"):
        return 0
    parser = argparse.ArgumentParser(prog="migration-slot-reservation")
    parser.add_argument("subcommand", choices=["validate"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not args.paths:
        return 0
    return validate(args.paths)


if __name__ == "__main__":
    # File-path invocation from a consumer root: put the playbook root on
    # sys.path so `scripts.*` resolves without PYTHONPATH/`-m`.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from scripts.rules._telemetry import cli_emit
    raise SystemExit(cli_emit("migration-slot-reservation", main))
