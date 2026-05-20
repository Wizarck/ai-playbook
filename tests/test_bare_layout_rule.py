"""Tests for scripts/rules/bare-layout.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_bl_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "bare-layout.rule.py",
)
assert SPEC and SPEC.loader
_bl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_bl)


# --- _detect_layout helpers ----------------------------------------------------

def _make_bare(tmp_path: Path) -> Path:
    (tmp_path / ".bare").mkdir()
    (tmp_path / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
    return tmp_path


def _make_single_tree(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def _make_malformed(tmp_path: Path) -> Path:
    (tmp_path / ".bare").mkdir()
    (tmp_path / ".git").write_text("invalid pointer\n", encoding="utf-8")
    return tmp_path


# --- _detect_layout ------------------------------------------------------------

def test_detect_bare_layout(tmp_path: Path) -> None:
    root = _make_bare(tmp_path)
    assert _bl._detect_layout(root) == "bare"


def test_detect_single_tree(tmp_path: Path) -> None:
    root = _make_single_tree(tmp_path)
    assert _bl._detect_layout(root) == "single_tree"


def test_detect_none_when_not_a_repo(tmp_path: Path) -> None:
    assert _bl._detect_layout(tmp_path) == "none"


def test_detect_malformed_when_pointer_wrong(tmp_path: Path) -> None:
    root = _make_malformed(tmp_path)
    assert _bl._detect_layout(root) == "malformed"


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_bare(tmp_path: Path) -> None:
    root = _make_bare(tmp_path)
    assert _bl.validate(root) == 0


def test_validate_drift_when_single_tree(tmp_path: Path, capsys) -> None:
    root = _make_single_tree(tmp_path)
    rc = _bl.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "single-tree" in err
    assert "apply" in err  # mentions the fix path


def test_validate_ok_when_not_a_repo(tmp_path: Path) -> None:
    # Walking up from tmp_path finds nothing → not applicable → exit 0.
    nested = tmp_path / "nested"
    nested.mkdir()
    assert _bl.validate(nested) == 0


def test_validate_fatal_when_malformed(tmp_path: Path, capsys) -> None:
    root = _make_malformed(tmp_path)
    rc = _bl.validate(root)
    assert rc == 2
    assert "malformed" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_BARE_LAYOUT_SKIP", "1")
    # Even with single-tree drift, the skip flag wins.
    root = _make_single_tree(tmp_path)
    assert _bl.validate(root) == 0


# --- apply (plan-only) ---------------------------------------------------------

def test_apply_on_bare_is_noop(tmp_path: Path, capsys) -> None:
    root = _make_bare(tmp_path)
    rc = _bl.apply(dry_run=False, cwd=root)
    assert rc == 0
    assert "already uses bare layout" in capsys.readouterr().out


def test_apply_on_no_repo_is_noop(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _bl.apply(dry_run=False, cwd=nested)
    assert rc == 0
    assert "not applicable" in capsys.readouterr().out


def test_apply_on_single_tree_prints_plan(tmp_path: Path, capsys) -> None:
    root = _make_single_tree(tmp_path)
    rc = _bl.apply(dry_run=False, cwd=root)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Migration plan" in out
    assert "git clone --bare" in out
    assert "git worktree add" in out
    assert "plan only" in out  # banner emphasises plan-only nature


def test_apply_dry_run_banner(tmp_path: Path, capsys) -> None:
    root = _make_single_tree(tmp_path)
    rc = _bl.apply(dry_run=True, cwd=root)
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "Migration plan" in out


def test_apply_refuses_malformed(tmp_path: Path, capsys) -> None:
    root = _make_malformed(tmp_path)
    rc = _bl.apply(dry_run=False, cwd=root)
    assert rc == 2
    assert "malformed" in capsys.readouterr().err


# --- _build_plan --------------------------------------------------------------

def test_build_plan_includes_root_path(tmp_path: Path) -> None:
    root = _make_single_tree(tmp_path)
    plan_lines = _bl._build_plan(root)
    joined = "\n".join(plan_lines)
    assert str(root) in joined
    assert "git clone --bare" in joined
    assert "worktree" in joined.lower()
    assert "pre-migration" in joined
