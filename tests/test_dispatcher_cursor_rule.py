"""Tests for scripts/rules/dispatcher-cursor.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_dc_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "dispatcher-cursor.rule.py",
)
assert SPEC and SPEC.loader
_dc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_dc)


CANONICAL = (
    "---\n"
    "description: AGENTS.md is the canonical dispatcher\n"
    "alwaysApply: true\n"
    "---\n\n"
    "# Cursor dispatcher pointer\n\n"
    "Pointer to [AGENTS.md](../../AGENTS.md).\n"
)


def _make_consumer(tmp_path: Path, *, with_agents: bool = True, with_cursor_dir: bool = True) -> Path:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if with_cursor_dir:
        (tmp_path / ".cursor").mkdir()
    return tmp_path


def _write_pointer(root: Path, text: str) -> Path:
    pointer = root / ".cursor" / "rules" / "00-AGENTS.mdc"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(text, encoding="utf-8")
    return pointer


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_pointer_canonical(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    _write_pointer(root, CANONICAL)
    assert _dc.validate(root) == 0


def test_validate_drift_when_pointer_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    rc = _dc.validate(root)
    assert rc == 1
    assert "missing" in capsys.readouterr().err


def test_validate_drift_when_agents_not_referenced(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    _write_pointer(
        root,
        "---\ndescription: x\nalwaysApply: true\n---\n\n# Pointer\n\nSome other content.\n",
    )
    rc = _dc.validate(root)
    assert rc == 1
    assert "does not reference AGENTS.md" in capsys.readouterr().err


def test_validate_drift_when_too_long(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    body = (
        "---\ndescription: x\nalwaysApply: true\n---\n\n# Pointer\n\nAGENTS.md\n\n"
        + "\n".join(f"line {i}" for i in range(50))
    )
    _write_pointer(root, body)
    rc = _dc.validate(root)
    assert rc == 1
    assert "exceeds" in capsys.readouterr().err


def test_validate_not_applicable_when_no_cursor_in_use(tmp_path: Path) -> None:
    # Consumer has AGENTS.md but no .cursor/ directory.
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    assert _dc.validate(tmp_path) == 0


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _dc.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_DISPATCHER_CURSOR_SKIP", "1")
    assert _dc.validate(tmp_path) == 0


def test_cursor_in_use_detects_cursor_dir(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (tmp_path / ".cursor").mkdir()
    assert _dc._cursor_in_use(tmp_path) is True


def test_cursor_in_use_false_when_unrelated(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    assert _dc._cursor_in_use(tmp_path) is False


# --- apply ---------------------------------------------------------------------

def test_apply_writes_canonical_when_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _dc.apply(dry_run=False, cwd=root)
    assert rc == 0
    pointer = root / ".cursor" / "rules" / "00-AGENTS.mdc"
    assert pointer.is_file()
    written = pointer.read_text(encoding="utf-8")
    assert "AGENTS.md" in written
    assert "alwaysApply: true" in written


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _dc.apply(dry_run=True, cwd=root)
    assert rc == 0
    assert not (root / ".cursor" / "rules" / "00-AGENTS.mdc").exists()


def test_apply_idempotent_when_already_canonical(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    _dc.apply(dry_run=False, cwd=root)
    rc = _dc.apply(dry_run=False, cwd=root)
    assert rc == 0


def test_apply_refuses_overwrite_of_custom_content(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    _write_pointer(
        root,
        "---\ndescription: custom\nalwaysApply: true\n---\n\n# Custom AGENTS.md pointer\n\nHand-tuned.\n",
    )
    rc = _dc.apply(dry_run=False, cwd=root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "refuse" in err
    assert "Custom" in (root / ".cursor" / "rules" / "00-AGENTS.mdc").read_text(encoding="utf-8")


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _dc.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
