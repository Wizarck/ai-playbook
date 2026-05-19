"""Tests for scripts/rules/github-project-board-schema.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_gpbs_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "github-project-board-schema.rule.py",
)
assert SPEC and SPEC.loader
_gpbs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_gpbs)


VALID_FIELDS = [
    {
        "name": "Status",
        "options": [
            {"name": "Todo"},
            {"name": "In Progress"},
            {"name": "In Review"},
            {"name": "Blocked"},
            {"name": "Done"},
        ],
    },
    {"name": "Slice ID"},
    {"name": "Last Update"},
]


def test_canonical_schema_passes() -> None:
    with patch.object(_gpbs, "_gh_field_list", return_value=VALID_FIELDS):
        assert _gpbs.validate("p1") == 0


def test_missing_status_options_fails(capsys) -> None:
    bad = list(VALID_FIELDS)
    bad[0] = {"name": "Status", "options": [{"name": "Todo"}, {"name": "Done"}]}
    with patch.object(_gpbs, "_gh_field_list", return_value=bad):
        rc = _gpbs.validate("p1")
    assert rc == 1
    assert "Status` options drift" in capsys.readouterr().err


def test_missing_text_field_fails(capsys) -> None:
    bad = [VALID_FIELDS[0], {"name": "Slice ID"}]
    with patch.object(_gpbs, "_gh_field_list", return_value=bad):
        rc = _gpbs.validate("p1")
    assert rc == 1
    assert "text fields missing" in capsys.readouterr().err


def test_missing_gh_returns_2() -> None:
    with patch.object(_gpbs, "_gh_field_list", return_value=None):
        assert _gpbs.validate("p1") == 2


def test_skip_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_GITHUB_PROJECT_BOARD_SCHEMA_SKIP", "1")
    assert _gpbs.validate("p1") == 0


def test_no_project_arg_is_noop() -> None:
    assert _gpbs.main(["validate"]) == 0
