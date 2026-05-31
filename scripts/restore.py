"""``restore`` — copy a backed-up file back onto its source (the Files-tab Restore action).

``apply_config`` records every overwrite in the backup index
(``.ai-playbook-state/backups/index.json``); the config-UI Files tab surfaces
those records and its **Restore** button copies an invocation of this CLI. The
heavy lifting lives in :mod:`scripts._backup_helper` — this is the thin,
human-gated, telemetry-instrumented entrypoint around it.

Restoring OVERWRITES the file's current content, so it is gated: without
``--yes`` (or with ``--dry-run``) the command only previews what it would do.

CLI::

    # one specific backup (what the UI copies — preview, then re-run with --yes)
    python -m scripts.restore <rel_path> --from <backup_rel_path> [--yes]
    # the BASE (pre-playbook) snapshot for one file
    python -m scripts.restore <rel_path> --base [--yes]
    # every BASE snapshot (full pre-playbook recovery)
    python -m scripts.restore --all-base [--yes]

Common flags: ``[--target PATH] [--dry-run] [--json]``.

Exit codes::
    0  preview (no --yes) OR restore succeeded
    1  nothing to restore for the given selector / record not found
    2  environment error (bad target) OR a backup file was missing on disk
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts._backup_helper import (
    BackupRecord,
    base_record_for,
    latest_backup_for,
    read_index,
    restore_backup,
    restore_base,
)


@dataclass
class RestoreResult:
    ok: bool
    rc: int
    detail: str
    restored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    previewed: bool = False


def _find_by_backup_rel(consumer_root: Path, backup_rel: str) -> BackupRecord | None:
    norm = backup_rel.replace("\\", "/")
    for r in read_index(consumer_root):
        if r.backup_rel_path == norm:
            return r
    return None


def restore(
    consumer_root: Path,
    *,
    rel_path: str | None = None,
    from_backup: str | None = None,
    base: bool = False,
    all_base: bool = False,
    consent: bool = False,
    dry_run: bool = False,
) -> RestoreResult:
    """Resolve the selector to one or more backup records and (if consented) restore them."""
    consumer_root = consumer_root.resolve()
    preview = dry_run or not consent

    # --- resolve the records to restore ---------------------------------
    records: list[BackupRecord] = []
    if all_base:
        # restore_base with no rel_path targets every file with a base record;
        # in preview mode we only enumerate, so collect the records directly.
        records = [r for r in read_index(consumer_root)
                   if r.session_id == "base"]
        # de-dupe to the earliest per file (mirrors restore_base semantics)
        earliest: dict[str, BackupRecord] = {}
        for r in sorted(records, key=lambda x: x.timestamp):
            earliest.setdefault(r.rel_path, r)
        records = list(earliest.values())
        if not records:
            return RestoreResult(False, 1, "no BASE snapshots recorded — nothing to restore")
    elif rel_path is None:
        return RestoreResult(False, 1, "specify a rel_path (or --all-base)")
    elif from_backup:
        rec = _find_by_backup_rel(consumer_root, from_backup)
        if rec is None:
            return RestoreResult(False, 1, f"no backup record with backup_rel_path={from_backup!r}")
        records = [rec]
    elif base:
        rec = base_record_for(consumer_root, rel_path)
        if rec is None:
            return RestoreResult(False, 1, f"no BASE snapshot recorded for {rel_path!r}")
        records = [rec]
    else:
        rec = latest_backup_for(consumer_root, rel_path)
        if rec is None:
            return RestoreResult(False, 1, f"no backup recorded for {rel_path!r}")
        records = [rec]

    targets = [f"{r.rel_path} ← {r.backup_rel_path} ({r.timestamp})" for r in records]

    # --- preview (no --yes) ---------------------------------------------
    if preview:
        return RestoreResult(
            ok=True, rc=0, previewed=True,
            detail=(f"Would restore {len(records)} file(s):\n  " + "\n  ".join(targets)
                    + "\nRe-run with --yes to apply (this overwrites current content)."),
            restored=[r.rel_path for r in records],
        )

    # --- apply ----------------------------------------------------------
    restored: list[str] = []
    warnings: list[str] = []
    for rec in records:
        try:
            dest = restore_backup(consumer_root, rec)
            restored.append(str(dest.relative_to(consumer_root)).replace("\\", "/"))
        except FileNotFoundError as exc:
            warnings.append(str(exc))
    if restored and not warnings:
        return RestoreResult(True, 0, f"restored {len(restored)} file(s)", restored, warnings)
    if restored and warnings:
        return RestoreResult(True, 2, f"restored {len(restored)} file(s), {len(warnings)} missing backup(s)",
                             restored, warnings)
    return RestoreResult(False, 2, "no files restored — backup file(s) missing on disk",
                         restored, warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restore",
        description="Restore a backed-up consumer file (or every BASE snapshot) from the backup index.",
    )
    parser.add_argument("rel_path", nargs="?", default=None,
                        help="Path (relative to consumer root) of the file to restore.")
    parser.add_argument("--from", dest="from_backup", default=None, metavar="BACKUP_REL",
                        help="Restore this specific backup (its backup_rel_path from the index).")
    parser.add_argument("--base", action="store_true",
                        help="Restore the BASE (pre-playbook) snapshot for rel_path.")
    parser.add_argument("--all-base", action="store_true",
                        help="Restore every BASE snapshot (full pre-playbook recovery).")
    parser.add_argument("--target", type=Path, default=None, help="Consumer root (default: cwd).")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; write nothing.")
    parser.add_argument("--yes", action="store_true",
                        help="Consent to overwrite current content with the backup.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    args = parser.parse_args(argv)

    target = (args.target or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        print(f"❌ target {target} is not a directory", file=sys.stderr)
        return 2

    result = restore(
        target,
        rel_path=args.rel_path,
        from_backup=args.from_backup,
        base=args.base,
        all_base=args.all_base,
        consent=args.yes,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps({
            "ok": result.ok, "rc": result.rc, "detail": result.detail,
            "restored": result.restored, "warnings": result.warnings,
            "previewed": result.previewed,
        }, ensure_ascii=False, indent=2))
    else:
        print(result.detail)
        for w in result.warnings:
            print(f"⚠️  {w}", file=sys.stderr)
    return result.rc


if __name__ == "__main__":
    from scripts.rules._telemetry import script_emit

    sys.exit(script_emit("restore", main))
