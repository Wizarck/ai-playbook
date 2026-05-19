"""Tests for scripts/rules/alembic-migration-naming.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_amn_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "alembic-migration-naming.rule.py",
)
assert SPEC and SPEC.loader
_amn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_amn)


def _mk(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_verbose_revision_matching_filename_passes(tmp_path: Path) -> None:
    p = _mk(
        tmp_path,
        "0010_research_sources_tier_b_c.py",
        'revision = "0010_research_sources_tier_b_c"\ndown_revision = "0009_orders_idempotency_key"\n',
    )
    assert _amn.main(["validate", str(p)]) == 0


def test_bare_integer_revision_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _mk(tmp_path, "0010_research.py", 'revision = "0010"\n')
    rc = _amn.main(["validate", str(p)])
    assert rc == 1
    assert "bare-integer" in capsys.readouterr().err.lower()


def test_revision_filename_drift_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _mk(tmp_path, "0010_research.py", 'revision = "0010_research_sources_tier_b_c"\n')
    rc = _amn.main(["validate", str(p)])
    assert rc == 1
    assert "drift" in capsys.readouterr().err.lower()


def test_non_alembic_file_skipped(tmp_path: Path) -> None:
    p = _mk(tmp_path, "helpers.py", "def foo(): return 1\n")
    assert _amn.main(["validate", str(p)]) == 0


def test_directory_walk(tmp_path: Path) -> None:
    _mk(tmp_path, "0001_init.py", 'revision = "0001_init"\n')
    _mk(tmp_path, "0002_add_users.py", 'revision = "0002_add_users"\n')
    assert _amn.main(["validate", str(tmp_path)]) == 0


def test_missing_path_returns_two(tmp_path: Path) -> None:
    assert _amn.main(["validate", str(tmp_path / "nope.py")]) == 2


def test_skip_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIPLAYBOOK_ALEMBIC_MIGRATION_NAMING_SKIP", "1")
    p = _mk(tmp_path, "0010_bad.py", 'revision = "0010"\n')
    assert _amn.main(["validate", str(p)]) == 0
