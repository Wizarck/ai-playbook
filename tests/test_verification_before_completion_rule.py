"""Tests for scripts/rules/verification-before-completion.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_vbc_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "verification-before-completion.rule.py",
)
assert SPEC and SPEC.loader
_vbc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_vbc)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "msg.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_approved_with_pytest_output_passes(tmp_path: Path) -> None:
    text = (
        "```\n"
        "$ pytest tests/\n"
        "============ 42 passed in 0.84s ============\n"
        "```\n\n"
        "✅ APPROVED\n"
    )
    assert _vbc.validate([str(_make(tmp_path, text))]) == 0


def test_approved_without_verification_fails(tmp_path: Path, capsys) -> None:
    text = "Looks good.\n\n✅ APPROVED\n"
    rc = _vbc.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "fresh verification" in capsys.readouterr().err.lower()


def test_synthesis_audit_structure_passes(tmp_path: Path) -> None:
    text = (
        "## Synthesis\n\n"
        "Covers AC-1, AC-2, AC-3 per spec §3.\n\n"
        "✅ APPROVED\n"
    )
    assert _vbc.validate([str(_make(tmp_path, text))]) == 0


def test_no_approved_literal_passes(tmp_path: Path) -> None:
    assert _vbc.validate([str(_make(tmp_path, "just a status update.\n"))]) == 0


def test_mypy_success_passes(tmp_path: Path) -> None:
    text = (
        "```\n"
        "$ mypy --strict apps/\n"
        "Success: no issues found in 247 source files\n"
        "```\n\n"
        "✅ APPROVED\n"
    )
    assert _vbc.validate([str(_make(tmp_path, text))]) == 0


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_VERIFICATION_BEFORE_COMPLETION_SKIP", "1")
    f = _make(tmp_path, "✅ APPROVED\n")
    assert _vbc.validate([str(f)]) == 0
