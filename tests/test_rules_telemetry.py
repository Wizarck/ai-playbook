"""Tests for scripts/rules/_telemetry.py — the CLI telemetry wrapper used by
every `scripts/rules/<slug>.rule.py` script.

Coverage:
- verdict_from_rc maps 0/1/>=2 to allow/block/warn
- cli_emit invokes main_fn with argv and returns its rc unchanged
- cli_emit logs a rule-event/v1 row to .ai-playbook-state/rule-events.jsonl
- cli_emit is fail-safe: telemetry failure does not alter the rc
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rules import _telemetry


def test_verdict_from_rc_zero_is_allow() -> None:
    assert _telemetry.verdict_from_rc(0) == "allow"


def test_verdict_from_rc_one_is_block() -> None:
    assert _telemetry.verdict_from_rc(1) == "block"


def test_verdict_from_rc_two_is_warn() -> None:
    assert _telemetry.verdict_from_rc(2) == "warn"


def test_verdict_from_rc_high_is_warn() -> None:
    assert _telemetry.verdict_from_rc(99) == "warn"


def test_cli_emit_returns_rc_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "state"))
    rc = _telemetry.cli_emit("update-playbook", lambda: 0)
    assert rc == 0
    rc = _telemetry.cli_emit("update-playbook", lambda: 1)
    assert rc == 1
    rc = _telemetry.cli_emit("update-playbook", lambda: 2)
    assert rc == 2


def test_cli_emit_writes_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    monkeypatch.setenv("AI_PLAYBOOK_LLM", "claude-test")
    monkeypatch.setenv("AI_PLAYBOOK_HOOK_TRIGGER", "PreToolUse:Edit")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-abc-123")
    rc = _telemetry.cli_emit("verdict-contract", lambda: 1)
    assert rc == 1
    events_file = state_dir / "rule-events.jsonl"
    assert events_file.is_file()
    row = json.loads(events_file.read_text(encoding="utf-8").splitlines()[-1])
    assert row["schema"] == "rule-event/v2"
    assert row["slug"] == "verdict-contract"
    assert row["llm"] == "claude-test"
    assert row["verdict"] == "block"
    assert row["trigger"] == "PreToolUse:Edit"
    # session_id_hash is the 8-char prefix of sha256(session-abc-123)
    assert len(row["session_id_hash"]) == 8
    assert row["self_check"] is False


def test_cli_emit_fails_safe_when_logger_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If the telemetry logger raises, the rule's rc must still propagate."""
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "state"))

    import scripts.telemetry.rule_event_logger as logger_mod

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("simulated logger failure")

    monkeypatch.setattr(logger_mod, "log_event", _boom)
    # Despite the logger blowing up, cli_emit must still return rc=42.
    rc = _telemetry.cli_emit("update-playbook", lambda: 42)
    assert rc == 42


def test_cli_emit_accepts_argv_for_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "state"))
    captured: list[list[str] | None] = []

    def fake_main(argv=None):
        captured.append(argv)
        return 0

    rc = _telemetry.cli_emit("update-playbook", fake_main, argv=["validate", "--quiet"])
    assert rc == 0
    assert captured == [["validate", "--quiet"]]


def test_cli_emit_calls_main_with_no_args_when_argv_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "state"))
    called = []

    def fake_main():  # no argv parameter at all
        called.append("yes")
        return 0

    rc = _telemetry.cli_emit("update-playbook", fake_main)
    assert rc == 0
    assert called == ["yes"]


def test_ensure_utf8_streams_calls_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_ensure_utf8_streams` calls reconfigure(encoding='utf-8', errors='replace')
    on every stream that exposes the method."""
    calls: list[tuple[str, dict]] = []

    class _FakeStream:
        def __init__(self, name: str) -> None:
            self._name = name

        def reconfigure(self, **kwargs):  # noqa: ANN003
            calls.append((self._name, kwargs))

    fake_out = _FakeStream("stdout")
    fake_err = _FakeStream("stderr")
    monkeypatch.setattr(_telemetry.sys, "stdout", fake_out)
    monkeypatch.setattr(_telemetry.sys, "stderr", fake_err)
    _telemetry._ensure_utf8_streams()
    assert ("stdout", {"encoding": "utf-8", "errors": "replace"}) in calls
    assert ("stderr", {"encoding": "utf-8", "errors": "replace"}) in calls


def test_ensure_utf8_streams_skips_stream_without_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streams without a `reconfigure` attribute (e.g. pytest capsys's stream)
    must be tolerated silently."""

    class _NoReconfigure:
        pass

    monkeypatch.setattr(_telemetry.sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(_telemetry.sys, "stderr", _NoReconfigure())
    # Must not raise.
    _telemetry._ensure_utf8_streams()


def test_ensure_utf8_streams_swallows_reconfigure_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        def reconfigure(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("simulated reconfigure failure")

    monkeypatch.setattr(_telemetry.sys, "stdout", _Boom())
    monkeypatch.setattr(_telemetry.sys, "stderr", _Boom())
    _telemetry._ensure_utf8_streams()  # must not raise


def test_cli_emit_invokes_ensure_utf8_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "state"))
    called = []
    monkeypatch.setattr(_telemetry, "_ensure_utf8_streams", lambda: called.append(True))
    _telemetry.cli_emit("update-playbook", lambda: 0)
    assert called == [True]
