"""Unit tests for scripts/log_event.py.

These tests MUST pass without `opentelemetry` or `langfuse` installed — the
JSONL writer is dependency-free.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import log_event


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_writes_jsonl_line(tmp_path: Path) -> None:
    events = tmp_path / "sub" / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "qa.verdict",
            "--attrs", '{"severity":"S1","iter":1}',
            "--events-file", str(events),
        ]
    )
    assert rc == 0
    rows = _read_events(events)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "qa.verdict"
    assert row["attrs"] == {"severity": "S1", "iter": 1}
    assert "ts" in row
    # Dir auto-creation:
    assert events.parent.exists()


def test_appends_multiple_events(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    for i in range(3):
        rc = log_event.main(
            [
                "--name", f"evt.{i}",
                "--attrs", json.dumps({"i": i}),
                "--events-file", str(events),
            ]
        )
        assert rc == 0
    rows = _read_events(events)
    assert [r["name"] for r in rows] == ["evt.0", "evt.1", "evt.2"]
    assert [r["attrs"]["i"] for r in rows] == [0, 1, 2]


def test_malformed_attrs_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events = tmp_path / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "qa.verdict",
            "--attrs", "{not json",
            "--events-file", str(events),
        ]
    )
    assert rc == 1
    assert not events.exists()
    err = capsys.readouterr().err
    assert "malformed" in err.lower() or "json" in err.lower()


def test_attrs_must_be_object_not_array(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "qa.verdict",
            "--attrs", '[1,2,3]',
            "--events-file", str(events),
        ]
    )
    assert rc == 1


def test_trace_id_is_propagated(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    tid = "0196f34a8c7e7b2f9d013e8a9b4c2f11"
    rc = log_event.main(
        [
            "--name", "router.fallback",
            "--attrs", '{"depth":2}',
            "--trace-id", tid,
            "--events-file", str(events),
        ]
    )
    assert rc == 0
    rows = _read_events(events)
    assert rows[0]["trace_id"] == tid


def test_missing_name_via_cli_returns_2() -> None:
    """Argparse raises SystemExit(2) when --name is missing — the playbook
    convention treats that as a CLI usage error (exit code 2)."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.log_event", "--attrs", "{}"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 2


def test_pretty_prints_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events = tmp_path / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "qa.verdict",
            "--attrs", '{"severity":"S2"}',
            "--events-file", str(events),
            "--pretty",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Pretty output should be indented JSON containing the event name.
    assert "qa.verdict" in out
    assert "  " in out  # indentation from json.dumps(indent=2)


def test_events_dir_is_autocreated(tmp_path: Path) -> None:
    events = tmp_path / "a" / "b" / "c" / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "deep.event",
            "--attrs", "{}",
            "--events-file", str(events),
        ]
    )
    assert rc == 0
    assert events.exists()
    assert events.parent.is_dir()


def test_unicode_roundtrip(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    rc = log_event.main(
        [
            "--name", "verdict.emoji",
            "--attrs", json.dumps({"verdict": "✅ APPROVED", "note": "café"}),
            "--events-file", str(events),
        ]
    )
    assert rc == 0
    rows = _read_events(events)
    assert rows[0]["attrs"]["verdict"] == "✅ APPROVED"
    assert rows[0]["attrs"]["note"] == "café"
