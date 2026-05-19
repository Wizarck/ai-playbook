"""Tests for scripts/rules/doc-drift-enforcement.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_dde_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "doc-drift-enforcement.rule.py",
)
assert SPEC and SPEC.loader
_dde = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_dde)


def test_checker_returns_0_passes() -> None:
    with patch.object(_dde.subprocess, "call", return_value=0):
        assert _dde.validate([]) == 0


def test_checker_returns_nonzero_fails() -> None:
    with patch.object(_dde.subprocess, "call", return_value=1):
        assert _dde.validate([]) == 1


def test_missing_checker_returns_2(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(_dde, "CHECKER", Path("/no/such/check_doc_drift.py"))
    rc = _dde.validate([])
    assert rc == 2
    assert "missing" in capsys.readouterr().err.lower()


def test_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_DOC_DRIFT_SKIP", "1")
    assert _dde.validate([]) == 0


def test_passes_through_paths_to_checker() -> None:
    captured = []

    def _capture(cmd, **kw):
        captured.append(cmd)
        return 0

    with patch.object(_dde.subprocess, "call", side_effect=_capture):
        _dde.validate(["docs/", "specs/"])
    # Ensure paths reached the subprocess invocation.
    assert any("docs/" in str(c) for c in captured)
