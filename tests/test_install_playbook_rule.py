"""Tests for scripts/rules/install-playbook.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_ip_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "install-playbook.rule.py",
)
assert SPEC and SPEC.loader
_ip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_ip)


def _make_gitmodules_root(tmp_path: Path) -> Path:
    (tmp_path / ".gitmodules").write_text(
        '[submodule ".ai-playbook"]\n\tpath = .ai-playbook\n\turl = ...\n',
        encoding="utf-8",
    )
    return tmp_path


# --- validate ------------------------------------------------------------------

def test_validate_fatal_when_no_gitmodules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert _ip.validate() == 2


def test_validate_drift_when_submodule_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_gitmodules_root(tmp_path)
    monkeypatch.chdir(root)
    assert _ip.validate() == 1


# --- apply (plan-only) ---------------------------------------------------------

def test_apply_not_applicable_when_no_gitmodules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = _ip.apply(dry_run=False)
    assert rc == 0
    assert "not applicable" in capsys.readouterr().out


def test_apply_noop_when_already_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    (root / ".ai-playbook").mkdir()
    monkeypatch.chdir(root)
    rc = _ip.apply(dry_run=False)
    assert rc == 0
    assert "already installed" in capsys.readouterr().out


def test_apply_prints_plan_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    monkeypatch.chdir(root)
    rc = _ip.apply(dry_run=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Install plan" in out
    assert "git submodule add" in out
    assert "plan only" in out


def test_apply_dry_run_banner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _make_gitmodules_root(tmp_path)
    monkeypatch.chdir(root)
    rc = _ip.apply(dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "Install plan" in out
