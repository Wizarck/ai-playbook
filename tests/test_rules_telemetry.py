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


# ---------------------------------------------------------------------------
# rules-toggle short-circuit (Phase F)
# ---------------------------------------------------------------------------


def _fake_consumer(tmp_path: Path, toggle_state: dict | None = None) -> Path:
    """Build a tmp consumer with AGENTS.md and an optional rules-toggle.json."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "AGENTS.md").write_text("# fake\n", encoding="utf-8")
    if toggle_state is not None:
        toggle_path = consumer / ".ai-playbook" / "rules-toggle.json"
        toggle_path.parent.mkdir(parents=True, exist_ok=True)
        toggle_path.write_text(json.dumps(toggle_state), encoding="utf-8")
    return consumer


def test_cli_emit_short_circuits_when_rule_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If rules-toggle.json says enabled=false, cli_emit skips main_fn + emits warn."""
    consumer = _fake_consumer(tmp_path, toggle_state={
        "schema": "rules-toggle/v1",
        "rules": {
            "verdict-contract": {"enabled": False, "reason": "ten-chars test"},
        },
    })
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    monkeypatch.chdir(consumer)

    invocations: list[bool] = []
    def main_fn() -> int:
        invocations.append(True)
        return 1  # would normally block

    rc = _telemetry.cli_emit("verdict-contract", main_fn)
    assert rc == 0, "rule disabled → cli_emit must return 0 (pass-through)"
    assert invocations == [], "main_fn must NOT be called when the rule is disabled"

    events = json.loads((state_dir / "rule-events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert events["verdict"] == "warn"
    assert events["block_class"] == "rule_disabled"
    assert events["toggle_layer"] == "L1"
    assert events["slug"] == "verdict-contract"


def test_cli_emit_runs_normally_when_rule_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A rule with no override (or enabled=true) runs main_fn as before."""
    consumer = _fake_consumer(tmp_path, toggle_state={
        "schema": "rules-toggle/v1",
        "rules": {},  # no overrides
    })
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    monkeypatch.chdir(consumer)

    invocations: list[bool] = []
    def main_fn() -> int:
        invocations.append(True)
        return 0

    rc = _telemetry.cli_emit("verdict-contract", main_fn)
    assert rc == 0
    assert invocations == [True]
    events = json.loads((state_dir / "rule-events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert events["verdict"] == "allow"
    assert events.get("block_class") != "rule_disabled"


def test_cli_emit_runs_normally_when_no_toggle_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No rules-toggle.json at all → cli_emit behaves exactly as before this feature."""
    consumer = _fake_consumer(tmp_path)  # no toggle state
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    monkeypatch.chdir(consumer)

    invocations: list[bool] = []
    def main_fn() -> int:
        invocations.append(True)
        return 1

    rc = _telemetry.cli_emit("verdict-contract", main_fn)
    assert rc == 1
    assert invocations == [True]
    events = json.loads((state_dir / "rule-events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert events["verdict"] == "block"
