"""Tests for scripts/rules/auto-pr-stream-closure.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_apsc_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "auto-pr-stream-closure.rule.py",
)
assert SPEC and SPEC.loader
_apsc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_apsc)


def test_no_prior_pr_passes(capsys) -> None:
    with patch.object(_apsc, "_gh_list", return_value=[]):
        assert _apsc.before_create("chore/bump-playbook") == 0
    out = capsys.readouterr().out
    assert "prior_open" in out


def test_prior_pr_returns_1(capsys) -> None:
    with patch.object(_apsc, "_gh_list", return_value=[
        {"number": 42, "headRefName": "chore/bump-playbook", "title": "x"},
    ]):
        rc = _apsc.before_create("chore/bump-playbook")
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    assert rc == 1
    assert "42" in out + err


def test_unrelated_pr_ignored() -> None:
    with patch.object(_apsc, "_gh_list", return_value=[
        {"number": 1, "headRefName": "feature/foo", "title": "x"},
    ]):
        assert _apsc.before_create("chore/bump-playbook") == 0


def test_no_gh_returns_2(capsys) -> None:
    with patch.object(_apsc, "_gh_list", return_value=None):
        rc = _apsc.before_create("any")
    assert rc == 2


def test_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_AUTO_PR_STREAM_CLOSURE_SKIP", "1")
    assert _apsc.before_create("any") == 0


def test_empty_stream_noop() -> None:
    assert _apsc.before_create("") == 0
