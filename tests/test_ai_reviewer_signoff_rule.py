"""Tests for scripts/rules/ai-reviewer-signoff.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ars_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "ai-reviewer-signoff.rule.py",
)
assert SPEC and SPEC.loader
_ars = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ars)


VALID_BODY = (
    "## 4.5 AI-reviewer signoff\n\n"
    "- L1 self-review: done\n"
    "- Actionable comments: addressed\n"
    "- Gate F: approved by maintainer\n"
)


def _make(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "body.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_body_passes(tmp_path: Path) -> None:
    assert _ars.validate(_make(tmp_path, VALID_BODY), None) == 0


def test_missing_marker_fails(tmp_path: Path, capsys) -> None:
    text = "## 4.5\n\nGate F: approved\n"
    rc = _ars.validate(_make(tmp_path, text), None)
    assert rc == 1
    err = capsys.readouterr().err
    assert "L1 self-review" in err


def test_missing_section_fails(tmp_path: Path) -> None:
    text = "L1 self-review done\nActionable comments addressed\nGate F approved\n"
    # Missing §4.5 heading entirely.
    rc = _ars.validate(_make(tmp_path, text), None)
    assert rc == 1


def test_missing_file_returns_2(tmp_path: Path, capsys) -> None:
    rc = _ars.validate(tmp_path / "no-such.md", None)
    assert rc == 2


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_AI_REVIEWER_SIGNOFF_SKIP", "1")
    assert _ars.validate(_make(tmp_path, "empty\n"), None) == 0


def test_no_inputs_is_noop() -> None:
    assert _ars.main(["validate"]) == 0
