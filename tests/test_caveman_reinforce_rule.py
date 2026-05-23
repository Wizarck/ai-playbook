"""Tests for scripts.rules.caveman-reinforce.rule.py — per-turn reinforcement hook."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


# The script has hyphens in its filename, so import via importlib.
HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "rules"
    / "caveman-reinforce.rule.py"
)


def _load_hook():
    spec = importlib.util.spec_from_file_location("caveman_reinforce_hook", HOOK_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load_hook()


def _make_project(tmp_path: Path, toggle_state: dict | None = None) -> Path:
    (tmp_path / "AGENTS.md").write_text("# project\n", encoding="utf-8")
    if toggle_state is not None:
        d = tmp_path / ".ai-playbook"
        d.mkdir()
        (d / "caveman.json").write_text(
            json.dumps(toggle_state), encoding="utf-8"
        )
    return tmp_path


# ---------------------------------------------------------------------------
# Silent paths — must emit nothing AND exit 0
# ---------------------------------------------------------------------------


def test_silent_when_no_project_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # tmp_path has no AGENTS.md, no .ai-playbook/. Walk up may find a real
    # project on this machine; we only assert: hook never raises.
    rc = hook.main(cwd=tmp_path)
    assert rc == 0


def test_silent_when_toggle_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _make_project(tmp_path)
    rc = hook.main(cwd=project)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_silent_when_enabled_false(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _make_project(
        tmp_path,
        {
            "schema": "caveman-toggle/v1",
            "enabled": False,
            "mode": "full",
            "components": {
                "response_style": False,
                "compress_docs": False,
                "subagents_cavecrew": False,
                "commit_caveman": False,
                "review_caveman": False,
                "mcp_shrink": False,
            },
            "applied_at": "2026-05-23T00:00:00Z",
        },
    )
    rc = hook.main(cwd=project)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_silent_when_response_style_false(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _make_project(
        tmp_path,
        {
            "schema": "caveman-toggle/v1",
            "enabled": True,
            "mode": "full",
            "components": {
                "response_style": False,
                "compress_docs": True,  # other component on, but not response_style
                "subagents_cavecrew": False,
                "commit_caveman": False,
                "review_caveman": False,
                "mcp_shrink": True,
            },
            "applied_at": "2026-05-23T00:00:00Z",
        },
    )
    rc = hook.main(cwd=project)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_silent_when_toggle_malformed_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _make_project(tmp_path)
    (project / ".ai-playbook").mkdir(exist_ok=True)
    (project / ".ai-playbook" / "caveman.json").write_text("not json {{", encoding="utf-8")
    rc = hook.main(cwd=project)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_silent_when_mode_unknown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _make_project(
        tmp_path,
        {
            "schema": "caveman-toggle/v1",
            "enabled": True,
            "mode": "telegraphic",  # invalid
            "components": {
                "response_style": True,
                "compress_docs": False,
                "subagents_cavecrew": False,
                "commit_caveman": False,
                "review_caveman": False,
                "mcp_shrink": False,
            },
            "applied_at": "2026-05-23T00:00:00Z",
        },
    )
    rc = hook.main(cwd=project)
    assert rc == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Active path — emit one paragraph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["lite", "full", "ultra"])
def test_nudge_emitted_when_active(tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str) -> None:
    project = _make_project(
        tmp_path,
        {
            "schema": "caveman-toggle/v1",
            "enabled": True,
            "mode": mode,
            "components": {
                "response_style": True,
                "compress_docs": False,
                "subagents_cavecrew": False,
                "commit_caveman": False,
                "review_caveman": False,
                "mcp_shrink": False,
            },
            "applied_at": "2026-05-23T00:00:00Z",
        },
    )
    rc = hook.main(cwd=project)
    assert rc == 0
    out = capsys.readouterr().out
    assert f"intensity: {mode}" in out
    assert "Drop articles" in out
    assert "Auto-clarity exceptions" in out
    # Single paragraph (one line + trailing newline from print).
    assert out.count("\n") == 1


# ---------------------------------------------------------------------------
# compose_nudge unit
# ---------------------------------------------------------------------------


def test_compose_nudge_full() -> None:
    out = hook.compose_nudge("full")
    assert "intensity: full" in out
    assert len(out) < 400  # keep under ~50 tokens budget
