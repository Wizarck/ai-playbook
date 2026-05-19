"""Tests for scripts/rules/delegated-shipping-prompt.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_dsp_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "delegated-shipping-prompt.rule.py",
)
assert SPEC and SPEC.loader
_dsp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_dsp)


VALID_ENVELOPE = (
    "Spawn envelope:\n"
    "L1 self-review required.\n"
    "Actionable comments must be resolved.\n"
    "Gate F approval before merge.\n"
    "See release-management §4.5.\n"
)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "envelope.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_envelope_passes(tmp_path: Path) -> None:
    assert _dsp.validate(_make(tmp_path, VALID_ENVELOPE)) == 0


def test_missing_marker_fails(tmp_path: Path, capsys) -> None:
    text = VALID_ENVELOPE.replace("Gate F approval before merge.\n", "")
    rc = _dsp.validate(_make(tmp_path, text))
    assert rc == 1
    assert "Gate F" in capsys.readouterr().err


def test_missing_reference_fails(tmp_path: Path, capsys) -> None:
    text = VALID_ENVELOPE.replace("See release-management §4.5.\n", "")
    rc = _dsp.validate(_make(tmp_path, text))
    assert rc == 1
    assert "release-management §4.5" in capsys.readouterr().err


def test_missing_file_returns_2(tmp_path: Path) -> None:
    rc = _dsp.validate(tmp_path / "missing.txt")
    assert rc == 2


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_DELEGATED_SHIPPING_PROMPT_SKIP", "1")
    assert _dsp.validate(_make(tmp_path, "empty")) == 0
