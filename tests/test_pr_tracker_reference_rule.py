"""Tests for scripts/rules/pr-tracker-reference.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ptr_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "pr-tracker-reference.rule.py",
)
assert SPEC and SPEC.loader
_ptr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ptr)


def _make(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "body.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_github_closes_in_body_passes(tmp_path: Path) -> None:
    p = _make(tmp_path, "Closes #42\n")
    rc = _ptr.main(["validate", "--pr-title", "any", "--pr-body-file", str(p)])
    assert rc == 0


def test_jira_prefix_in_title_passes(tmp_path: Path) -> None:
    p = _make(tmp_path, "no github ref here\n")
    rc = _ptr.main(["validate", "--pr-title", "GPLO-1234: bump", "--pr-body-file", str(p)])
    assert rc == 0


def test_no_reference_fails(tmp_path: Path, capsys) -> None:
    p = _make(tmp_path, "no tracker reference at all\n")
    rc = _ptr.main(["validate", "--pr-title", "feat: thing", "--pr-body-file", str(p)])
    assert rc == 1
    assert "tracker reference" in capsys.readouterr().err.lower()


def test_fixes_form_passes(tmp_path: Path) -> None:
    p = _make(tmp_path, "Fixes #99\n")
    assert _ptr.main(["validate", "--pr-title", "anything", "--pr-body-file", str(p)]) == 0


def test_resolves_form_passes(tmp_path: Path) -> None:
    p = _make(tmp_path, "Resolves #123 and more\n")
    assert _ptr.main(["validate", "--pr-title", "anything", "--pr-body-file", str(p)]) == 0


def test_skip_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_PR_TRACKER_REFERENCE_SKIP", "1")
    p = _make(tmp_path, "no ref\n")
    assert _ptr.main(["validate", "--pr-title", "feat: x", "--pr-body-file", str(p)]) == 0
