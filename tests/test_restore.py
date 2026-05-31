"""Tests for ``scripts.restore`` — the human-gated per-file restore CLI wrapper."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import _backup_helper as bh
from scripts import restore as R


def _w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    _w(tmp_path / "AGENTS.md", "ORIGINAL\n")
    return tmp_path


def _backup(consumer: Path, rel: str, *, session: str = "s1") -> bh.BackupRecord:
    rec = bh.backup_once(
        consumer, consumer / rel,
        location=bh.BackupLocation.CENTRAL, with_timestamp=True, session_id=session,
    )
    assert rec is not None
    return rec


# --- preview (no consent) -------------------------------------------------


def test_preview_does_not_write(consumer: Path) -> None:
    rec = _backup(consumer, "AGENTS.md")
    (consumer / "AGENTS.md").write_bytes(b"EDITED\n")
    res = R.restore(consumer, rel_path="AGENTS.md", from_backup=rec.backup_rel_path, consent=False)
    assert res.ok and res.rc == 0 and res.previewed
    assert (consumer / "AGENTS.md").read_bytes() == b"EDITED\n"
    assert "Re-run with --yes" in res.detail


def test_dry_run_does_not_write_even_with_consent_flag(consumer: Path) -> None:
    rec = _backup(consumer, "AGENTS.md")
    (consumer / "AGENTS.md").write_bytes(b"EDITED\n")
    res = R.restore(consumer, rel_path="AGENTS.md", from_backup=rec.backup_rel_path,
                    consent=True, dry_run=True)
    assert res.previewed and (consumer / "AGENTS.md").read_bytes() == b"EDITED\n"


# --- apply (consent) ------------------------------------------------------


def test_apply_restores_from_specific_backup(consumer: Path) -> None:
    rec = _backup(consumer, "AGENTS.md")
    (consumer / "AGENTS.md").write_bytes(b"EDITED\n")
    res = R.restore(consumer, rel_path="AGENTS.md", from_backup=rec.backup_rel_path, consent=True)
    assert res.ok and res.rc == 0 and res.restored == ["AGENTS.md"]
    assert (consumer / "AGENTS.md").read_bytes() == b"ORIGINAL\n"


def test_apply_latest_when_no_from_or_base(consumer: Path) -> None:
    _backup(consumer, "AGENTS.md")
    (consumer / "AGENTS.md").write_bytes(b"EDITED\n")
    res = R.restore(consumer, rel_path="AGENTS.md", consent=True)
    assert res.ok and (consumer / "AGENTS.md").read_bytes() == b"ORIGINAL\n"


def test_base_restore(consumer: Path) -> None:
    bh.backup_base(consumer, consumer / "AGENTS.md")
    (consumer / "AGENTS.md").write_bytes(b"EDITED\n")
    res = R.restore(consumer, rel_path="AGENTS.md", base=True, consent=True)
    assert res.ok and (consumer / "AGENTS.md").read_bytes() == b"ORIGINAL\n"


def test_all_base_restores_every_base_file(tmp_path: Path) -> None:
    _w(tmp_path / "AGENTS.md", "A0\n")
    _w(tmp_path / ".gitignore", "G0\n")
    bh.backup_base(tmp_path, tmp_path / "AGENTS.md")
    bh.backup_base(tmp_path, tmp_path / ".gitignore")
    (tmp_path / "AGENTS.md").write_bytes(b"A1\n")
    (tmp_path / ".gitignore").write_bytes(b"G1\n")
    res = R.restore(tmp_path, all_base=True, consent=True)
    assert res.ok and sorted(res.restored) == [".gitignore", "AGENTS.md"]
    assert (tmp_path / "AGENTS.md").read_bytes() == b"A0\n"
    assert (tmp_path / ".gitignore").read_bytes() == b"G0\n"


# --- error paths ----------------------------------------------------------


def test_missing_record_rc1(consumer: Path) -> None:
    res = R.restore(consumer, rel_path="nope.md", consent=True)
    assert not res.ok and res.rc == 1


def test_no_base_recorded_rc1(consumer: Path) -> None:
    res = R.restore(consumer, rel_path="AGENTS.md", base=True, consent=True)
    assert not res.ok and res.rc == 1


def test_no_selector_rc1(consumer: Path) -> None:
    res = R.restore(consumer, consent=True)
    assert not res.ok and res.rc == 1


def test_all_base_empty_rc1(consumer: Path) -> None:
    res = R.restore(consumer, all_base=True, consent=True)
    assert not res.ok and res.rc == 1


def test_missing_backup_file_on_disk_rc2(consumer: Path) -> None:
    rec = _backup(consumer, "AGENTS.md")
    # delete the backup blob, keep the index record
    (consumer / rec.backup_rel_path).unlink()
    res = R.restore(consumer, rel_path="AGENTS.md", from_backup=rec.backup_rel_path, consent=True)
    assert not res.ok and res.rc == 2


# --- CLI smoke ------------------------------------------------------------


def test_cli_preview_returns_zero(consumer: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rec = _backup(consumer, "AGENTS.md")
    rc = R.main(["AGENTS.md", "--from", rec.backup_rel_path, "--target", str(consumer)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Would restore" in out
