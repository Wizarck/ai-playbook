"""Tests for scripts/rules/mcp-render.rule.py."""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "_mr_rule",
    Path(__file__).resolve().parent.parent / "scripts" / "rules" / "mcp-render.rule.py",
)
assert SPEC and SPEC.loader
_mr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mr)


def _make_consumer(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    return tmp_path


def _set_mtime(p: Path, ts: float) -> None:
    os.utime(p, (ts, ts))


# --- _is_stale -----------------------------------------------------------------

def test_is_stale_when_render_missing(tmp_path: Path) -> None:
    ssot = tmp_path / "mcp-servers.yaml"
    ssot.write_text("servers: {}\n", encoding="utf-8")
    render = tmp_path / ".mcp.json"
    assert _mr._is_stale(ssot, render) is True


def test_is_stale_when_ssot_newer(tmp_path: Path) -> None:
    ssot = tmp_path / "mcp-servers.yaml"
    render = tmp_path / ".mcp.json"
    ssot.write_text("servers: {}\n", encoding="utf-8")
    render.write_text("{}", encoding="utf-8")
    _set_mtime(render, time.time() - 100)
    _set_mtime(ssot, time.time())
    assert _mr._is_stale(ssot, render) is True


def test_is_fresh_when_render_newer(tmp_path: Path) -> None:
    ssot = tmp_path / "mcp-servers.yaml"
    render = tmp_path / ".mcp.json"
    ssot.write_text("servers: {}\n", encoding="utf-8")
    render.write_text("{}", encoding="utf-8")
    _set_mtime(ssot, time.time() - 100)
    _set_mtime(render, time.time())
    assert _mr._is_stale(ssot, render) is False


# --- _uses_gemini --------------------------------------------------------------

def test_uses_gemini_via_dir(tmp_path: Path) -> None:
    (tmp_path / ".gemini").mkdir()
    assert _mr._uses_gemini(tmp_path) is True


def test_uses_gemini_via_gemini_md(tmp_path: Path) -> None:
    (tmp_path / "GEMINI.md").write_text("# G\n", encoding="utf-8")
    assert _mr._uses_gemini(tmp_path) is True


def test_uses_gemini_false_when_neither(tmp_path: Path) -> None:
    assert _mr._uses_gemini(tmp_path) is False


# --- validate ------------------------------------------------------------------

def test_validate_not_applicable_when_no_ssot(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    assert _mr.validate(root) == 0


def test_validate_not_applicable_when_no_consumer_root(tmp_path: Path) -> None:
    # No AGENTS.md anywhere → not applicable.
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    assert _mr.validate(nested) == 0


def test_validate_drift_when_render_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / "mcp-servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    rc = _mr.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert ".mcp.json" in err


def test_validate_ok_when_render_fresh(tmp_path: Path) -> None:
    root = _make_consumer(tmp_path)
    ssot = root / "mcp-servers.yaml"
    render = root / ".mcp.json"
    ssot.write_text("servers: {}\n", encoding="utf-8")
    render.write_text("{}", encoding="utf-8")
    _set_mtime(ssot, time.time() - 100)
    _set_mtime(render, time.time())
    assert _mr.validate(root) == 0


def test_validate_drift_when_render_stale(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    ssot = root / "mcp-servers.yaml"
    render = root / ".mcp.json"
    render.write_text("{}", encoding="utf-8")
    ssot.write_text("servers: {}\n", encoding="utf-8")
    _set_mtime(render, time.time() - 100)
    _set_mtime(ssot, time.time())
    rc = _mr.validate(root)
    assert rc == 1
    assert "stale" in capsys.readouterr().err


def test_validate_drift_when_gemini_render_missing(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    (root / ".gemini").mkdir()
    ssot = root / "mcp-servers.yaml"
    claude = root / ".mcp.json"
    ssot.write_text("servers: {}\n", encoding="utf-8")
    claude.write_text("{}", encoding="utf-8")
    _set_mtime(ssot, time.time() - 100)
    _set_mtime(claude, time.time())
    # Claude fresh; Gemini render absent → still drift.
    rc = _mr.validate(root)
    assert rc == 1
    err = capsys.readouterr().err
    assert "settings.json" in err


def test_validate_skip_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_MCP_RENDER_SKIP", "1")
    root = _make_consumer(tmp_path)
    (root / "mcp-servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    # Drift state, but skip wins.
    assert _mr.validate(root) == 0


# --- apply ---------------------------------------------------------------------

def test_apply_not_applicable_when_no_ssot(tmp_path: Path, capsys) -> None:
    root = _make_consumer(tmp_path)
    rc = _mr.apply(dry_run=False, cwd=root)
    assert rc == 0
    assert "not applicable" in capsys.readouterr().out


def test_apply_not_applicable_when_no_consumer(tmp_path: Path, capsys) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    rc = _mr.apply(dry_run=False, cwd=nested)
    assert rc == 0
    assert "not applicable" in capsys.readouterr().out


# Note: We do NOT test the actual subprocess invocation of scripts.mcp.render
# here — that would require the playbook tree's mcp-servers-base template
# resolvable from tmp_path, which is its own integration concern. The render
# script has its own tests at tests/test_mcp_render.py.
