"""Tests for scripts/rules/confirm-before-termination.rule.py.

Loads the hyphenated rule module by path (the dispatcher does the same) and
exercises the PreToolUse veto + the break-glass override.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "rules" / "confirm-before-termination.rule.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("confirm_before_termination_rule", RULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rule = _load()


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)


# --- blocks -----------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "kill 1234",
    "kill -9 4321",
    "pkill -f gtm",
    "docker stop web",
    "docker-compose down",
    "systemctl stop nginx",
    "pm2 delete all",
])
def test_blocks_bash_termination_verbs(cmd: str) -> None:
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert v.blocked, f"expected block on: {cmd!r}"


@pytest.mark.parametrize("tool", ["TaskStop", "KillShell", "BashOutputKill"])
def test_blocks_harness_stop_tools(tool: str) -> None:
    v = rule.pretooluse({"tool_name": tool, "tool_input": {}})
    assert v.blocked, f"expected block on tool: {tool}"


# --- allows -----------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "ls -la && git status",
    "python scripts/run.py",
    "git commit -m 'add feature'",
])
def test_allows_non_termination_bash(cmd: str) -> None:
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert not v.blocked, f"unexpected block on: {cmd!r}"


def test_allows_edit_event() -> None:
    v = rule.pretooluse({"tool_name": "Edit", "tool_input": {"file_path": "x", "new_string": "y"}})
    assert not v.blocked


# --- break-glass override ---------------------------------------------------

def test_override_allows_bash_kill(monkeypatch) -> None:
    monkeypatch.setenv(rule.OVERRIDE_ENV, "user said yes: stop the stuck run")
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": "kill 1234"}})
    assert not v.blocked


def test_override_allows_taskstop(monkeypatch) -> None:
    monkeypatch.setenv(rule.OVERRIDE_ENV, "user said yes")
    v = rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}})
    assert not v.blocked


# --- CLI validate is a no-op ------------------------------------------------

def test_validate_is_noop() -> None:
    assert rule.validate() == 0
