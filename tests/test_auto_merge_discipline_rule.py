"""Tests for scripts/rules/auto-merge-discipline.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_amd_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "auto-merge-discipline.rule.py",
)
assert SPEC and SPEC.loader
_amd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_amd)


VALID_BODY = (
    "## 4.5 AI-reviewer signoff\n"
    "L1 self-review done. Actionable comments resolved. Gate F approved.\n"
)


def test_all_checks_green_with_valid_body_passes() -> None:
    with patch.object(_amd, "_gh_pr_view", return_value={
        "body": VALID_BODY,
        "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED"}],
        "state": "OPEN",
    }):
        assert _amd.validate("123") == 0


def test_missing_markers_fails(capsys) -> None:
    with patch.object(_amd, "_gh_pr_view", return_value={
        "body": "## 4.5\n\n(empty)\n",
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    }):
        rc = _amd.validate("123")
    assert rc == 1
    assert "markers missing" in capsys.readouterr().err


def test_failing_ci_blocks() -> None:
    with patch.object(_amd, "_gh_pr_view", return_value={
        "body": VALID_BODY,
        "statusCheckRollup": [{"conclusion": "FAILURE"}],
    }):
        assert _amd.validate("123") == 1


def test_missing_gh_returns_2(capsys) -> None:
    with patch.object(_amd, "_gh_pr_view", return_value=None):
        rc = _amd.validate("123")
    assert rc == 2
    assert "could not fetch" in capsys.readouterr().err


def test_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_AUTO_MERGE_DISCIPLINE_SKIP", "1")
    assert _amd.validate("anything") == 0


def test_no_pr_arg_is_noop() -> None:
    assert _amd.main(["validate"]) == 0
