"""Backup helper for consumer files mutated by ``apply_config`` / ``bootstrap --update``.

Two destination layouts (chosen per call, ultimately driven by a UI setting
persisted in the bundle):

* ``BackupLocation.NEXT_TO_FILE`` (default — matches the user-preferred
  ergonomics of "I can see my backup right next to the file"):
  writes ``<file>.<ts>.bak`` (or ``<file>.bak`` if ``with_timestamp=False``)
  in the same directory as the source.
* ``BackupLocation.CENTRAL``: writes
  ``<consumer>/.ai-playbook-state/backups/<rel-path>.<ts>.bak`` so the
  consumer's working tree stays uncluttered.

Discovery is centralised regardless of location: every backup write
appends a record to ``<consumer>/.ai-playbook-state/backups/index.json``
(``ai-playbook-backups/v1``). The UI reads this index to populate the
"Restore from .bak" dropdown without having to scan the filesystem.

Stdlib-only — imported from hot paths in ``apply_config.py``.

Convention notes
----------------
* This module is separate from ``scripts.caveman.backup``, which uses the
  legacy in-submodule ``.ai-playbook/backups/<area>/`` layout. The legacy
  helper is preserved for caveman toggle transitions; new file-managed
  apply flows go through THIS module instead. Eventually caveman's
  backup can be migrated to this layout (separate PR).
* Atomic file writes use the temp-file + ``os.replace`` pattern; we do
  NOT take filesystem locks. Concurrent apply invocations could corrupt
  the index, but the realistic single-user single-machine UI workflow
  makes that unlikely. A future iteration may add lockfile semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


STATE_DIR_NAME = ".ai-playbook-state"
BACKUP_DIR_NAME = "backups"
INDEX_FILENAME = "index.json"
INDEX_SCHEMA = "ai-playbook-backups/v1"
TIMESTAMP_FMT = "%Y-%m-%dT%H-%M-%SZ"  # colons stripped — Windows-safe


class BackupLocation(str, Enum):  # noqa: UP042 — StrEnum changes str()/format(); keep (str, Enum)
    """Where ``backup_once`` should write the ``.bak`` file."""

    NEXT_TO_FILE = "next"
    CENTRAL = "central"


@dataclass(frozen=True)
class BackupRecord:
    """One row of the backup index.

    All path fields are stored relative to ``consumer_root`` for portability
    across machine moves. ``restore_backup`` resolves them at read time.
    """

    rel_path: str          # source path relative to consumer root
    backup_rel_path: str   # backup file path relative to consumer root
    location: str          # "next" | "central"
    timestamp: str         # ISO-8601 with Windows-safe seconds
    sha256: str            # SHA-256 of the file content backed up
    source_size: int       # bytes of the source file at backup time
    session_id: str        # apply session id (audit grouping)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def state_dir(consumer_root: Path) -> Path:
    return consumer_root / STATE_DIR_NAME


def backups_dir(consumer_root: Path) -> Path:
    return state_dir(consumer_root) / BACKUP_DIR_NAME


def index_path(consumer_root: Path) -> Path:
    return backups_dir(consumer_root) / INDEX_FILENAME


def _now_ts() -> str:
    return datetime.now(UTC).strftime(TIMESTAMP_FMT)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via temp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _resolve_backup_target(
    consumer_root: Path,
    source_file: Path,
    *,
    location: BackupLocation,
    timestamp: str | None,
) -> Path:
    """Compute the absolute destination path for a backup write.

    Path semantics
    --------------
    * ``source_file`` is interpreted as already absolute or relative-to-cwd
      (caller's responsibility). It MUST be under ``consumer_root``.
    * Returned path is absolute.
    """
    source_abs = source_file.resolve()
    consumer_abs = consumer_root.resolve()
    try:
        rel = source_abs.relative_to(consumer_abs)
    except ValueError as exc:
        raise ValueError(
            f"source_file {source_abs} is not under consumer_root {consumer_abs}"
        ) from exc

    suffix = f".{timestamp}.bak" if timestamp else ".bak"
    if location is BackupLocation.NEXT_TO_FILE:
        return source_abs.parent / f"{source_abs.name}{suffix}"
    return backups_dir(consumer_abs) / rel.parent / f"{source_abs.name}{suffix}"


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------


def read_index(consumer_root: Path) -> list[BackupRecord]:
    """Return all index records (oldest first). Empty list if missing/corrupt."""
    p = index_path(consumer_root)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    if not str(data.get("schema", "")).startswith("ai-playbook-backups"):
        return []
    raw_records = data.get("records")
    if not isinstance(raw_records, list):
        return []
    out: list[BackupRecord] = []
    fields = {f for f in BackupRecord.__dataclass_fields__}
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        if not fields.issubset(item.keys()):
            continue
        try:
            out.append(BackupRecord(
                rel_path=str(item["rel_path"]),
                backup_rel_path=str(item["backup_rel_path"]),
                location=str(item["location"]),
                timestamp=str(item["timestamp"]),
                sha256=str(item["sha256"]),
                source_size=int(item["source_size"]),
                session_id=str(item["session_id"]),
            ))
        except (TypeError, ValueError):
            continue
    return out


def _write_index(consumer_root: Path, records: list[BackupRecord]) -> None:
    payload = {
        "schema": INDEX_SCHEMA,
        "records": [asdict(r) for r in records],
    }
    _atomic_write_text(
        index_path(consumer_root),
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def append_index(consumer_root: Path, record: BackupRecord) -> None:
    """Append one record to the index. Atomic at the file level."""
    records = read_index(consumer_root)
    records.append(record)
    _write_index(consumer_root, records)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def backup_once(
    consumer_root: Path,
    source_file: Path,
    *,
    location: BackupLocation = BackupLocation.NEXT_TO_FILE,
    with_timestamp: bool = True,
    session_id: str | None = None,
) -> BackupRecord | None:
    """Backup ``source_file`` before overwrite.

    Returns ``None`` if ``source_file`` does not exist (nothing to back up).
    Otherwise copies the file to the resolved destination, appends a record
    to the index, and returns the record.

    Idempotency
    -----------
    This function does NOT enforce idempotency by itself. Callers that want
    "only backup if no recent backup exists for this file" should consult
    ``latest_backup_for`` first. The default behaviour is "always create a
    new timestamped backup", matching the user's stated preference for
    versioned history.

    When ``with_timestamp=False``, the file is written as ``<file>.bak``
    (single slot, overwrites itself). That mode is provided for callers
    who explicitly want a single-slot rollback point (e.g., the one-shot
    migration).
    """
    consumer_root = consumer_root.resolve()
    source_file = source_file.resolve()
    if not source_file.is_file():
        return None

    ts = _now_ts() if with_timestamp else ""
    dest = _resolve_backup_target(
        consumer_root,
        source_file,
        location=location,
        timestamp=ts if with_timestamp else None,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, dest)

    rel = source_file.relative_to(consumer_root)
    backup_rel = dest.relative_to(consumer_root)
    record = BackupRecord(
        rel_path=str(rel).replace(os.sep, "/"),
        backup_rel_path=str(backup_rel).replace(os.sep, "/"),
        location=location.value,
        timestamp=ts or _now_ts(),
        sha256=_sha256(source_file),
        source_size=source_file.stat().st_size,
        session_id=session_id or f"adhoc-{_now_ts()}",
    )
    append_index(consumer_root, record)
    return record


def latest_backup_for(
    consumer_root: Path, rel_path: str
) -> BackupRecord | None:
    """Return the most recent backup record for ``rel_path``, or None."""
    rel_norm = rel_path.replace(os.sep, "/")
    matches = [r for r in read_index(consumer_root) if r.rel_path == rel_norm]
    return matches[-1] if matches else None


def list_backups_for(
    consumer_root: Path, rel_path: str
) -> list[BackupRecord]:
    """Return all backup records for ``rel_path`` sorted newest-first."""
    rel_norm = rel_path.replace(os.sep, "/")
    matches = [r for r in read_index(consumer_root) if r.rel_path == rel_norm]
    return list(reversed(matches))


def restore_backup(
    consumer_root: Path,
    record: BackupRecord,
    *,
    target: Path | None = None,
) -> Path:
    """Copy a backup back onto its source (or onto ``target`` if given).

    Returns the destination path that was written.

    Raises FileNotFoundError if the backup file referenced by the record
    is missing on disk.
    """
    consumer_root = consumer_root.resolve()
    backup_abs = (consumer_root / record.backup_rel_path).resolve()
    if not backup_abs.is_file():
        raise FileNotFoundError(f"backup file missing: {backup_abs}")
    dest = target.resolve() if target is not None else (consumer_root / record.rel_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_abs, dest)
    return dest


def restore_session(
    consumer_root: Path,
    session_id: str,
) -> tuple[list[Path], list[str]]:
    """Restore every file backed up under ``session_id`` to its pre-session content.

    For each source file with one or more backups in the session, the EARLIEST
    backup (the pre-session snapshot) is restored, so the file returns to the
    state it had before the session began. This is the set-level rollback unit
    for a failed transactional ``apply``.

    Returns ``(restored, warnings)`` where ``restored`` lists the destination
    paths rewritten and ``warnings`` lists records whose backup file was missing
    on disk (skipped rather than raised).

    NOTE: files that the session CREATED (no prior content, hence no backup
    record) are NOT affected here — the caller is responsible for removing
    newly-created files when rolling a batch back.
    """
    consumer_root = consumer_root.resolve()
    session_records = [
        r for r in read_index(consumer_root) if r.session_id == session_id
    ]
    # Earliest backup per source file = the pre-session snapshot.
    earliest: dict[str, BackupRecord] = {}
    for r in sorted(session_records, key=lambda rec: rec.timestamp):
        earliest.setdefault(r.rel_path, r)

    restored: list[Path] = []
    warnings: list[str] = []
    for record in earliest.values():
        try:
            restored.append(restore_backup(consumer_root, record))
        except FileNotFoundError as exc:
            warnings.append(str(exc))
    return restored, warnings


# ---------------------------------------------------------------------------
# BASE snapshot — the pre-playbook state, captured once, kept for uninstall
# ---------------------------------------------------------------------------

# Per D8: only the BASE (pre-playbook) snapshot is durably kept and explicitly
# tagged so an uninstall / recovery can return a file to the state it had before
# the playbook ever touched it. All other backups are ordinary versioned history.
BASE_SESSION_ID = "base"


def base_record_for(consumer_root: Path, rel_path: str) -> BackupRecord | None:
    """Return the BASE (earliest, pre-playbook) record for ``rel_path``, or None."""
    rel_norm = rel_path.replace(os.sep, "/")
    matches = [
        r for r in read_index(consumer_root)
        if r.session_id == BASE_SESSION_ID and r.rel_path == rel_norm
    ]
    matches.sort(key=lambda r: r.timestamp)
    return matches[0] if matches else None


def backup_base(consumer_root: Path, source_file: Path) -> BackupRecord | None:
    """Capture the pre-playbook content of ``source_file`` ONCE (tag ``base``).

    The BASE snapshot is the very first state the playbook saw; it is never
    overwritten. No-op (returns ``None``) when the file does not exist or a base
    record already exists for it. Stored CENTRAL so it survives next-to-file
    backup pruning and stays out of the working tree.
    """
    consumer_root = consumer_root.resolve()
    source_file = source_file.resolve()
    if not source_file.is_file():
        return None
    rel = str(source_file.relative_to(consumer_root)).replace(os.sep, "/")
    if base_record_for(consumer_root, rel) is not None:
        return None  # base already captured — keep the earliest forever
    return backup_once(
        consumer_root, source_file,
        location=BackupLocation.CENTRAL, with_timestamp=True,
        session_id=BASE_SESSION_ID,
    )


def restore_base(
    consumer_root: Path,
    rel_path: str | None = None,
) -> tuple[list[Path], list[str]]:
    """Restore BASE (pre-playbook) snapshots — one file if ``rel_path`` is given,
    else every file that has a base record. The uninstall recovery path.

    Returns ``(restored, warnings)`` mirroring ``restore_session``. The earliest
    base record per file is used (the true pre-playbook content).
    """
    consumer_root = consumer_root.resolve()
    base_records = [r for r in read_index(consumer_root) if r.session_id == BASE_SESSION_ID]
    if rel_path is not None:
        rel_norm = rel_path.replace(os.sep, "/")
        base_records = [r for r in base_records if r.rel_path == rel_norm]

    earliest: dict[str, BackupRecord] = {}
    for r in sorted(base_records, key=lambda rec: rec.timestamp):
        earliest.setdefault(r.rel_path, r)

    restored: list[Path] = []
    warnings: list[str] = []
    for record in earliest.values():
        try:
            restored.append(restore_backup(consumer_root, record))
        except FileNotFoundError as exc:
            warnings.append(str(exc))
    return restored, warnings


def prune_backups(
    consumer_root: Path,
    *,
    keep_per_file: int = 10,
) -> int:
    """Remove the oldest backups beyond ``keep_per_file`` per ``rel_path``.

    Returns the number of backup files removed from disk. The index is
    rewritten to match.
    """
    if keep_per_file < 1:
        raise ValueError("keep_per_file must be >= 1")
    consumer_root = consumer_root.resolve()
    records = read_index(consumer_root)
    # BASE snapshots are kept forever (the uninstall anchor) — never pruned.
    base_keep = [r for r in records if r.session_id == BASE_SESSION_ID]
    by_rel: dict[str, list[BackupRecord]] = {}
    for r in records:
        if r.session_id == BASE_SESSION_ID:
            continue
        by_rel.setdefault(r.rel_path, []).append(r)

    keep: list[BackupRecord] = list(base_keep)
    removed_files = 0
    for _rel_path, group in by_rel.items():
        group_sorted = sorted(group, key=lambda r: r.timestamp)
        if len(group_sorted) <= keep_per_file:
            keep.extend(group_sorted)
            continue
        for old in group_sorted[:-keep_per_file]:
            backup_abs = consumer_root / old.backup_rel_path
            try:
                backup_abs.unlink()
                removed_files += 1
            except OSError:
                pass
        keep.extend(group_sorted[-keep_per_file:])

    keep_sorted = sorted(keep, key=lambda r: r.timestamp)
    if removed_files > 0 or len(keep_sorted) != len(records):
        _write_index(consumer_root, keep_sorted)
    return removed_files


__all__ = [
    "BACKUP_DIR_NAME",
    "BASE_SESSION_ID",
    "BackupLocation",
    "BackupRecord",
    "INDEX_FILENAME",
    "INDEX_SCHEMA",
    "STATE_DIR_NAME",
    "TIMESTAMP_FMT",
    "append_index",
    "backup_base",
    "backup_once",
    "backups_dir",
    "base_record_for",
    "index_path",
    "latest_backup_for",
    "list_backups_for",
    "prune_backups",
    "read_index",
    "restore_backup",
    "restore_base",
    "restore_session",
    "state_dir",
]
