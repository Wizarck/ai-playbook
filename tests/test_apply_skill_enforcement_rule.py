"""Tests for scripts/rules/apply-skill-enforcement.rule.py."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ase_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "apply-skill-enforcement.rule.py",
)
assert SPEC and SPEC.loader
_ase = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ase)


def _fake_run(rc: int):
    def _r(cmd, **kw):
        return subprocess.CompletedProcess(cmd, rc, "", "")
    return _r


def test_validate_passes_when_marker_returns_0() -> None:
    with patch.object(_ase.subprocess, "run", side_effect=_fake_run(0)):
        assert _ase.validate("test-change") == 0


def test_validate_fails_when_marker_returns_nonzero(capsys) -> None:
    with patch.object(_ase.subprocess, "run", side_effect=_fake_run(2)):
        rc = _ase.validate("test-change")
    assert rc == 1
    assert "apply session marker" in capsys.readouterr().err


def test_validate_empty_change_id_is_noop() -> None:
    assert _ase.main(["validate", ""]) == 0


def test_validate_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_APPLY_SKILL_SKIP", "1")
    assert _ase.validate("anything") == 0


def test_validate_missing_marker_script_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ase, "MARKER_SCRIPT", Path("/no/such/script.py"))
    assert _ase.validate("any") == 2
