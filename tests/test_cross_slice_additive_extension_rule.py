"""Tests for scripts/rules/cross-slice-additive-extension.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_csae_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "cross-slice-additive-extension.rule.py",
)
assert SPEC and SPEC.loader
_csae = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_csae)


def _mk(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "0010_add.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_nullable_shape_a_passes(tmp_path: Path) -> None:
    p = _mk(tmp_path, 'op.execute("ALTER TABLE x ADD COLUMN k TEXT")\n')
    assert _csae.main(["validate", str(p)]) == 0


def test_not_null_default_shape_b_passes(tmp_path: Path) -> None:
    p = _mk(
        tmp_path,
        'op.execute("ALTER TABLE x ADD COLUMN provenance_chain TEXT[] NOT NULL DEFAULT \'{}\'")\n',
    )
    assert _csae.main(["validate", str(p)]) == 0


def test_jsonb_shape_c_passes(tmp_path: Path) -> None:
    p = _mk(
        tmp_path,
        'op.execute("ALTER TABLE x ADD COLUMN extension_payload JSONB NOT NULL DEFAULT \'{}\'")\n',
    )
    assert _csae.main(["validate", str(p)]) == 0


def test_not_null_without_default_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _mk(
        tmp_path,
        'op.execute("ALTER TABLE x ADD COLUMN audit_trail_id UUID NOT NULL")\n',
    )
    rc = _csae.main(["validate", str(p)])
    assert rc == 1
    assert "default" in capsys.readouterr().err.lower()


def test_missing_file_returns_two(tmp_path: Path) -> None:
    assert _csae.main(["validate", str(tmp_path / "absent.py")]) == 2


def test_skip_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIPLAYBOOK_CROSS_SLICE_ADDITIVE_EXTENSION_SKIP", "1")
    p = _mk(tmp_path, 'op.execute("ALTER TABLE x ADD COLUMN k UUID NOT NULL")\n')
    assert _csae.main(["validate", str(p)]) == 0
