"""Tests for ``scripts._backup_helper`` — backup-once + index + restore + prune."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scripts import _backup_helper as bh


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_lf(path: Path, content: str) -> None:
    """Write text with LF endings regardless of platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    _write_lf(tmp_path / "AGENTS.md", "# project agents\n")
    _write_lf(tmp_path / ".gitignore", "node_modules/\n")
    sub = tmp_path / ".claude"
    sub.mkdir()
    _write_lf(sub / "settings.json", "{}\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Backup destination resolution
# ---------------------------------------------------------------------------


def test_next_to_file_with_timestamp_writes_alongside(consumer: Path) -> None:
    rec = bh.backup_once(
        consumer,
        consumer / "AGENTS.md",
        location=bh.BackupLocation.NEXT_TO_FILE,
        with_timestamp=True,
    )
    assert rec is not None
    backup_abs = consumer / rec.backup_rel_path
    assert backup_abs.parent == consumer
    assert backup_abs.name.startswith("AGENTS.md.")
    assert backup_abs.name.endswith(".bak")
    assert backup_abs.is_file()
    assert backup_abs.read_bytes() == b"# project agents\n"


def test_next_to_file_without_timestamp_writes_single_slot(consumer: Path) -> None:
    rec = bh.backup_once(
        consumer,
        consumer / "AGENTS.md",
        location=bh.BackupLocation.NEXT_TO_FILE,
        with_timestamp=False,
    )
    assert rec is not None
    backup_abs = consumer / rec.backup_rel_path
    assert backup_abs.name == "AGENTS.md.bak"


def test_central_location_mirrors_rel_path(consumer: Path) -> None:
    rec = bh.backup_once(
        consumer,
        consumer / ".claude" / "settings.json",
        location=bh.BackupLocation.CENTRAL,
        with_timestamp=True,
    )
    assert rec is not None
    backup_abs = consumer / rec.backup_rel_path
    assert backup_abs.is_file()
    assert backup_abs.parent == bh.backups_dir(consumer) / ".claude"
    assert backup_abs.name.startswith("settings.json.")


def test_missing_source_returns_none(consumer: Path) -> None:
    rec = bh.backup_once(consumer, consumer / "no-such-file.md")
    assert rec is None
    assert not bh.index_path(consumer).is_file()


def test_source_outside_consumer_root_raises(tmp_path_factory: pytest.TempPathFactory) -> None:
    consumer = tmp_path_factory.mktemp("consumer")
    (consumer / "AGENTS.md").write_text("# inside\n", encoding="utf-8")
    foreign_root = tmp_path_factory.mktemp("foreign")
    foreign = foreign_root / "stuff.md"
    foreign.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="not under consumer_root"):
        bh.backup_once(consumer, foreign)


# ---------------------------------------------------------------------------
# Index — read / write / append
# ---------------------------------------------------------------------------


def test_index_empty_when_no_backups(consumer: Path) -> None:
    assert bh.read_index(consumer) == []


def test_index_appended_on_each_backup(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    bh.backup_once(consumer, consumer / ".gitignore", with_timestamp=True)
    records = bh.read_index(consumer)
    assert len(records) == 2
    rel_paths = sorted(r.rel_path for r in records)
    assert rel_paths == [".gitignore", "AGENTS.md"]


def test_index_schema_marker(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md")
    raw = json.loads(bh.index_path(consumer).read_text(encoding="utf-8"))
    assert raw["schema"] == bh.INDEX_SCHEMA
    assert isinstance(raw["records"], list)


def test_index_tolerates_malformed_file(consumer: Path) -> None:
    idx = bh.index_path(consumer)
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("not json {", encoding="utf-8")
    assert bh.read_index(consumer) == []
    bh.backup_once(consumer, consumer / "AGENTS.md")
    assert len(bh.read_index(consumer)) == 1


def test_index_drops_records_missing_required_fields(consumer: Path) -> None:
    idx = bh.index_path(consumer)
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(
        json.dumps({
            "schema": bh.INDEX_SCHEMA,
            "records": [
                {"rel_path": "AGENTS.md"},  # missing every other field
                {
                    "rel_path": "AGENTS.md",
                    "backup_rel_path": "AGENTS.md.x.bak",
                    "location": "next",
                    "timestamp": "2026-05-27T00-00-00Z",
                    "sha256": "deadbeef",
                    "source_size": 12,
                    "session_id": "test",
                },
            ],
        }),
        encoding="utf-8",
    )
    records = bh.read_index(consumer)
    assert len(records) == 1
    assert records[0].rel_path == "AGENTS.md"
    assert records[0].sha256 == "deadbeef"


# ---------------------------------------------------------------------------
# Discovery (latest, list)
# ---------------------------------------------------------------------------


def test_latest_backup_returns_newest(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    time.sleep(1.05)  # bump the per-second timestamp
    _write_lf(consumer / "AGENTS.md", "# changed\n")
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    latest = bh.latest_backup_for(consumer, "AGENTS.md")
    assert latest is not None
    assert (consumer / latest.backup_rel_path).read_bytes() == b"# changed\n"


def test_list_backups_for_returns_newest_first(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    time.sleep(1.05)
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    backups = bh.list_backups_for(consumer, "AGENTS.md")
    assert len(backups) == 2
    assert backups[0].timestamp >= backups[1].timestamp


def test_latest_backup_finds_central_and_next_indifferently(consumer: Path) -> None:
    """Discovery via index must be location-agnostic per the design contract."""
    bh.backup_once(
        consumer, consumer / "AGENTS.md",
        location=bh.BackupLocation.NEXT_TO_FILE,
        with_timestamp=True,
    )
    time.sleep(1.05)
    bh.backup_once(
        consumer, consumer / "AGENTS.md",
        location=bh.BackupLocation.CENTRAL,
        with_timestamp=True,
    )
    listing = bh.list_backups_for(consumer, "AGENTS.md")
    assert {r.location for r in listing} == {"next", "central"}


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def test_restore_writes_backup_content_to_source(consumer: Path) -> None:
    original = (consumer / "AGENTS.md").read_bytes()
    rec = bh.backup_once(consumer, consumer / "AGENTS.md")
    assert rec is not None
    _write_lf(consumer / "AGENTS.md", "# corrupted\n")
    bh.restore_backup(consumer, rec)
    assert (consumer / "AGENTS.md").read_bytes() == original


def test_restore_to_alternate_target(consumer: Path, tmp_path: Path) -> None:
    rec = bh.backup_once(consumer, consumer / "AGENTS.md")
    assert rec is not None
    target = consumer / "AGENTS.restored.md"
    out = bh.restore_backup(consumer, rec, target=target)
    assert out == target.resolve()
    assert target.read_bytes() == b"# project agents\n"


def test_restore_missing_backup_file_raises(consumer: Path) -> None:
    rec = bh.backup_once(consumer, consumer / "AGENTS.md")
    assert rec is not None
    (consumer / rec.backup_rel_path).unlink()
    with pytest.raises(FileNotFoundError, match="backup file missing"):
        bh.restore_backup(consumer, rec)


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------


def test_prune_keeps_only_n_newest(consumer: Path) -> None:
    for _ in range(5):
        bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
        time.sleep(1.05)
    removed = bh.prune_backups(consumer, keep_per_file=2)
    assert removed == 3
    remaining = bh.list_backups_for(consumer, "AGENTS.md")
    assert len(remaining) == 2


def test_prune_other_files_unaffected(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    time.sleep(1.05)
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    bh.backup_once(consumer, consumer / ".gitignore", with_timestamp=True)
    bh.prune_backups(consumer, keep_per_file=1)
    assert len(bh.list_backups_for(consumer, "AGENTS.md")) == 1
    assert len(bh.list_backups_for(consumer, ".gitignore")) == 1


def test_prune_rejects_invalid_keep_value(consumer: Path) -> None:
    with pytest.raises(ValueError, match=">= 1"):
        bh.prune_backups(consumer, keep_per_file=0)


def test_prune_noop_when_under_limit(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    removed = bh.prune_backups(consumer, keep_per_file=10)
    assert removed == 0


# ---------------------------------------------------------------------------
# Record content sanity
# ---------------------------------------------------------------------------


def test_record_carries_sha_and_size(consumer: Path) -> None:
    rec = bh.backup_once(consumer, consumer / "AGENTS.md")
    assert rec is not None
    assert rec.source_size == len("# project agents\n".encode("utf-8"))
    assert len(rec.sha256) == 64  # SHA-256 hex


def test_session_id_grouping(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", session_id="session-a")
    bh.backup_once(consumer, consumer / ".gitignore", session_id="session-a")
    bh.backup_once(consumer, consumer / ".claude" / "settings.json", session_id="session-b")
    records = bh.read_index(consumer)
    sessions = {r.session_id for r in records}
    assert sessions == {"session-a", "session-b"}
    a_records = [r for r in records if r.session_id == "session-a"]
    assert {r.rel_path for r in a_records} == {"AGENTS.md", ".gitignore"}


# ---------------------------------------------------------------------------
# restore_session — set-level rollback of a failed transactional apply
# ---------------------------------------------------------------------------


def test_restore_session_reverts_all_files_to_pre_session(consumer: Path) -> None:
    # Back up two files under one session (snapshots their pre-session content).
    bh.backup_once(consumer, consumer / "AGENTS.md", session_id="sess-1")
    bh.backup_once(consumer, consumer / ".gitignore", session_id="sess-1")
    # Now both files get mutated (simulating the apply that we will roll back).
    _write_lf(consumer / "AGENTS.md", "# MUTATED\n")
    _write_lf(consumer / ".gitignore", "MUTATED\n")

    restored, warnings = bh.restore_session(consumer, "sess-1")

    assert warnings == []
    assert {p.name for p in restored} == {"AGENTS.md", ".gitignore"}
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == "# project agents\n"
    assert (consumer / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"


def test_restore_session_uses_earliest_snapshot_per_file(consumer: Path) -> None:
    # First (pre-session) backup, then a later backup of mutated content.
    bh.backup_once(consumer, consumer / "AGENTS.md", session_id="sess-2")
    time.sleep(1.1)  # timestamp granularity is whole seconds
    _write_lf(consumer / "AGENTS.md", "# later mutation\n")
    bh.backup_once(consumer, consumer / "AGENTS.md", session_id="sess-2")
    _write_lf(consumer / "AGENTS.md", "# final mutation\n")

    bh.restore_session(consumer, "sess-2")

    # The EARLIEST snapshot (original pre-session content) must win.
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == "# project agents\n"


def test_restore_session_ignores_other_sessions(consumer: Path) -> None:
    bh.backup_once(consumer, consumer / "AGENTS.md", session_id="sess-a")
    bh.backup_once(consumer, consumer / ".gitignore", session_id="sess-b")
    _write_lf(consumer / "AGENTS.md", "# mutated a\n")
    _write_lf(consumer / ".gitignore", "mutated b\n")

    restored, _ = bh.restore_session(consumer, "sess-a")

    assert {p.name for p in restored} == {"AGENTS.md"}
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == "# project agents\n"
    # The other session's file is untouched by this rollback.
    assert (consumer / ".gitignore").read_text(encoding="utf-8") == "mutated b\n"


def test_restore_session_warns_on_missing_backup_file(consumer: Path) -> None:
    record = bh.backup_once(consumer, consumer / "AGENTS.md", session_id="sess-x")
    assert record is not None
    # Delete the backup file on disk to simulate a missing artifact.
    (consumer / record.backup_rel_path).unlink()

    restored, warnings = bh.restore_session(consumer, "sess-x")

    assert restored == []
    assert len(warnings) == 1
    assert "backup file missing" in warnings[0]


# ---------------------------------------------------------------------------
# BASE snapshot (pre-playbook anchor for uninstall)
# ---------------------------------------------------------------------------


def test_backup_base_captures_once_and_is_idempotent(consumer: Path) -> None:
    rec1 = bh.backup_base(consumer, consumer / "AGENTS.md")
    assert rec1 is not None
    assert rec1.session_id == bh.BASE_SESSION_ID
    # Second call is a no-op: the base is the very first state, never overwritten.
    # Even after the file changes, the base record stays the original.
    _write_lf(consumer / "AGENTS.md", "# mutated by playbook\n")
    rec2 = bh.backup_base(consumer, consumer / "AGENTS.md")
    assert rec2 is None
    base = bh.base_record_for(consumer, "AGENTS.md")
    assert base is not None and base.sha256 == rec1.sha256


def test_restore_base_returns_preplaybook_content(consumer: Path) -> None:
    original = (consumer / "AGENTS.md").read_text(encoding="utf-8")
    bh.backup_base(consumer, consumer / "AGENTS.md")
    _write_lf(consumer / "AGENTS.md", "# heavily rewritten\n")
    restored, warnings = bh.restore_base(consumer, "AGENTS.md")
    assert warnings == []
    assert len(restored) == 1
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == original


def test_restore_base_all_files(consumer: Path) -> None:
    bh.backup_base(consumer, consumer / "AGENTS.md")
    bh.backup_base(consumer, consumer / ".gitignore")
    _write_lf(consumer / "AGENTS.md", "x\n")
    _write_lf(consumer / ".gitignore", "y\n")
    restored, warnings = bh.restore_base(consumer)
    assert warnings == []
    assert len(restored) == 2
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == "# project agents\n"
    assert (consumer / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"


def test_prune_never_removes_base(consumer: Path) -> None:
    bh.backup_base(consumer, consumer / "AGENTS.md")
    # Pile up ordinary backups for the same file.
    for _ in range(5):
        time.sleep(0.01)
        bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    bh.prune_backups(consumer, keep_per_file=1)
    # The base survives pruning regardless of keep_per_file.
    assert bh.base_record_for(consumer, "AGENTS.md") is not None
