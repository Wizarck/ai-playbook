"""End-to-end tests for scripts/telemetry/ (Slice 6, v0.18.2).

Covers:
- log_event() builds valid v1 events and appends one JSONL line per call.
- report.py CLI returns exit 0 on empty event log.
- report.py JSON output has all eight sections.
- Cost computation per-rule / per-session / spend-over-time.
- Retirement window check (absorbed lifecycle_check.py).
- OpenSpec staleness check (absorbed deprecation_watcher.py / lifecycle_check.py).
- Budget breach check (absorbed budget_disable_check.py).
- Simulate model migration (absorbed simulate_model_migration.py).
- Break-glass / escape-hatch counting.
- Memory decay stub.
- Window filtering.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.telemetry import report as rpt
from scripts.telemetry import rule_event_logger as rel

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_YAML = REPO_ROOT / "configs" / "pricing.yaml"
RETIREMENT_YAML = REPO_ROOT / "configs" / "anthropic-retirement-list.yaml"


def _write_event(path: Path, **overrides) -> None:
    base = {
        "schema": "rule-event/v1",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slug": "verdict-contract",
        "llm": "claude-opus-4-7",
        "model": "claude-opus-4-7",
        "verdict": "allow",
        "latency_ms": 5.0,
        "session_id_hash": "abcd1234",
        "trigger": "PreToolUse:Edit",
        "self_check": False,
    }
    base.update(overrides)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(base) + "\n")


# ---------------------------------------------------------------------------
# rule_event_logger
# ---------------------------------------------------------------------------


def test_log_event_creates_file_and_appends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    p1 = rel.log_event(slug="a", llm="x", verdict="allow", latency_ms=1.0, session_id="s")
    p2 = rel.log_event(slug="b", llm="x", verdict="block", latency_ms=2.0, session_id="s")
    assert p1 is not None and p2 is not None
    assert p1 == p2
    lines = p1.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["slug"] == "a"
    assert json.loads(lines[1])["verdict"] == "block"


def test_log_event_optional_token_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rel.log_event(
        slug="x",
        llm="claude-opus-4-7",
        verdict="allow",
        latency_ms=1.0,
        session_id="s",
        tokens_in=100,
        tokens_out=50,
        cache_read_tokens=10,
    )
    event = json.loads((tmp_path / rel.EVENTS_FILENAME).read_text(encoding="utf-8").strip())
    assert event["tokens_in"] == 100
    assert event["tokens_out"] == 50
    assert event["cache_read_tokens"] == 10


def test_log_event_omits_optional_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rel.log_event(slug="x", llm="x", verdict="allow", latency_ms=1.0, session_id="s")
    event = json.loads((tmp_path / rel.EVENTS_FILENAME).read_text(encoding="utf-8").strip())
    assert "tokens_in" not in event
    assert "tokens_out" not in event


def test_rotate_if_stale_archives_old_log(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    log.write_text("old\n", encoding="utf-8")
    # Backdate mtime by 10 days.
    import os
    import time
    backdate = time.time() - 10 * 86400
    os.utime(log, (backdate, backdate))
    arc = rel.rotate_if_stale(tmp_path, retain_days=7)
    assert arc is not None
    assert arc.is_file()
    assert log.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# report.py — CLI
# ---------------------------------------------------------------------------


def test_report_monthly_exit_0_on_empty_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rc = rpt.main(["monthly", "--state-dir", str(tmp_path), "--openspec-dir", str(tmp_path / "no-openspec")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## 1. Obey rate" in out
    assert "## 8. Memory decay" in out


def test_report_weekly_json_has_all_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rc = rpt.main(["weekly", "--json", "--state-dir", str(tmp_path), "--openspec-dir", str(tmp_path / "x")])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    for key in (
        "window_days",
        "obey_rate",
        "cost_per_rule",
        "cost_per_session",
        "spend_over_time",
        "retirements",
        "openspec_staleness",
        "break_glass_usage",
        "memory_decay",
    ):
        assert key in data


def test_report_custom_requires_window_days(capsys) -> None:
    rc = rpt.main(["custom"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "window-days" in err.lower()


def test_report_custom_with_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path))
    rc = rpt.main(
        [
            "custom",
            "--window-days",
            "14",
            "--json",
            "--state-dir",
            str(tmp_path),
            "--openspec-dir",
            str(tmp_path / "x"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["window_days"] == 14


# ---------------------------------------------------------------------------
# Compute helpers
# ---------------------------------------------------------------------------


def test_compute_obey_rate(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    _write_event(log, slug="r1", verdict="allow")
    _write_event(log, slug="r1", verdict="allow")
    _write_event(log, slug="r1", verdict="block")
    _write_event(log, slug="r2", verdict="warn")
    events = rpt.load_events(log)
    rows = rpt.compute_obey_rate(events)
    by_slug = {(r["slug"], r["llm"]): r for r in rows}
    assert by_slug[("r1", "claude-opus-4-7")]["obey_rate"] == round(2 / 3, 4)
    assert by_slug[("r2", "claude-opus-4-7")]["obey_rate"] == 0.0  # 0 allow / 1 total


def test_compute_cost_per_rule_with_pricing(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    _write_event(log, slug="r1", tokens_in=1000, tokens_out=1000, cache_read_tokens=0)
    pricing = rpt.load_pricing(PRICING_YAML)
    rows = rpt.compute_cost_per_rule(rpt.load_events(log), pricing)
    assert len(rows) == 1
    # claude-opus-4-7: 1*0.015 + 1*0.075 = 0.09
    assert abs(rows[0]["cost_usd"] - 0.09) < 1e-6


def test_compute_cost_per_session_aggregates(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    _write_event(log, session_id_hash="aaaa1111", tokens_in=1000, tokens_out=500)
    _write_event(log, session_id_hash="aaaa1111", tokens_in=2000, tokens_out=1000)
    _write_event(log, session_id_hash="bbbb2222", tokens_in=500, tokens_out=100)
    pricing = rpt.load_pricing(PRICING_YAML)
    rows = rpt.compute_cost_per_session(rpt.load_events(log), pricing)
    sessions = {r["session_id_hash"] for r in rows}
    assert sessions == {"aaaa1111", "bbbb2222"}
    a = next(r for r in rows if r["session_id_hash"] == "aaaa1111")
    assert a["events"] == 2


def test_check_retirement_window_empty_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "ret.yaml"
    yaml_path.write_text("retirements: []\n", encoding="utf-8")
    result = rpt.check_retirement_window(yaml_path)
    assert result == []


def test_check_retirement_window_imminent_entry(tmp_path: Path) -> None:
    soon = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
    yaml_path = tmp_path / "ret.yaml"
    yaml_path.write_text(
        f"retirements:\n  - model_id: foo\n    provider: anthropic\n    retirement_date: {soon}\n    successor: bar\n",
        encoding="utf-8",
    )
    result = rpt.check_retirement_window(yaml_path)
    assert len(result) == 1
    assert result[0]["model_id"] == "foo"
    assert result[0]["days_remaining"] in (29, 30)


def test_check_openspec_staleness_no_dir() -> None:
    result = rpt.check_openspec_staleness(Path("/no/such/dir"))
    assert result == []


def test_check_budget_breach_no_flag(tmp_path: Path) -> None:
    result = rpt.check_budget_breach(["anthropic"], flag_dir=str(tmp_path))
    assert result == [{"provider": "anthropic", "disabled": False}]


def test_check_budget_breach_with_flag(tmp_path: Path) -> None:
    (tmp_path / "budget-disabled-anthropic.flag").write_text("", encoding="utf-8")
    result = rpt.check_budget_breach(["anthropic"], flag_dir=str(tmp_path))
    assert result == [{"provider": "anthropic", "disabled": True}]


def test_simulate_model_migration_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_MIGRATION_REQUESTED", "claude-haiku-4-5:claude-haiku-5-0")
    result = rpt.simulate_model_migration()
    assert result["status"] == "simulated"
    assert result["from"] == "claude-haiku-4-5"
    assert result["to"] == "claude-haiku-5-0"


def test_simulate_model_migration_no_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_MIGRATION_REQUESTED", raising=False)
    yaml_path = tmp_path / "ret.yaml"
    yaml_path.write_text("retirements: []\n", encoding="utf-8")
    result = rpt.simulate_model_migration(retirement_yaml_path=yaml_path)
    assert result["status"] == "no-trigger"


def test_compute_break_glass_usage(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    _write_event(log, escape_hatch="[no-doc-impact]")
    _write_event(log, escape_hatch="[no-doc-impact]")
    _write_event(log, escape_hatch="AIPLAYBOOK_X_SKIP")
    _write_event(log)  # no escape_hatch
    rows = rpt.compute_break_glass_usage(rpt.load_events(log))
    by_eh = {r["escape_hatch"]: r["count"] for r in rows}
    assert by_eh["[no-doc-impact]"] == 2
    assert by_eh["AIPLAYBOOK_X_SKIP"] == 1


def test_check_memory_decay_stub() -> None:
    result = rpt.check_memory_decay()
    assert result["status"] == "deferred-to-slice-7"


def test_filter_by_window_drops_old_events(tmp_path: Path) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    old_ts = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_event(log, slug="old", timestamp=old_ts)
    _write_event(log, slug="new", timestamp=new_ts)
    events = rpt.load_events(log)
    since = datetime.now(UTC) - timedelta(days=30)
    in_window = rpt.filter_by_window(events, since=since)
    assert {ev["slug"] for ev in in_window} == {"new"}


def test_load_events_skips_malformed_lines(tmp_path: Path, capsys) -> None:
    log = tmp_path / rel.EVENTS_FILENAME
    log.write_text(
        '{"valid": true}\n'
        "this is not json\n"
        '{"slug": "x"}\n',
        encoding="utf-8",
    )
    events = rpt.load_events(log)
    assert len(events) == 2


def test_compute_block_breakdown_groups_by_class_tool_pattern() -> None:
    events = [
        {"verdict": "block", "slug": "apply-skill-enforcement", "block_class": "apply_phase_bypass",
         "block_tool": "Bash", "bash_pattern_kind": "sed-i"},
        {"verdict": "block", "slug": "apply-skill-enforcement", "block_class": "apply_phase_bypass",
         "block_tool": "Bash", "bash_pattern_kind": "sed-i"},
        {"verdict": "block", "slug": "apply-skill-enforcement", "block_class": "apply_phase_bypass",
         "block_tool": "Edit", "bash_pattern_kind": ""},
        {"verdict": "allow", "slug": "apply-skill-enforcement", "block_class": "none"},
    ]
    rows = rpt.compute_block_breakdown(events)
    # 2 buckets: (Bash, sed-i) count=2 and (Edit, "") count=1.
    assert len(rows) == 2
    top = rows[0]
    assert top["block_tool"] == "Bash"
    assert top["bash_pattern_kind"] == "sed-i"
    assert top["count"] == 2


def test_compute_block_breakdown_ignores_non_blocks_and_none_class() -> None:
    events = [
        {"verdict": "allow", "slug": "x", "block_class": "none"},
        {"verdict": "warn",  "slug": "x", "block_class": "helper_missing"},
        {"verdict": "block", "slug": "x", "block_class": ""},
        {"verdict": "block", "slug": "x"},  # no block_class field
    ]
    assert rpt.compute_block_breakdown(events) == []


def test_compute_top_blocked_paths_orders_by_count() -> None:
    events = [
        {"verdict": "block", "slug": "rule-a", "target_rel": "backend/foo.py"},
        {"verdict": "block", "slug": "rule-a", "target_rel": "backend/foo.py"},
        {"verdict": "block", "slug": "rule-a", "target_rel": "backend/bar.py"},
        {"verdict": "allow", "slug": "rule-a", "target_rel": "backend/baz.py"},  # ignored
        {"verdict": "block", "slug": "rule-b", "target_rel": "frontend/x.tsx"},
    ]
    rows = rpt.compute_top_blocked_paths(events, top_n=10)
    assert rows[0] == {"slug": "rule-a", "target_rel": "backend/foo.py", "count": 2}
    # Only block events count; baz.py absent.
    assert all(r["target_rel"] != "backend/baz.py" for r in rows)
    # Total 3 distinct rows.
    assert len(rows) == 3


def test_compute_top_blocked_paths_respects_top_n() -> None:
    events = [{"verdict": "block", "slug": "rule-a", "target_rel": f"p{i}.py"} for i in range(20)]
    rows = rpt.compute_top_blocked_paths(events, top_n=5)
    assert len(rows) == 5


def test_compute_override_ratio_per_slug() -> None:
    events = [
        {"slug": "rule-a"},
        {"slug": "rule-a", "escape_hatch": "X"},
        {"slug": "rule-a"},
        {"slug": "rule-b"},
        {"slug": "rule-b", "escape_hatch": "Y"},
        {"slug": "rule-b", "escape_hatch": "Y"},
    ]
    rows = rpt.compute_override_ratio(events, flag_threshold=0.5)
    # Sorted by slug.
    a, b = rows
    assert a["slug"] == "rule-a"
    assert a["total"] == 3 and a["overrides"] == 1
    assert abs(a["override_ratio"] - 0.3333) < 0.001
    assert a["over_threshold"] is False
    assert b["slug"] == "rule-b"
    assert b["total"] == 3 and b["overrides"] == 2
    assert b["over_threshold"] is True  # 0.6667 > 0.5


def test_compute_override_ratio_flag_at_5_percent() -> None:
    events = [{"slug": "x"} for _ in range(99)]
    events.append({"slug": "x", "escape_hatch": "Z"})  # 1/100 = 1%
    rows = rpt.compute_override_ratio(events)
    assert rows[0]["over_threshold"] is False
    # Add 4 more overrides → 5/100 = 5%; threshold is strictly >0.05 by default.
    events.extend({"slug": "x", "escape_hatch": "Z"} for _ in range(4))
    rows = rpt.compute_override_ratio(events)
    # 5/104 = ~4.81% — still below 5%.
    assert rows[0]["over_threshold"] is False
    # 6 overrides → 6/105 = ~5.71%.
    events.append({"slug": "x", "escape_hatch": "Z"})
    rows = rpt.compute_override_ratio(events)
    assert rows[0]["over_threshold"] is True


def test_render_markdown_contains_v2_sections() -> None:
    """Sections 1.bis, 1.ter, 6.bis appear in the rendered markdown."""
    rpt_obj = rpt.build_report(window_days=1, state_dir=Path("/no/such/dir/__missing"))
    out = rpt.render_markdown(rpt_obj)
    assert "## 1.bis Block reasons breakdown" in out
    assert "## 1.ter Top blocked paths" in out
    assert "## 6.bis Override ratio (per slug)" in out


def test_render_markdown_contains_all_eight_sections(tmp_path: Path) -> None:
    report = rpt.build_report(
        window_days=30,
        state_dir=tmp_path,
        pricing_path=PRICING_YAML,
        retirement_path=tmp_path / "ret.yaml",  # missing — graceful
        openspec_dir=tmp_path / "openspec",
    )
    md = rpt.render_markdown(report)
    for n in range(1, 9):
        assert f"## {n}." in md
