"""Tests for scripts/rules/verdict-contract.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_vc_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "verdict-contract.rule.py",
)
assert SPEC and SPEC.loader
_vc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_vc)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "art.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_approved_passes(tmp_path: Path) -> None:
    f = _make(tmp_path, "# Review\n\nFindings OK.\n\n✅ APPROVED\n")
    assert _vc.validate([str(f)]) == 0


def test_iter_n_form_passes(tmp_path: Path) -> None:
    f = _make(tmp_path, "issue list\n\n⚠️ ISSUES FOUND (iter 2)\n")
    assert _vc.validate([str(f)]) == 0


def test_clarification_needed_passes(tmp_path: Path) -> None:
    f = _make(tmp_path, "needs input\n\n❓ CLARIFICATION NEEDED\n")
    assert _vc.validate([str(f)]) == 0


def test_paraphrased_fails(tmp_path: Path, capsys) -> None:
    f = _make(tmp_path, "Approved!\n")
    rc = _vc.validate([str(f)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "paraphrased verdict" in err


def test_multiple_verdicts_fails(tmp_path: Path, capsys) -> None:
    text = "\n".join(["✅ APPROVED", "", "later", "", "✅ APPROVED", ""])
    f = _make(tmp_path, text)
    rc = _vc.validate([str(f)])
    assert rc == 1
    assert "multiple verdict literals" in capsys.readouterr().err


def test_non_qa_artefact_skipped(tmp_path: Path) -> None:
    f = _make(tmp_path, "just a doc.\n")
    assert _vc.validate([str(f)]) == 0


def test_missing_file_returns_2(capsys) -> None:
    rc = _vc.validate(["/no/such/file"])
    assert rc == 2
    assert "path not readable" in capsys.readouterr().err


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_VERDICT_CONTRACT_SKIP", "1")
    f = _make(tmp_path, "Approved!\n")
    assert _vc.validate([str(f)]) == 0
