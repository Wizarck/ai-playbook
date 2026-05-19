"""Tests for scripts/rules/bootstrap-directive.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_bd_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "bootstrap-directive.rule.py",
)
assert SPEC and SPEC.loader
_bd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_bd)


VALID_AGENTS = (
    "## 0 Bootstrap directive\n\n"
    "Before responding:\n"
    "1. Read dispatcher-chain.md\n"
    "2. Consult injected-context.md\n"
    "3. Scan openspec/changes/*/\n"
    "4. Respond\n"
)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "AGENTS.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_canonical_block_passes(tmp_path: Path) -> None:
    assert _bd.validate([str(_make(tmp_path, VALID_AGENTS))]) == 0


def test_missing_section_zero_fails(tmp_path: Path, capsys) -> None:
    text = "# Introduction\n\nBlah.\n"
    rc = _bd.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "§0" in capsys.readouterr().err


def test_missing_token_fails(tmp_path: Path, capsys) -> None:
    text = "## 0 Bootstrap\n\nNothing useful here.\n"
    rc = _bd.validate([str(_make(tmp_path, text))])
    assert rc == 1
    assert "missing tokens" in capsys.readouterr().err


def test_missing_file_returns_2(capsys) -> None:
    assert _bd.validate(["/no/such/AGENTS.md"]) == 2


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_BOOTSTRAP_DIRECTIVE_SKIP", "1")
    assert _bd.validate([str(_make(tmp_path, "broken"))]) == 0
