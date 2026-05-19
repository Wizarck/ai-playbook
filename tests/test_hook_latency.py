"""SLA test for scripts/hook_dispatcher.py (D10 — ≤50ms p50)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from scripts import hook_dispatcher as hd


@pytest.fixture()
def fake_rules(tmp_path: Path) -> list[hd.Rule]:
    docs = tmp_path / "docs" / "rules"
    docs.mkdir(parents=True)
    for i, name in enumerate(["alpha", "beta", "gamma", "delta", "epsilon"]):
        (docs / f"{name}.rule.md").write_text(
            f"---\nschema: rule/v1\nslug: {name}\ndescription: x\npaired_hardrule: null\nactivation: always\nstatus: enforced\ntriggers:\n  - Edit\n  - Bash\n---\n# body\n",
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
        "---\nschema: rule/v1\nslug: any\ndescription: x\npaired_hardrule: null\nactivation: always\nstatus: enforced\n---\n# body\n",
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
        "---\nschema: rule/v1\nslug: ok\ndescription: x\npaired_hardrule: null\nactivation: always\nstatus: enforced\n---\n",
        encoding="utf-8",
    )
    rules = hd.load_rules(tmp_path)
    assert [r.slug for r in rules] == ["ok"]
