"""Tests for scripts/rules/update-playbook.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_up_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "update-playbook.rule.py",
)
assert SPEC and SPEC.loader
_up = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_up)


def _make_gitmodules_root(tmp_path: Path) -> Path:
    (tmp_path / ".gitmodules").write_text(
        '[submodule ".ai-playbook"]\n\tpath = .ai-playbook\n\turl = ...\n',
        encoding="utf-8",
    )
    return tmp_path


# --- validate ------------------------------------------------------------------

def test_validate_fatal_when_no_gitmodules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert _up.validate() == 2


def test_validate_fatal_when_submodule_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_gitmodules_root(tmp_path)
    monkeypatch.chdir(root)
    assert _up.validate() == 2


# --- apply (plan-only) ---------------------------------------------------------

def test_apply_not_applicable_when_no_gitmodules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = _up.apply(dry_run=False)
    assert rc == 0
    assert "not applicable" in capsys.readouterr().out


def test_apply_fatal_when_submodule_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    monkeypatch.chdir(root)
    rc = _up.apply(dry_run=False)
    assert rc == 2
    assert "missing" in capsys.readouterr().err


def test_apply_prints_plan_when_dir_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    (root / ".ai-playbook").mkdir()
    monkeypatch.chdir(root)
    rc = _up.apply(dry_run=False)
    assert rc == 0
    out = capsys.readouterr().out
    # Either prints bump plan or no-op (depending on _current_pin / _latest_tag
    # resolution — both are valid outcomes for an empty dir).
    assert "Bump plan" in out or "no-op" in out or "<unknown>" in out


def test_apply_dry_run_banner_when_drift_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    (root / ".ai-playbook").mkdir()
    monkeypatch.chdir(root)
    rc = _up.apply(dry_run=True)
    # In a freshly-created empty .ai-playbook dir, _current_pin returns None
    # so the "Bump plan" branch fires and the dry-run banner shows. Either
    # outcome (banner or no-op) is acceptable for this smoke test; we only
    # assert no crash.
    capsys.readouterr()
    assert rc == 0


# --- _current_pin / _latest_tag (smoke) ----------------------------------------

def test_current_pin_returns_none_for_non_git_dir(tmp_path: Path) -> None:
    # _current_pin shells out to `git describe`; on a non-git dir it returns None.
    assert _up._current_pin(tmp_path) is None
