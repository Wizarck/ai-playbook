"""Tests for scripts/rules/error-message-standard.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ems_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "error-message-standard.rule.py",
)
assert SPEC and SPEC.loader
_ems = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ems)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "log.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_canonical_shape_passes(tmp_path: Path) -> None:
    text = (
        "❌ Schema validation failed at /path:1\n"
        "   FIX: align the spec to schemas/schema-agents-md-v1.json.\n"
        "   OVERRIDE: none\n"
    )
    assert _ems.validate([str(_make(tmp_path, text))]) == 0


def test_missing_fix_fails(tmp_path: Path, capsys) -> None:
    text = "❌ Something broken at /path:1\n   OVERRIDE: none\n"
    rc = _ems.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "FIX:" in capsys.readouterr().err


def test_missing_override_fails(tmp_path: Path, capsys) -> None:
    text = "❌ Something broken at /path:1\n   FIX: do x.\n"
    rc = _ems.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "OVERRIDE" in capsys.readouterr().err


def test_no_errors_passes(tmp_path: Path) -> None:
    assert _ems.validate([str(_make(tmp_path, "all good.\n"))]) == 0


def test_multi_error_one_clean_one_bad(tmp_path: Path) -> None:
    text = (
        "❌ first at a:1\n"
        "   FIX: do x.\n"
        "   OVERRIDE: none\n"
        "\n"
        "❌ second at b:2\n"
        "   no follow up here\n"
    )
    rc = _ems.validate([str(_make(tmp_path, text))])
    assert rc == 1


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_ERROR_MESSAGE_STANDARD_SKIP", "1")
    text = "❌ broken at /:1\n"
    assert _ems.validate([str(_make(tmp_path, text))]) == 0
