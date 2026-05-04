"""Tests for the Phase 5 P5.6/P5.7 activation triggers + simulators.

Covers OpenSpec change `complete-ir-and-model-migration-specs`:

- `lifecycle_check.scan_paying_clients` — detects sla_signed within 30 days,
  ignores older / future-dated, ignores rows missing tier or signed.
- `lifecycle_check.scan_model_retirements` — detects retirements within
  90-day horizon; ignores far-future entries; sorts by days_remaining.
- Trigger-state idempotency — `select_new_*` returns only first-time hits;
  `record_trigger_state` accumulates.
- `simulate_incident_response.simulate` — happy path; broken runbook path;
  json output round-trip.
- `simulate_model_migration.derive_plan` — env var path; YAML path; both
  empty path returns None; verifier integration.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts import lifecycle_check as lc
from scripts import simulate_incident_response as sim_ir
from scripts import simulate_model_migration as sim_mm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def consumers_yaml(tmp_path: Path) -> Path:
    """A consumers.yaml exercising the four detector branches."""
    path = tmp_path / "consumers.yaml"
    path.write_text(
        """\
schema: ai-playbook/consumers/v1
version: 1
consumers:
  recent-paying:
    repo: org/recent-paying
    paying_tier: enterprise
    sla_signed: 2026-04-20    # 11 days ago — within window
  old-paying:
    repo: org/old-paying
    paying_tier: smb
    sla_signed: 2025-01-01    # > 30 days ago — out of window
  future-paying:
    repo: org/future-paying
    paying_tier: enterprise
    sla_signed: 2027-01-01    # future-dated — ignored
  no-tier:
    repo: org/no-tier
    sla_signed: 2026-04-20    # missing paying_tier — ignored
  no-signed:
    repo: org/no-signed
    paying_tier: enterprise   # missing sla_signed — ignored
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def retirement_yaml(tmp_path: Path) -> Path:
    """A retirement YAML exercising the three detector branches."""
    path = tmp_path / "retirement.yaml"
    path.write_text(
        """\
retirements:
  - model_id: claude-near
    provider: anthropic
    retirement_date: 2026-06-15    # 45 days out — within horizon
    successor: claude-near-next
    deprecation_url: https://example.com/near
  - model_id: claude-overdue
    provider: anthropic
    retirement_date: 2026-04-15    # past — overdue, still surfaced
    successor: claude-overdue-next
  - model_id: claude-far
    provider: anthropic
    retirement_date: 2027-06-15    # 410 days out — beyond 90d horizon
    successor: claude-far-next
retired: []
""",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# scan_paying_clients
# ---------------------------------------------------------------------------


def test_scan_paying_clients_returns_only_within_window(consumers_yaml: Path) -> None:
    findings = lc.scan_paying_clients(consumers_yaml, now=_NOW)
    assert [f.consumer_id for f in findings] == ["recent-paying"]
    assert findings[0].paying_tier == "enterprise"
    assert findings[0].sla_signed == date(2026, 4, 20)
    assert findings[0].days_since_signed == 11


def test_scan_paying_clients_missing_file_returns_empty(tmp_path: Path) -> None:
    findings = lc.scan_paying_clients(tmp_path / "absent.yaml", now=_NOW)
    assert findings == []


def test_scan_paying_clients_malformed_yaml_returns_empty(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("this is: not: valid: yaml: at all\n", encoding="utf-8")
    findings = lc.scan_paying_clients(bad, now=_NOW)
    # YAML loader is permissive; the assertion is "doesn't crash" and "no
    # `consumers:` block means no findings".
    assert findings == []


# ---------------------------------------------------------------------------
# scan_model_retirements
# ---------------------------------------------------------------------------


def test_scan_model_retirements_within_horizon(retirement_yaml: Path) -> None:
    findings = lc.scan_model_retirements(retirement_yaml, now=_NOW)
    ids = [f.model_id for f in findings]
    assert "claude-near" in ids
    assert "claude-overdue" in ids
    assert "claude-far" not in ids


def test_scan_model_retirements_sorted_by_days_remaining(retirement_yaml: Path) -> None:
    findings = lc.scan_model_retirements(retirement_yaml, now=_NOW)
    days = [f.days_remaining for f in findings]
    assert days == sorted(days)
    overdue = next(f for f in findings if f.model_id == "claude-overdue")
    assert overdue.days_remaining < 0


def test_scan_model_retirements_missing_file(tmp_path: Path) -> None:
    findings = lc.scan_model_retirements(tmp_path / "absent.yaml", now=_NOW)
    assert findings == []


# ---------------------------------------------------------------------------
# Trigger-state idempotency
# ---------------------------------------------------------------------------


def test_select_new_paying_clients_filters_out_already_seen() -> None:
    f1 = lc.PayingClientFinding("a", "enterprise", date(2026, 4, 20), 11)
    f2 = lc.PayingClientFinding("b", "smb", date(2026, 4, 25), 6)
    state: dict[str, object] = {"paying_clients": ["a"]}
    result = lc.select_new_paying_clients([f1, f2], state=state)
    assert [f.consumer_id for f in result] == ["b"]


def test_select_new_model_retirements_filters_out_already_seen() -> None:
    f1 = lc.ModelRetirementFinding("m1", "anthropic", date(2026, 6, 1), 31, "m2", "")
    f2 = lc.ModelRetirementFinding("m3", "anthropic", date(2026, 7, 1), 61, "m4", "")
    state: dict[str, object] = {"model_retirements": ["m1"]}
    result = lc.select_new_model_retirements([f1, f2], state=state)
    assert [f.model_id for f in result] == ["m3"]


def test_record_trigger_state_accumulates_ids() -> None:
    state: dict[str, object] = {"paying_clients": ["a"], "model_retirements": ["m1"]}
    pf = lc.PayingClientFinding("b", "enterprise", date(2026, 4, 20), 11)
    mf = lc.ModelRetirementFinding("m2", "anthropic", date(2026, 6, 1), 31, "m2-next", "")
    out = lc.record_trigger_state(state, paying=[pf], retirements=[mf])
    assert out["paying_clients"] == ["a", "b"]
    assert out["model_retirements"] == ["m1", "m2"]


def test_load_trigger_state_missing_returns_empty(tmp_path: Path) -> None:
    assert lc.load_trigger_state(tmp_path / "absent.json") == {}


def test_save_load_trigger_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "triggers.json"
    payload = {"paying_clients": ["a", "b"], "model_retirements": ["m1"]}
    lc.save_trigger_state(path, payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert lc.load_trigger_state(path) == payload


# ---------------------------------------------------------------------------
# build_report wiring (smoke — confirms detectors plug in cleanly)
# ---------------------------------------------------------------------------


def test_build_report_includes_trigger_findings(
    tmp_path: Path, consumers_yaml: Path, retirement_yaml: Path,
) -> None:
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    report = lc.build_report(
        consumer_root=consumer_root,
        month="2026-04",
        now=_NOW,
        migration_log=tmp_path / "absent-migration.log",
        consumers_yaml=consumers_yaml,
        retirement_yaml=retirement_yaml,
    )
    assert any(f.consumer_id == "recent-paying" for f in report.paying_clients)
    assert any(f.model_id == "claude-near" for f in report.model_retirements)


def test_render_markdown_emits_activation_triggers_section(
    tmp_path: Path, consumers_yaml: Path, retirement_yaml: Path,
) -> None:
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    report = lc.build_report(
        consumer_root=consumer_root,
        month="2026-04",
        now=_NOW,
        migration_log=tmp_path / "absent.log",
        consumers_yaml=consumers_yaml,
        retirement_yaml=retirement_yaml,
    )
    body = lc.render_markdown(report)
    assert "## Activation triggers" in body
    assert "first_paying_client_detected" in body
    assert "model_retirement_detected" in body
    assert "claude-near" in body


# ---------------------------------------------------------------------------
# simulate_incident_response
# ---------------------------------------------------------------------------


def test_simulate_incident_response_default_scenario_passes() -> None:
    result = sim_ir.simulate(sim_ir.SCENARIOS[3], now=_NOW)  # #4 OOM
    assert result.ok()
    assert result.scenario.id == 4
    assert result.runbook_resolves
    assert result.template_renders


def test_simulate_incident_response_broken_runbook_marked_not_ok(
    tmp_path: Path,
) -> None:
    # Synthetic playbook root: no runbooks/, no templates/
    fake_root = tmp_path / "fake-playbook"
    fake_root.mkdir()
    result = sim_ir.simulate(sim_ir.SCENARIOS[0], root=fake_root, now=_NOW)
    assert not result.ok()
    assert not result.runbook_resolves
    assert not result.template_renders


def test_simulate_incident_response_emits_incident_id_with_timestamp() -> None:
    result = sim_ir.simulate(sim_ir.SCENARIOS[0], now=_NOW)
    assert result.incident_id.startswith("INC-SIM-")
    # ISO-derived suffix matches the override
    assert "20260501" in result.incident_id


def test_simulate_incident_response_renders_post_mortem_no_missing_vars() -> None:
    result = sim_ir.simulate(sim_ir.SCENARIOS[0], now=_NOW)
    assert result.template_missing_vars == []


# ---------------------------------------------------------------------------
# simulate_model_migration
# ---------------------------------------------------------------------------


def test_derive_plan_from_env_var_overrides_yaml(tmp_path: Path) -> None:
    plan = sim_mm.derive_plan(
        env_var="claude-old:claude-new",
        retirement_yaml=tmp_path / "absent.yaml",
        now=_NOW,
    )
    assert plan is not None
    assert plan.from_model == "claude-old"
    assert plan.to_model == "claude-new"
    assert plan.source == "env"


def test_derive_plan_from_yaml_when_env_absent(retirement_yaml: Path) -> None:
    plan = sim_mm.derive_plan(env_var=None, retirement_yaml=retirement_yaml, now=_NOW)
    assert plan is not None
    # claude-overdue has the smallest (most negative) days_remaining → first.
    assert plan.from_model == "claude-overdue"
    assert plan.source == "retirement-list"


def test_derive_plan_returns_none_when_no_trigger(tmp_path: Path) -> None:
    plan = sim_mm.derive_plan(
        env_var=None, retirement_yaml=tmp_path / "absent.yaml", now=_NOW,
    )
    assert plan is None


def test_derive_plan_rejects_malformed_env_var(tmp_path: Path) -> None:
    plan = sim_mm.derive_plan(
        env_var="no-colon-here", retirement_yaml=tmp_path / "absent.yaml", now=_NOW,
    )
    assert plan is None


def test_simulate_model_migration_pr_body_includes_trigger_section(
    retirement_yaml: Path,
) -> None:
    result = sim_mm.simulate(env_var=None, retirement_yaml=retirement_yaml, now=_NOW)
    assert result is not None
    assert "## Trigger" in result.pr_body
    assert "## CI canary plan" in result.pr_body
    assert "## Rollback" in result.pr_body


def test_simulate_model_migration_skips_verifier_when_absent(tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-playbook"
    (fake_root / "configs").mkdir(parents=True)
    fake_root.joinpath("configs/anthropic-retirement-list.yaml").write_text(
        "retirements: []\n", encoding="utf-8"
    )
    result = sim_mm.simulate(
        env_var="claude-x:claude-y",
        retirement_yaml=fake_root / "configs" / "anthropic-retirement-list.yaml",
        root=fake_root,
        now=_NOW,
    )
    assert result is not None
    assert result.verifier_present is False
    assert "fall back to manual regex sweep" in result.pr_body
