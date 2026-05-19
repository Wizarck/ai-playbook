"""Tests for scripts/rules/migration-slot-reservation.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_msr_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "migration-slot-reservation.rule.py",
)
assert SPEC and SPEC.loader
_msr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_msr)


def test_unique_slots_pass(tmp_path: Path) -> None:
    (tmp_path / "0001_a.py").write_text("revision = '0001_a'\n", encoding="utf-8")
    (tmp_path / "0002_b.py").write_text("revision = '0002_b'\n", encoding="utf-8")
    (tmp_path / "0003_c.py").write_text("revision = '0003_c'\n", encoding="utf-8")
    assert _msr.main(["validate", str(tmp_path)]) == 0


def test_duplicate_slot_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "0010_a.py").write_text("revision = '0010_a'\n", encoding="utf-8")
    (tmp_path / "0010_b.py").write_text("revision = '0010_b'\n", encoding="utf-8")
    rc = _msr.main(["validate", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "slot 0010" in err


def test_non_slot_files_ignored(tmp_path: Path) -> None:
    (tmp_path / "env.py").write_text("# alembic env\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")
    assert _msr.main(["validate", str(tmp_path)]) == 0


def test_missing_dir_returns_two(tmp_path: Path) -> None:
    assert _msr.main(["validate", str(tmp_path / "absent")]) == 2


def test_skip_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIPLAYBOOK_MIGRATION_SLOT_RESERVATION_SKIP", "1")
    (tmp_path / "0010_a.py").write_text("", encoding="utf-8")
    (tmp_path / "0010_b.py").write_text("", encoding="utf-8")
    assert _msr.main(["validate", str(tmp_path)]) == 0
