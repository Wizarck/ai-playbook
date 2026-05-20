"""Tests for scripts/rules/dispatcher-gemini.rule.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_dg_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "dispatcher-gemini.rule.py",
)
assert SPEC and SPEC.loader
_dg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_dg)


CANONICAL = (
    "# GEMINI.md — Gemini CLI dispatcher\n\n"
    "Pointer to [AGENTS.md](AGENTS.md).\n"
)


def _make_consumer(tmp_path: Path, *, with_agents: bool = True, with_gemini_dir: bool = True) -> Path:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if with_gemini_dir:
        (tmp_path / ".gemini").mkdir()
    return tmp_path


# --- validate ------------------------------------------------------------------

def test_validate_ok_when_gemini_md_canonical(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    (root / "GEMINI.md").write_text(CANONICAL, encoding="utf-8")
    assert _dg.validate(root) == 0


def test_validate_drift_when_gemini_md_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    rc = _dg.validate(root)
    assert rc == 1
    assert "GEMINI.md missing" in capsys.readouterr().err


def test_validate_drift_when_agents_not_referenced(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / "GEMINI.md").write_text("# GEMINI\n\nSome other content.\n", encoding="utf-8")
    rc = _dg.validate(root)
    assert rc == 1
    assert "does not reference AGENTS.md" in capsys.readouterr().err


def test_validate_drift_when_too_long(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    body = "# GEMINI.md\n\nAGENTS.md\n\n" + "\n".join(f"line {i}" for i in range(50))
    (root / "GEMINI.md").write_text(body, encoding="utf-8")
    rc = _dg.validate(root)
    assert rc == 1
    assert "exceeds" in capsys.readouterr().err


def test_validate_not_applicable_when_no_gemini_in_use(tmp_path: Path) -> None:
    # Consumer has AGENTS.md but no .gemini/, no mcp-servers.yaml, no GEMINI.md.
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    assert _dg.validate(tmp_path) == 0


def test_validate_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    # No AGENTS.md anywhere up from tmp_path.
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _dg.validate(nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Broken state: no consumer root, but skip flag bypasses everything.
    monkeypatch.setenv("AIPLAYBOOK_DISPATCHER_GEMINI_SKIP", "1")
    assert _dg.validate(tmp_path) == 0


def test_gemini_in_use_detects_mcp_yaml(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (tmp_path / "mcp-servers.yaml").write_text("servers:\n  gemini-foo: {}\n", encoding="utf-8")
    assert _dg._gemini_in_use(tmp_path) is True


def test_gemini_in_use_false_when_unrelated(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    assert _dg._gemini_in_use(tmp_path) is False


# --- apply ---------------------------------------------------------------------

def test_apply_writes_canonical_when_missing(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _dg.apply(dry_run=False, cwd=root)
    assert rc == 0
    written = (root / "GEMINI.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in written
    assert written.startswith("# GEMINI.md")


def test_apply_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    rc = _dg.apply(dry_run=True, cwd=root)
    assert rc == 0
    assert not (root / "GEMINI.md").exists()


def test_apply_idempotent_when_already_canonical(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    # First write through apply (establishes the canonical).
    _dg.apply(dry_run=False, cwd=root)
    # Second invocation = no-op.
    rc = _dg.apply(dry_run=False, cwd=root)
    assert rc == 0


def test_apply_refuses_overwrite_of_custom_content(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / "GEMINI.md").write_text("# Custom\n\nMy hand-tuned content with AGENTS.md ref.\n", encoding="utf-8")
    rc = _dg.apply(dry_run=False, cwd=root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "refuse" in err
    # Original content preserved.
    assert "Custom" in (root / "GEMINI.md").read_text(encoding="utf-8")


def test_apply_fatal_when_no_consumer_root(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    rc = _dg.apply(dry_run=False, cwd=nested)
    assert rc == 2
    assert "no consumer root" in capsys.readouterr().err
