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
    # Compose v2 spelling — the hyphenated pattern above never matched it.
    "docker compose down",
    "docker compose down -v",
    "docker compose -p proj -f a.yml stop",
    "kubectl delete pod netprobe -n tenant",
    "kubectl delete -f manifest.yaml",
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


def test_an_undecodable_receipt_blocks_and_is_consumed(monkeypatch, tmp_path) -> None:
    """An undecodable receipt used to raise UnicodeDecodeError: the dispatcher
    failed open AND the file survived as a standing override."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_bytes(b"\xff\xfeu\x00s\x00e")  # UTF-16 BOM, truncated (odd length)
    v = rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}})
    assert v.blocked
    assert not receipt.exists(), "an unreadable receipt must still be single-use"


@pytest.mark.parametrize("raw", [
    "el usuario dijo sí \r\n".encode("cp850"),  # cmd `echo ... > <path>` (OEM code page)
    "el usuario dijo sí\r\n".encode("cp1252"),  # PS 5.1 `Set-Content` without -Encoding
    b"\x80\x81user said yes",
])
def test_a_legacy_code_page_receipt_authorises_exactly_one_stop(monkeypatch, tmp_path, raw) -> None:
    """Only blankness is judged: a non-ASCII reason written in the console's code
    page used to be refused again and again, with nothing saying why."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_bytes(raw)
    assert not rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked
    assert not receipt.exists()
    assert rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked


@pytest.mark.parametrize("raw", [
    b"\xff\xfe" + "user said yes\r\n".encode("utf-16-le"),  # PowerShell 5.1 `>`
    b"\xfe\xff" + "user said yes\r\n".encode("utf-16-be"),
    b"\xef\xbb\xbf" + b"user said yes\r\n",                  # Set-Content -Encoding utf8
])
def test_a_bom_marked_receipt_authorises_exactly_one_stop(monkeypatch, tmp_path, raw) -> None:
    """The documented `echo <reason> > <path>` must work from the shell the agent
    has. In Windows PowerShell 5.1 that writes UTF-16LE with a BOM."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_bytes(raw)
    assert not rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked
    assert not receipt.exists()
    assert rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked


@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbf",                                # UTF-8 BOM alone
    b"\xff\xfe" + " \r\n".encode("utf-16-le"),      # UTF-16 BOM + whitespace
    b"\xff\xfe\x00\x00",                            # UTF-32 BOM alone
])
def test_a_bom_with_no_reason_does_not_authorise(monkeypatch, tmp_path, raw) -> None:
    """NEGATIVE CONTROL: a BOM is not a reason."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_bytes(raw)
    assert rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked
    assert not receipt.exists()


def test_a_blank_receipt_is_consumed_too(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    receipt.write_text("   \n", encoding="utf-8")
    assert rule.pretooluse({"tool_name": "TaskStop", "tool_input": {}}).blocked
    assert not receipt.exists()


def test_the_stop_refusal_names_the_receipt_path(monkeypatch, tmp_path) -> None:
    """Quoted, with forward slashes: an unquoted `C:\\Users\\...` loses every
    backslash in Git Bash, so the receipt would land in a junk file in the cwd."""
    monkeypatch.delenv(rule.OVERRIDE_ENV, raising=False)
    receipt = tmp_path / "receipt"
    monkeypatch.setattr(rule, "_receipt_path", lambda: receipt)
    v = rule.pretooluse({"tool_name": "KillShell", "tool_input": {}})
    assert v.blocked
    assert f'> "{receipt.as_posix()}"' in v.message
    assert "\\" not in v.message


# --- CLI validate is a no-op ------------------------------------------------

def test_validate_is_noop() -> None:
    assert rule.validate() == 0
