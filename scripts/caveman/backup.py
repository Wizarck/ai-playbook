"""Backup + restore for files mutated by caveman toggle transitions.

Every reversible mutation (AGENTS.md inject, .mcp.json wrap, etc.) MUST
go through ``make_backup`` before writing. Rollback paths use
``latest_backup`` and ``restore_backup``.

Layout
------
    <project>/.ai-playbook/backups/<area>/<source_basename>.<timestamp>.bak

The ``<area>`` namespace separates concerns (``agents``, ``mcp``, etc.) so a
single restore call only touches the relevant family of files.

Timestamp format: ``YYYY-MM-DDTHH-MM-SSZ`` (colons stripped — Windows
filenames cannot contain ``:``).
"""
from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


STATE_DIR_NAME = ".ai-playbook"
BACKUP_DIR_NAME = "backups"


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def backup_dir(project_root: Path, area: str) -> Path:
    return project_root / STATE_DIR_NAME / BACKUP_DIR_NAME / area


def make_backup(project_root: Path, area: str, source_file: Path) -> Path:
    """Copy ``source_file`` to ``backups/<area>/<name>.<ts>.bak``.

    Returns the absolute path of the backup just written.

    Raises ``FileNotFoundError`` if ``source_file`` does not exist — callers
    must check existence before mutating, never blindly back up nothing.
    """
    if not source_file.is_file():
        raise FileNotFoundError(f"source not found for backup: {source_file}")
    d = backup_dir(project_root, area)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{source_file.name}.{_ts()}.bak"
    shutil.copy2(source_file, target)
    return target


def list_backups(project_root: Path, area: str | None = None) -> list[Path]:
    """Return all backup files, optionally scoped to ``area``. Sorted oldest→newest."""
    base = project_root / STATE_DIR_NAME / BACKUP_DIR_NAME
    if not base.is_dir():
        return []
    if area is not None:
        d = base / area
        if not d.is_dir():
            return []
        return sorted(d.glob("*.bak"))
    return sorted(base.rglob("*.bak"))


def latest_backup(project_root: Path, area: str, source_basename: str) -> Path | None:
    d = backup_dir(project_root, area)
    if not d.is_dir():
        return None
    candidates = sorted(d.glob(f"{source_basename}.*.bak"))
    return candidates[-1] if candidates else None


def restore_backup(
    project_root: Path,
    area: str,
    source_file: Path,
    *,
    timestamp: str | None = None,
) -> Path:
    """Restore the latest (or a specific) backup over ``source_file``.

    If ``timestamp`` is provided, restores ``<area>/<name>.<timestamp>.bak``
    explicitly; otherwise picks the newest backup matching the basename.

    Returns the backup path that was copied from.
    """
    if timestamp is not None:
        d = backup_dir(project_root, area)
        backup = d / f"{source_file.name}.{timestamp}.bak"
    else:
        b = latest_backup(project_root, area, source_file.name)
        if b is None:
            raise FileNotFoundError(
                f"no backup found for '{source_file.name}' in area '{area}'."
            )
        backup = b
    if not backup.is_file():
        raise FileNotFoundError(f"backup not found: {backup}")
    source_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, source_file)
    return backup


def prune_backups(project_root: Path, keep_per_file: int = 10) -> int:
    """Keep only the newest ``keep_per_file`` backups per (area, basename).

    Returns the count of removed files.
    """
    if keep_per_file < 1:
        raise ValueError("keep_per_file must be >= 1")
    base = project_root / STATE_DIR_NAME / BACKUP_DIR_NAME
    if not base.is_dir():
        return 0
    by_key: dict[tuple[str, str], list[Path]] = {}
    for area_dir in base.iterdir():
        if not area_dir.is_dir():
            continue
        for backup in area_dir.glob("*.bak"):
            # filename: <basename>.<timestamp>.bak — rsplit on '.' twice from the right.
            parts = backup.name.rsplit(".", 2)
            if len(parts) != 3 or parts[2] != "bak":
                continue
            basename = parts[0]
            by_key.setdefault((area_dir.name, basename), []).append(backup)

    removed = 0
    for files in by_key.values():
        files_sorted = sorted(files)
        if len(files_sorted) > keep_per_file:
            for f in files_sorted[:-keep_per_file]:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


__all__ = [
    "STATE_DIR_NAME",
    "BACKUP_DIR_NAME",
    "backup_dir",
    "make_backup",
    "list_backups",
    "latest_backup",
    "restore_backup",
    "prune_backups",
]
