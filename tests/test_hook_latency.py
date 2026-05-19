"""SLA test for scripts/hook_dispatcher.py (D10 — ≤50ms p50)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import hook_dispatcher as hd

_RULE_TEMPLATE = (
    "---\n"
    "schema: rule/v1\n"
    "slug: {name}\n"
    "description: x\n"
    "paired_hardrule: null\n"
    "activation: always\n"
    "status: enforced\n"
    "triggers:\n"
    "  - Edit\n"
    "  - Bash\n"
    "---\n# body\n"
)


@pytest.fixture()
def fake_rules(tmp_path: Path) -> list[hd.Rule]:
    docs = tmp_path / "docs" / "rules"
    docs.mkdir(parents=True)
    for name in ["alpha", "beta", "gamma", "delta", "epsilon"]:
        (docs / f"{name}.rule.md").write_text(
            _RULE_TEMPLATE.format(name=name),
            encoding="utf-8",
        )
    return hd.load_rules(tmp_path)


def test_load_rules_returns_list(fake_rules: list[hd.Rule]) -> None:
    assert len(fake_rules) == 5
    slugs = {r.slug for r in fake_rules}
    assert slugs == {"alpha", "beta", "gamma", "delta", "epsilon"}


def test_dispatch_matches_triggers(fake_rules: list[hd.Rule]) -> None:
    fired = hd.dispatch(fake_rules, "Edit", {})
    assert set(fired) == {"alpha", "beta", "gamma", "delta", "epsilon"}


def test_dispatch_filters_by_trigger(fake_rules: list[hd.Rule]) -> None:
    # All test rules declare Edit + Bash. So Write should fire none.
    fired = hd.dispatch(fake_rules, "Write", {})
    assert fired == []


def test_rule_without_triggers_fires_always(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "rules"
    docs.mkdir(parents=True)
    (docs / "any.rule.md").write_text(
        "---\n"
        "schema: rule/v1\n"
        "slug: any\n"
        "description: x\n"
        "paired_hardrule: null\n"
        "activation: always\n"
        "status: enforced\n"
        "---\n# body\n",
        encoding="utf-8",
    )
    rules = hd.load_rules(tmp_path)
    fired = hd.dispatch(rules, "WhateverTool", {})
    assert fired == ["any"]


def test_benchmark_returns_stats(fake_rules: list[hd.Rule]) -> None:
    stats = hd.benchmark(fake_rules, n=200)
    for key in ("p50_ms", "p95_ms", "p99_ms", "mean_ms", "max_ms"):
        assert key in stats
    assert stats["p50_ms"] >= 0


def test_p50_under_sla(fake_rules: list[hd.Rule]) -> None:
    """Hard SLA: p50 ≤ 50ms even on Windows."""
    stats = hd.benchmark(fake_rules, n=500)
    assert stats["p50_ms"] <= 50.0, f"p50={stats['p50_ms']} ms exceeds 50ms SLA"


def test_load_rules_handles_missing_directory(tmp_path: Path) -> None:
    # No docs/rules/ exists.
    rules = hd.load_rules(tmp_path)
    assert rules == []


def test_load_rules_ignores_invalid_frontmatter(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "rules"
    docs.mkdir(parents=True)
    (docs / "broken.rule.md").write_text("not a yaml frontmatter\n", encoding="utf-8")
    (docs / "ok.rule.md").write_text(
        "---\n"
        "schema: rule/v1\n"
        "slug: ok\n"
        "description: x\n"
        "paired_hardrule: null\n"
        "activation: always\n"
        "status: enforced\n"
        "---\n",
        encoding="utf-8",
    )
    rules = hd.load_rules(tmp_path)
    assert [r.slug for r in rules] == ["ok"]


def test_telemetry_emission_overhead_under_5ms_per_rule(
    fake_rules: list[hd.Rule], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slice 6 budget: telemetry emission ≤5ms per rule (well under 50ms SLA)."""
    import time

    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(tmp_path / "telemetry-state"))
    n = 50
    samples: list[float] = []
    event = {"llm": "claude-opus-4-7", "session_id": "test"}
    for _ in range(n):
        t0 = time.perf_counter_ns()
        hd.dispatch(fake_rules, "Edit", event, emit_telemetry=True)
        t1 = time.perf_counter_ns()
        # Per-call dispatch covers all 5 rules; per-rule budget is < 5ms.
        per_rule_ms = ((t1 - t0) / 1e6) / max(len(fake_rules), 1)
        samples.append(per_rule_ms)
    samples.sort()
    median = samples[len(samples) // 2]
    # File IO can be slow on Windows; allow a 5ms per-rule budget.
    assert median <= 5.0, f"per-rule telemetry overhead median={median:.2f}ms > 5ms"


def test_dispatch_emit_telemetry_false_skips_logging(
    fake_rules: list[hd.Rule], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "no-events"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    hd.dispatch(fake_rules, "Edit", {"llm": "x"}, emit_telemetry=False)
    assert not (state_dir / "rule-events.jsonl").exists()


def test_dispatch_emit_telemetry_writes_jsonl(
    fake_rules: list[hd.Rule], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "with-events"
    monkeypatch.setenv("AI_PLAYBOOK_STATE_DIR", str(state_dir))
    hd.dispatch(
        fake_rules,
        "Edit",
        {"llm": "claude-opus-4-7", "session_id": "abc"},
        emit_telemetry=True,
    )
    log = state_dir / "rule-events.jsonl"
    assert log.is_file()
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(fake_rules)
