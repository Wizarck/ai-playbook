"""Tests for scripts/rules/stacked-pr-guard.rule.py.

Slice: stacked-pr-guard.

Born from a real loss: ai-playbook #145 was stacked on #144, #144 was merged
with `--delete-branch`, and GitHub closed #145 terminally — `gh pr reopen`
answered "Could not open the pull request" and `gh pr edit --base` answered
"Cannot change the base branch of a closed pull request". The commits survived;
the PR did not, and had to be replaced by #146.

Contracts:
- docs/rules/stacked-pr-guard.rule.md
- docs/rules/error-message-standard.rule.md (❌/FIX/OVERRIDE shape)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "rules" / "stacked-pr-guard.rule.py"

SPEC = importlib.util.spec_from_file_location("stacked_pr_guard_rule", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = _guard
SPEC.loader.exec_module(_guard)


def _fake_gh(view: dict | None, listing: list[dict] | None):
    """Build a _gh stand-in returning canned JSON for the two calls the rule makes."""

    def _gh(args: list[str]) -> str | None:
        if args[:2] == ["pr", "view"]:
            return None if view is None else json.dumps(view)
        if args[:2] == ["pr", "list"]:
            return None if listing is None else json.dumps(listing)
        return None

    return _gh


@pytest.fixture(autouse=True)
def _no_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_guard.SKIP_ENV, raising=False)


def test_clean_pr_with_no_dependents_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "feat/a", "baseRefName": "main", "state": "OPEN"},
        [{"number": 9, "title": "unrelated", "baseRefName": "main", "headRefName": "feat/z"}],
    ))
    assert _guard.validate("1") == 0


def test_dependent_pr_blocks(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "fix/base", "baseRefName": "main", "state": "OPEN"},
        [{"number": 145, "title": "stacked", "baseRefName": "fix/base", "headRefName": "feat/child"}],
    ))
    assert _guard.validate("144") == 1
    err = capsys.readouterr().err
    assert "#145" in err
    assert "gh pr edit 145 --base main" in err, "the fix must name the exact retarget command"


def test_error_follows_the_canonical_shape(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "fix/base", "baseRefName": "main", "state": "OPEN"},
        [{"number": 2, "title": "child", "baseRefName": "fix/base", "headRefName": "feat/child"}],
    ))
    _guard.validate("1")
    err = capsys.readouterr().err
    assert err.startswith("❌ ")
    assert "FIX:" in err
    assert "OVERRIDE:" in err


def test_multiple_dependents_are_all_listed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "fix/base", "baseRefName": "release/1.x", "state": "OPEN"},
        [
            {"number": 2, "title": "b", "baseRefName": "fix/base", "headRefName": "feat/b"},
            {"number": 3, "title": "c", "baseRefName": "fix/base", "headRefName": "feat/c"},
            {"number": 4, "title": "elsewhere", "baseRefName": "main", "headRefName": "feat/d"},
        ],
    ))
    assert _guard.validate("1") == 1
    err = capsys.readouterr().err
    assert "#2" in err and "#3" in err
    assert "#4" not in err, "a PR based on main is not a dependent"
    assert "--base release/1.x" in err, "retarget must point at the merging PR's own base"


def test_self_is_never_its_own_dependent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PR whose head equals its own base would otherwise self-report."""
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "weird", "baseRefName": "main", "state": "OPEN"},
        [{"number": 1, "title": "self", "baseRefName": "weird", "headRefName": "weird"}],
    ))
    assert _guard.validate("1") == 0


def test_undeterminable_returns_2_not_a_false_all_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """gh missing or unauthenticated must never read as 'no dependents'."""
    monkeypatch.setattr(_guard, "_gh", _fake_gh(None, None))
    assert _guard.validate("1") == 2


def test_listing_failure_alone_still_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "feat/a", "baseRefName": "main", "state": "OPEN"}, None
    ))
    assert _guard.validate("1") == 2


def test_break_glass_short_circuits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv(_guard.SKIP_ENV, "1")
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "fix/base", "baseRefName": "main", "state": "OPEN"},
        [{"number": 2, "title": "child", "baseRefName": "fix/base", "headRefName": "feat/child"}],
    ))
    assert _guard.validate("1") == 0
    assert _guard.SKIP_ENV in capsys.readouterr().err


def test_json_output_is_machine_readable(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(_guard, "_gh", _fake_gh(
        {"headRefName": "fix/base", "baseRefName": "main", "state": "OPEN"},
        [{"number": 145, "title": "child", "baseRefName": "fix/base", "headRefName": "feat/child"}],
    ))
    _guard.validate("144", as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["dependents"] == [145]
    assert payload["base"] == "main"


def test_no_pr_argument_is_a_noop() -> None:
    assert _guard.main(["validate"]) == 0


def test_doc_and_hardrule_agree_on_flags() -> None:
    """The rule doc and the script must not drift on the CLI surface."""
    doc = (REPO_ROOT / "docs" / "rules" / "stacked-pr-guard.rule.md").read_text(encoding="utf-8")
    assert "validate --pr" in doc
    assert _guard.SKIP_ENV in doc
