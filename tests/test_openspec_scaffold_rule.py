"""Tests for scripts/rules/openspec-scaffold.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_os_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "openspec-scaffold.rule.py",
)
assert SPEC and SPEC.loader
_os_rule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_os_rule)


# --- helpers -----------------------------------------------------------------


def _make_consumer(
    tmp_path: Path,
    *,
    with_agents: bool = True,
    agents_mentions_openspec: bool = False,
    with_openspec_dir: bool = False,
    with_changes: bool = False,
    with_specs: bool = False,
) -> Path:
    """Build a synthetic consumer root under tmp_path."""
    if with_agents:
        body = "# AGENTS\n"
        if agents_mentions_openspec:
            body += "\nSee `openspec/changes/` for in-flight proposals.\n"
        (tmp_path / "AGENTS.md").write_text(body, encoding="utf-8")
    if with_openspec_dir:
        (tmp_path / "openspec").mkdir()
    if with_changes:
        (tmp_path / "openspec" / "changes").mkdir(parents=True, exist_ok=True)
    if with_specs:
        (tmp_path / "openspec" / "specs").mkdir(parents=True, exist_ok=True)
    return tmp_path


# --- validate ----------------------------------------------------------------


def test_validate_ok_when_scaffold_complete(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path,
        with_openspec_dir=True,
        with_changes=True,
        with_specs=True,
    )
    assert _os_rule.validate(root) == 0


def test_validate_drift_when_changes_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        with_openspec_dir=True,
        with_specs=True,
    )
    rc = _os_rule.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "openspec/changes/" in err


def test_validate_drift_when_specs_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        with_openspec_dir=True,
        with_changes=True,
    )
    rc = _os_rule.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "openspec/specs/" in err


def test_validate_drift_when_both_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(
        tmp_path,
        with_openspec_dir=True,
    )
    rc = _os_rule.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "openspec/changes/" in err
    assert "openspec/specs/" in err


def test_validate_not_applicable_when_openspec_absent_and_unreferenced(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    assert _os_rule.validate(root) == 0


def test_validate_triggers_via_agents_md_mention(tmp_path: Path, capsys) -> None:
    # No openspec/ dir, but AGENTS.md mentions openspec/changes/ — rule applies.
    root = _make_consumer(tmp_path, agents_mentions_openspec=True)
    rc = _os_rule.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "openspec/changes/" in err
    assert "openspec/specs/" in err


def test_validate_fatal_when_path_is_file(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path, with_openspec_dir=True, with_specs=True)
    # Replace openspec/changes with a regular file.
    (root / "openspec" / "changes").write_text("not a dir", encoding="utf-8")
    rc = _os_rule.validate(root)
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _os_rule.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drift state, but skip flag bypasses everything.
    root = _make_consumer(tmp_path, with_openspec_dir=True)
    monkeypatch.setenv("AIPLAYBOOK_OPENSPEC_SCAFFOLD_SKIP", "1")
    assert _os_rule.validate(root) == 0


# --- apply -------------------------------------------------------------------


def test_apply_creates_missing_subdirs(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path, with_openspec_dir=True)
    rc = _os_rule.apply(dry_run=False, cwd=root)
    assert rc == 0
    assert (root / "openspec" / "changes").is_dir()
    assert (root / "openspec" / "specs").is_dir()


def test_apply_creates_openspec_dir_when_referenced_only_in_agents(tmp_path: Path) -> None:
    # No openspec/ dir at all — apply must create it AND both subdirs.
    root = _make_consumer(tmp_path, agents_mentions_openspec=True)
    rc = _os_rule.apply(dry_run=False, cwd=root)
    assert rc == 0
    assert (root / "openspec").is_dir()
    assert (root / "openspec" / "changes").is_dir()
    assert (root / "openspec" / "specs").is_dir()


def test_apply_dry_run_does_not_create(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path, with_openspec_dir=True)
    rc = _os_rule.apply(dry_run=True, cwd=root)
    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert not (root / "openspec" / "changes").exists()
    assert not (root / "openspec" / "specs").exists()


def test_apply_idempotent_on_converged_state(tmp_path: Path) -> None:
    root = _make_consumer(
        tmp_path,
        with_openspec_dir=True,
        with_changes=True,
        with_specs=True,
    )
    # First apply: no-op success.
    assert _os_rule.apply(dry_run=False, cwd=root) == 0
    # Second apply: still no-op success, no FS mutation.
    assert _os_rule.apply(dry_run=False, cwd=root) == 0


def test_apply_refuses_when_path_type_drift(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path, with_openspec_dir=True)
    (root / "openspec" / "changes").write_text("not a dir", encoding="utf-8")
    rc = _os_rule.apply(dry_run=False, cwd=root)
    assert rc == 2
    err = capsys.readouterr().err
    assert "refuse" in err
    assert "not a directory" in err


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _os_rule.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
