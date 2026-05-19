"""Privacy invariants for scripts/telemetry/ (Slice 6, v0.18.2).

These tests are the safety net for the telemetry pipeline. They MUST pass
on every CI run; a regression here is a hard release blocker.

Coverage:
- No file paths in any emitted event.
- No diff content in any emitted event.
- No raw user messages in any emitted event.
- session_id is hashed (8 hex chars; the raw id never appears in the file).
- pricing.yaml load + cost computation correctness (regression).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.telemetry import rule_event_logger as rel
from scripts.telemetry.anonymize import hash_session_id, scrub_event
from scripts.telemetry.report import load_pricing

SESSION_ID_RAW = "session-abc-123-DO-NOT-LEAK"


def test_session_id_hash_is_8_hex_chars() -> None:
    h = hash_session_id(SESSION_ID_RAW)
    assert re.fullmatch(r"[0-9a-f]{8}", h), f"hash shape wrong: {h!r}"


def test_session_id_hash_one_way_no_leak_in_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rel.log_event(
        slug="output-completeness",
        llm="claude-opus-4-7",
        verdict="allow",
        latency_ms=5.0,
        session_id=SESSION_ID_RAW,
    )
    payload = (tmp_path / rel.EVENTS_FILENAME).read_text(encoding="utf-8")
    assert SESSION_ID_RAW not in payload, "raw session_id leaked into JSONL"
    assert "session_id_hash" in payload


def test_scrub_event_strips_file_paths() -> None:
    out = scrub_event(
        {
            "slug": "x",
            "file_path": "/secret/foo.py",
            "path": "/another/secret",
            "directory": "/dir/secret",
        }
    )
    assert "file_path" not in out
    assert "path" not in out
    assert "directory" not in out
    assert out["slug"] == "x"


def test_scrub_event_strips_diff_content_and_messages() -> None:
    out = scrub_event(
        {
            "slug": "x",
            "diff": "+secret diff line",
            "content": "raw content",
            "body": "raw body",
            "message": "user said X",
            "user_message": "leak me",
            "tool_input": "secret args",
        }
    )
    for forbidden in ("diff", "content", "body", "message", "user_message", "tool_input"):
        assert forbidden not in out
    assert out["slug"] == "x"


def test_log_event_with_extra_pii_keys_scrubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rel.log_event(
        slug="verdict-contract",
        llm="claude-opus-4-7",
        verdict="allow",
        latency_ms=2.0,
        session_id="sid",
        extra={
            "file_path": "/secret/leak.py",
            "diff": "+leak",
            "message": "user message leak",
        },
    )
    payload = (tmp_path / rel.EVENTS_FILENAME).read_text(encoding="utf-8")
    assert "/secret/leak.py" not in payload
    assert "+leak" not in payload
    assert "user message leak" not in payload


def test_pricing_load_and_compute_known_row() -> None:
    pricing = load_pricing(Path(__file__).resolve().parent.parent / "configs" / "pricing.yaml")
    assert pricing.loaded
    # claude-opus-4-7 is in the catalog. Verify the math is byte-exact.
    cost = pricing.cost_for(
        model="claude-opus-4-7",
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=1000,
    )
    # 1.0 * 0.015 + 1.0 * 0.075 + 1.0 * 0.0015 = 0.0915
    assert cost is not None
    assert abs(cost - 0.0915) < 1e-9


def test_hash_session_id_deterministic() -> None:
    assert hash_session_id("same-input") == hash_session_id("same-input")
    assert hash_session_id("foo") != hash_session_id("bar")


def test_empty_session_id_returns_zero_hash() -> None:
    assert hash_session_id("") == "00000000"


def test_log_event_is_failsafe_when_state_dir_unwritable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Point to a state dir we cannot create — logger must NOT raise.
    nonexistent = tmp_path / "does-not-exist-and-cannot-be-created" / "deep" / "tree"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(nonexistent))
    result = rel.log_event(
        slug="any",
        llm="x",
        verdict="allow",
        latency_ms=1.0,
        session_id="s",
    )
    # On Windows, mkdir(parents=True) generally succeeds; we still verify it
    # never raises and either returns a path or None.
    assert result is None or isinstance(result, Path)


def test_event_schema_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rel.log_event(
        slug="apply-skill-enforcement",
        llm="claude-opus-4-7",
        verdict="block",
        latency_ms=3.5,
        session_id="s",
        trigger="PreToolUse:Edit",
        self_check=True,
    )
    line = (tmp_path / rel.EVENTS_FILENAME).read_text(encoding="utf-8").strip()
    event = json.loads(line)
    for required in (
        "schema",
        "timestamp",
        "slug",
        "llm",
        "verdict",
        "latency_ms",
        "session_id_hash",
        "trigger",
        "self_check",
    ):
        assert required in event, f"missing required field {required}"
    assert event["schema"] == "rule-event/v1"
    assert event["verdict"] == "block"
    assert event["self_check"] is True
