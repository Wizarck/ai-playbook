"""Tests for scripts/cost_report.py (T14f)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import cost_report as cr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _recent_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _old_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _llm_event(
    *,
    ts: str,
    project: str = "acme",
    model: str = "claude-sonnet-4",
    task_class: str = "work",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_tokens: int = 200,
) -> dict:
    return {
        "ts": ts,
        "name": "llm.call",
        "attrs": {
            "project": project,
            "gen_ai.response.model": model,
            "ai_playbook.task_class": task_class,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.cache_read_input_tokens": cache_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_events_file_returns_0_with_empty_rollup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    rc = cr.main(["--events", str(events), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["rows"] == []


def test_missing_events_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cr.main(["--events", str(tmp_path / "missing.jsonl")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "events file not found" in err
    assert "FIX:" in err


def test_malformed_line_exits_1_with_line_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(_llm_event(ts=_recent_iso())) + "\n" + "{not json\n",
        encoding="utf-8",
    )
    rc = cr.main(["--events", str(events)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "line 2" in err


def test_aggregation_by_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            _llm_event(ts=_recent_iso(), project="acme", input_tokens=1000),
            _llm_event(ts=_recent_iso(), project="acme", input_tokens=2000),
            _llm_event(ts=_recent_iso(), project="beta", input_tokens=500),
        ],
    )
    rc = cr.main(["--events", str(events), "--by", "project", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    rows = {r["key"]: r for r in payload["rows"]}
    assert rows["acme"]["calls"] == 2
    assert rows["acme"]["input_tokens"] == 3000
    assert rows["beta"]["calls"] == 1


def test_aggregation_by_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            _llm_event(ts=_recent_iso(), model="opus-4-7"),
            _llm_event(ts=_recent_iso(), model="opus-4-7"),
            _llm_event(ts=_recent_iso(), model="sonnet-4-6"),
        ],
    )
    rc = cr.main(["--events", str(events), "--by", "model", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    keys = {r["key"] for r in payload["rows"]}
    assert keys == {"opus-4-7", "sonnet-4-6"}


def test_since_filter_drops_old_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            _llm_event(ts=_recent_iso(), project="acme"),
            _llm_event(ts=_old_iso(200), project="acme"),
        ],
    )
    rc = cr.main([
        "--events", str(events),
        "--since", (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat(),
        "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"][0]["calls"] == 1


def test_cache_hit_pct_is_calculated(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            _llm_event(ts=_recent_iso(), input_tokens=1000, cache_tokens=250),
        ],
    )
    # Exercise aggregation directly to assert on the Aggregate value.
    raw = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line]
    rows = cr.aggregate(raw, by="project", since=None, pricing=cr.PricingCatalog())
    assert rows[0].cache_hit_pct() == pytest.approx(25.0)


def test_json_output_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(events, [_llm_event(ts=_recent_iso())])
    rc = cr.main(["--events", str(events), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) >= {"by", "period", "since", "pricing_loaded", "rows"}
    row = payload["rows"][0]
    assert set(row.keys()) >= {
        "key",
        "calls",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_hit_pct",
        "estimated_cost_usd",
    }


def test_skips_non_llm_events(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            {"ts": _recent_iso(), "name": "qa.verdict", "attrs": {"severity": "S1"}},
            _llm_event(ts=_recent_iso()),
        ],
    )
    raw = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line]
    rows = cr.aggregate(raw, by="project", since=None, pricing=cr.PricingCatalog())
    assert len(rows) == 1
    assert rows[0].calls == 1


def test_pricing_yaml_applied_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            _llm_event(
                ts=_recent_iso(),
                model="sonnet-4-6",
                input_tokens=1000,
                output_tokens=500,
                cache_tokens=0,
            ),
        ],
    )
    pricing = tmp_path / "pricing.yaml"
    pricing.write_text(
        "models:\n"
        "  sonnet-4-6:\n"
        "    input_per_1k: 0.003\n"
        "    output_per_1k: 0.015\n"
        "    cache_read_per_1k: 0.0003\n",
        encoding="utf-8",
    )
    rc = cr.main([
        "--events", str(events),
        "--pricing", str(pricing),
        "--by", "model",
        "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pricing_loaded"] is True
    row = payload["rows"][0]
    # 1 * 0.003 + 0.5 * 0.015 = 0.003 + 0.0075 = 0.0105
    assert row["estimated_cost_usd"] == pytest.approx(0.0105, abs=1e-4)


def test_missing_attrs_dont_crash(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(
        events,
        [
            {"ts": _recent_iso(), "name": "llm.call", "attrs": {}},
            {"ts": _recent_iso(), "name": "llm.call"},  # no attrs at all
        ],
    )
    raw = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line]
    rows = cr.aggregate(raw, by="project", since=None, pricing=cr.PricingCatalog())
    # first event qualifies because name contains llm.call, second has no attrs
    # dict so key resolution yields "unknown" for the first and skips the second
    assert sum(r.calls for r in rows) >= 1


def test_accepts_alt_attr_names() -> None:
    """gen_ai.usage.input_tokens is the canonical key, but plain input_tokens works too."""
    events = [
        {
            "ts": _recent_iso(),
            "name": "llm.call",
            "attrs": {
                "project": "acme",
                "input_tokens": 500,
                "output_tokens": 250,
                "cache_read_tokens": 50,
            },
        }
    ]
    rows = cr.aggregate(events, by="project", since=None, pricing=cr.PricingCatalog())
    assert rows[0].input_tokens == 500
    assert rows[0].output_tokens == 250
    assert rows[0].cache_read_tokens == 50


def test_text_table_renders_note_when_pricing_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = tmp_path / "events.jsonl"
    _write_events(events, [_llm_event(ts=_recent_iso())])
    rc = cr.main([
        "--events", str(events),
        "--pricing", str(tmp_path / "does-not-exist.yaml"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "pricing catalog not configured" in out


def test_invalid_since_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    rc = cr.main(["--events", str(events), "--since", "not-a-date"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "invalid --since" in err
