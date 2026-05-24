"""Tests for scripts.caveman.stats — session-token aggregation + extrapolation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.caveman import stats

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_slugify_project_path_windows() -> None:
    assert stats._slugify_project_path(Path("c:/Projects/ai-playbook")) == "c--Projects-ai-playbook"


def test_slugify_project_path_unix_like() -> None:
    # Forward-slash-only path (no colon)
    assert stats._slugify_project_path(Path("/home/me/proj")) == "-home-me-proj"


def test_extrapolated_savings_zero_when_no_output() -> None:
    assert stats.extrapolated_savings(0) == 0
    assert stats.extrapolated_savings(-1) == 0


def test_extrapolated_savings_math() -> None:
    # SAVINGS_RATE = 0.65 → multiplier ≈ 1.857
    out = stats.extrapolated_savings(100)
    # 100 * 0.65 / 0.35 = 185
    assert out == 185


def test_short_count_formats() -> None:
    assert stats._short_count(500) == "500"
    assert stats._short_count(1500) == "1.5k"
    assert stats._short_count(12_400) == "12.4k"
    assert stats._short_count(2_500_000) == "2.5M"


def test_statusline_suffix_includes_pickaxe() -> None:
    assert stats.statusline_suffix(12_400) == "⛏ 12.4k"


def test_estimated_cost_usd_math() -> None:
    # 1M input @ $3 + 1M output @ $15 = $18
    cost = stats.estimated_cost_usd(1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_write_statusline_suffix_creates_file(tmp_path: Path) -> None:
    target = stats.write_statusline_suffix(tmp_path, 12_400)
    assert target == tmp_path / ".ai-playbook" / ".caveman-statusline-suffix"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "⛏ 12.4k"


# ---------------------------------------------------------------------------
# session_logs_dir — env override
# ---------------------------------------------------------------------------


def test_session_logs_dir_honors_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    project = Path("c:/Projects/fake")
    d = stats.session_logs_dir(project)
    assert d == tmp_path / "projects" / "c--Projects-fake"


# ---------------------------------------------------------------------------
# iter_assistant_events + collect_stats with a fixture JSONL
# ---------------------------------------------------------------------------


def _write_session_log(dir_: Path, name: str, events: list[dict]) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{name}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return p


def _assistant_ev(*, ts: str, in_tok: int, out_tok: int, model: str = "claude-opus-4-7") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "fake-session",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 200,
            },
        },
    }


def test_iter_assistant_events_filters_by_type(tmp_path: Path) -> None:
    log = _write_session_log(tmp_path, "s1", [
        {"type": "user", "timestamp": "2026-05-01T00:00:00Z"},
        _assistant_ev(ts="2026-05-01T00:00:01Z", in_tok=5, out_tok=10),
        {"type": "queue-operation", "operation": "x", "timestamp": "2026-05-01T00:00:02Z", "sessionId": "x"},
    ])
    out = list(stats.iter_assistant_events(log))
    assert len(out) == 1
    assert out[0]["type"] == "assistant"


def test_iter_assistant_events_handles_bad_json(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    log.write_text(
        json.dumps(_assistant_ev(ts="2026-05-01T00:00:00Z", in_tok=1, out_tok=2)) + "\n"
        + "{bad json\n"
        + "\n"  # blank line
        + json.dumps(_assistant_ev(ts="2026-05-01T00:00:01Z", in_tok=3, out_tok=4)) + "\n",
        encoding="utf-8",
    )
    out = list(stats.iter_assistant_events(log))
    assert len(out) == 2  # bad-json line silently skipped


def test_collect_stats_aggregates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    project = tmp_path / "proj"
    log_dir = stats.session_logs_dir(project)

    _write_session_log(log_dir, "session1", [
        _assistant_ev(ts="2026-05-01T00:00:00Z", in_tok=100, out_tok=300),
        _assistant_ev(ts="2026-05-01T00:00:10Z", in_tok=50, out_tok=200, model="claude-haiku-4-5"),
    ])
    _write_session_log(log_dir, "session2", [
        _assistant_ev(ts="2026-05-02T00:00:00Z", in_tok=10, out_tok=20),
    ])

    s = stats.collect_stats(project)
    assert s.sessions == 2
    assert s.events == 3
    assert s.input_tokens == 160
    assert s.output_tokens == 520
    assert s.cache_creation_tokens == 300
    assert s.cache_read_tokens == 600
    assert s.first_event_at == "2026-05-01T00:00:00Z"
    assert s.last_event_at == "2026-05-02T00:00:00Z"
    assert s.models == {"claude-opus-4-7": 2, "claude-haiku-4-5": 1}


def test_collect_stats_with_since_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    project = tmp_path / "proj"
    log_dir = stats.session_logs_dir(project)
    _write_session_log(log_dir, "s", [
        _assistant_ev(ts="2026-05-01T00:00:00Z", in_tok=999, out_tok=999),  # before cutoff
        _assistant_ev(ts="2026-05-02T00:00:00Z", in_tok=10, out_tok=20),
    ])
    s = stats.collect_stats(project, since="2026-05-01T12:00:00Z")
    assert s.events == 1
    assert s.input_tokens == 10
    assert s.output_tokens == 20


def test_collect_stats_returns_empty_when_no_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    project = tmp_path / "proj"
    s = stats.collect_stats(project)
    assert s.sessions == 0
    assert s.events == 0
    assert s.input_tokens == 0


# ---------------------------------------------------------------------------
# render_report sanity
# ---------------------------------------------------------------------------


def test_render_report_contains_key_fields(tmp_path: Path) -> None:
    s = stats.SessionStats(
        sessions=3,
        events=10,
        input_tokens=1000,
        output_tokens=500,
        cache_creation_tokens=100,
        cache_read_tokens=200,
    )
    out = stats.render_report(s, project_root=tmp_path, since=None)
    assert "sessions:        3" in out
    assert "assistant turns: 10" in out
    assert "1,000" in out  # input tokens
    assert "500" in out    # output tokens
    assert "⛏" in out
    # 500 * 0.65 / 0.35 ≈ 928
    assert "928" in out or "927" in out
