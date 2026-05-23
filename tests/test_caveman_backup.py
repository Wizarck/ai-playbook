"""Tests for scripts.caveman.backup — make / list / restore / prune."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from scripts.caveman import backup


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# make_backup
# ---------------------------------------------------------------------------


def test_make_backup_creates_target(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "hello\n")
    b = backup.make_backup(tmp_path, "agents", src)
    assert b.is_file()
    assert b.read_text(encoding="utf-8") == "hello\n"
    assert b.parent == tmp_path / ".ai-playbook" / "backups" / "agents"
    assert b.name.startswith("AGENTS.md.")
    assert b.name.endswith(".bak")


def test_make_backup_raises_when_source_missing(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.md"
    with pytest.raises(FileNotFoundError):
        backup.make_backup(tmp_path, "agents", missing)


def test_make_backup_two_sequential_calls_different_names(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "v1\n")
    b1 = backup.make_backup(tmp_path, "agents", src)
    # Sleep 1.1s so timestamp differs (filename resolution = 1s).
    time.sleep(1.1)
    src.write_text("v2\n", encoding="utf-8")
    b2 = backup.make_backup(tmp_path, "agents", src)
    assert b1 != b2
    assert b1.is_file()
    assert b2.is_file()
    assert b1.read_text(encoding="utf-8") == "v1\n"
    assert b2.read_text(encoding="utf-8") == "v2\n"


# ---------------------------------------------------------------------------
# list_backups + latest_backup
# ---------------------------------------------------------------------------


def test_list_backups_empty_when_dir_missing(tmp_path: Path) -> None:
    assert backup.list_backups(tmp_path) == []


def test_list_backups_scoped_to_area(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "x")
    backup.make_backup(tmp_path, "agents", src)
    other = tmp_path / "subdir" / "config.yaml"
    _write(other, "y")
    backup.make_backup(tmp_path, "mcp", other)

    agents_backups = backup.list_backups(tmp_path, "agents")
    assert len(agents_backups) == 1
    mcp_backups = backup.list_backups(tmp_path, "mcp")
    assert len(mcp_backups) == 1
    all_backups = backup.list_backups(tmp_path)
    assert len(all_backups) == 2


def test_latest_backup_returns_newest(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "v1")
    b1 = backup.make_backup(tmp_path, "agents", src)
    time.sleep(1.1)
    src.write_text("v2", encoding="utf-8")
    b2 = backup.make_backup(tmp_path, "agents", src)

    latest = backup.latest_backup(tmp_path, "agents", "AGENTS.md")
    assert latest == b2


def test_latest_backup_returns_none_when_empty(tmp_path: Path) -> None:
    assert backup.latest_backup(tmp_path, "agents", "AGENTS.md") is None


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------


def test_restore_latest(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "original\n")
    backup.make_backup(tmp_path, "agents", src)
    src.write_text("mutated\n", encoding="utf-8")
    assert src.read_text(encoding="utf-8") == "mutated\n"

    backup.restore_backup(tmp_path, "agents", src)
    assert src.read_text(encoding="utf-8") == "original\n"


def test_restore_raises_when_no_backup(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "x")
    with pytest.raises(FileNotFoundError):
        backup.restore_backup(tmp_path, "agents", src)


def test_restore_with_explicit_timestamp(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "v1\n")
    b1 = backup.make_backup(tmp_path, "agents", src)
    time.sleep(1.1)
    src.write_text("v2\n", encoding="utf-8")
    backup.make_backup(tmp_path, "agents", src)
    src.write_text("v3\n", encoding="utf-8")

    # Extract timestamp from b1 filename: AGENTS.md.<ts>.bak
    parts = b1.name.rsplit(".", 2)
    ts = parts[1]
    backup.restore_backup(tmp_path, "agents", src, timestamp=ts)
    assert src.read_text(encoding="utf-8") == "v1\n"


# ---------------------------------------------------------------------------
# prune_backups
# ---------------------------------------------------------------------------


def test_prune_keeps_last_n(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "v0\n")
    # 5 backups with separate timestamps. Sleep 1.1s between each so filenames differ.
    for i in range(5):
        src.write_text(f"v{i}\n", encoding="utf-8")
        backup.make_backup(tmp_path, "agents", src)
        if i < 4:
            time.sleep(1.1)
    assert len(backup.list_backups(tmp_path, "agents")) == 5

    removed = backup.prune_backups(tmp_path, keep_per_file=2)
    assert removed == 3
    remaining = backup.list_backups(tmp_path, "agents")
    assert len(remaining) == 2


def test_prune_does_nothing_under_threshold(tmp_path: Path) -> None:
    src = tmp_path / "AGENTS.md"
    _write(src, "x")
    backup.make_backup(tmp_path, "agents", src)
    removed = backup.prune_backups(tmp_path, keep_per_file=10)
    assert removed == 0


def test_prune_invalid_keep_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        backup.prune_backups(tmp_path, keep_per_file=0)


def test_prune_separates_areas(tmp_path: Path) -> None:
    """Pruning is scoped per (area, basename) — agents/AGENTS.md and mcp/AGENTS.md don't compete."""
    src1 = tmp_path / "AGENTS.md"
    _write(src1, "x")
    backup.make_backup(tmp_path, "agents", src1)
    time.sleep(1.1)
    backup.make_backup(tmp_path, "mcp", src1)

    removed = backup.prune_backups(tmp_path, keep_per_file=1)
    assert removed == 0
    assert len(backup.list_backups(tmp_path, "agents")) == 1
    assert len(backup.list_backups(tmp_path, "mcp")) == 1
