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


# --- the remedy must be performable from the gated tool ---------------------
#
# Measured 2026-08-17: an agent holding the user's explicit yes wrote
# `export OVERRIDE=...; Stop-Process ...` and was blocked AGAIN -- the hook
# evaluates before the shell runs, so an inline export can never reach the
# hook's os.environ. That is the impossible-remedy shape of #166, inside the
# very rule built to demand confirmation.


def test_inline_override_allows_the_exact_command_that_was_blocked(monkeypatch) -> None:
    """The real command from the incident, with the reason inline."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    cmd = (
        f'{rule.OVERRIDE_ENV}=user-confirmed-kill-of-orphaned-pytest '
        'powershell -NoProfile -Command "Stop-Process -Id 77560 -Force"'
    )
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert not v.blocked


def test_inline_override_with_empty_reason_still_blocks(monkeypatch) -> None:
    """NEGATIVE CONTROL: the assignment alone is not a reason."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    cmd = f'{rule.OVERRIDE_ENV}= kill 1234'
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert v.blocked


def test_a_kill_without_any_override_still_blocks_and_names_the_inline_remedy(monkeypatch) -> None:
    """The refusal must teach the remedy that actually works."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    v = rule.pretooluse({"tool_name": "Bash", "tool_input": {"command": "pkill -f pytest"}})
    assert v.blocked
    assert "INLINE" in v.message
    assert "export" in v.message  # ...and says why export cannot work


def test_receipt_allows_exactly_one_stop(monkeypatch, tmp_path) -> None:
    """One confirmation, one stop -- the receipt is consumed on use."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)

    receipt.write_text("user said yes: stop the stuck waiter", encoding="utf-8")
    first = rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}})
    second = rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}})
    assert not first.blocked
    assert second.blocked, "the receipt authorised more than one stop"
    assert not receipt.exists()


def test_a_blank_receipt_does_not_authorise(monkeypatch, tmp_path) -> None:
    """NEGATIVE CONTROL: whitespace is not a reason."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_text("   \n", encoding="utf-8")
    v = rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}})
    assert v.blocked


def test_the_stop_refusal_names_the_receipt_path(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    v = rule.pretooluse({"tool_name": "KillShell", "tool_input": {}})
    assert v.blocked
    assert str(receipt) in v.message


# --- CLI validate is a no-op ------------------------------------------------

def test_validate_is_noop() -> None:
    assert rule.validate() == 0
