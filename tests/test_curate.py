"""Tests for the curate pipeline (scripts/curate.py + scripts/_curate_validate.py).

The LLM call is injected via ``plan_provider`` so no test ever reaches a real
proxy. The deterministic guardrail / validation / apply paths are exercised in
full; only the model's plan is stubbed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import _curate_validate, curate

_PROSE = "\n".join(
    f"Substantive dispatcher paragraph line {i}, well over the pointer threshold."
    for i in range(15)
)


def _consumer_with_loose_claude(tmp_path: Path) -> tuple[Path, str]:
    c = tmp_path / "consumer"
    c.mkdir()
    (c / "AGENTS.md").write_text("# AGENTS\n\nSee docs.\n", encoding="utf-8")
    claude = "# CLAUDE.md\n\n## Architecture notes\n" + _PROSE + "\n"
    (c / "CLAUDE.md").write_text(claude, encoding="utf-8")
    return c, claude


def _plan_for(excerpt: str, *, dest="docs/architecture.md") -> dict:
    return {
        "schema": "curate-plan/v1",
        "moves": [{
            "source_rel_path": "CLAUDE.md",
            "source_excerpt": excerpt,
            "dest_rel_path": dest,
            "pointer": f"See [architecture]({dest}) for details.",
        }],
    }


# --- _curate_validate ------------------------------------------------------


def test_validate_accepts_a_clean_plan() -> None:
    sources = {"CLAUDE.md": "# C\n\n" + _PROSE + "\n"}
    v = _curate_validate.validate_plan(_plan_for(_PROSE), sources)
    assert v.ok, v.errors
    assert len(v.moves) == 1


def test_validate_rejects_fabricated_excerpt() -> None:
    sources = {"CLAUDE.md": "# C\n\nreal content here and more and more text\n"}
    v = _curate_validate.validate_plan(
        _plan_for("This text was invented by the model and is not in the file at all."),
        sources,
    )
    assert not v.ok
    assert any("fabrication" in e for e in v.errors)


def test_validate_rejects_path_traversal_and_absolute() -> None:
    sources = {"CLAUDE.md": "# C\n\n" + _PROSE + "\n"}
    for bad in ("../../etc/passwd.md", "/abs/leaf.md", "C:/win.md", "notdocs/x.md"):
        v = _curate_validate.validate_plan(_plan_for(_PROSE, dest=bad), sources)
        assert not v.ok, bad


def test_validate_accepts_canonical_agents_dest() -> None:
    sources = {"CLAUDE.md": "# C\n\n" + _PROSE + "\n"}
    plan = _plan_for(_PROSE, dest="AGENTS.md")
    plan["moves"][0]["pointer"] = "See [AGENTS.md](AGENTS.md)."
    v = _curate_validate.validate_plan(plan, sources)
    assert v.ok, v.errors


def test_validate_rejects_pointer_without_link() -> None:
    sources = {"CLAUDE.md": "# C\n\n" + _PROSE + "\n"}
    plan = _plan_for(_PROSE)
    plan["moves"][0]["pointer"] = "moved, no link here"
    v = _curate_validate.validate_plan(plan, sources)
    assert not v.ok


def test_validate_rejects_wrong_schema() -> None:
    v = _curate_validate.validate_plan({"schema": "nope", "moves": []}, {})
    assert not v.ok


# --- curate orchestration --------------------------------------------------


def test_curate_no_drift_is_noop(tmp_path: Path) -> None:
    c = tmp_path / "consumer"
    c.mkdir()
    (c / "AGENTS.md").write_text("# A\n\nSee [docs](docs/x.md).\n", encoding="utf-8")
    res = curate.curate(c, plan_provider=lambda f: {})
    assert res.rc == 0
    assert "nothing to curate" in res.detail


def test_curate_requires_consent(tmp_path: Path) -> None:
    c, _ = _consumer_with_loose_claude(tmp_path)
    res = curate.curate(c, plan_provider=lambda f: pytest.fail("LLM must not be called without consent/dry-run"))
    assert res.rc == 2
    assert "--yes" in res.detail


def test_curate_guardrail_aborts_on_secret(tmp_path: Path) -> None:
    c = tmp_path / "consumer"
    c.mkdir()
    (c / "AGENTS.md").write_text("# A\n", encoding="utf-8")
    tainted = "# CLAUDE\n\n## Notes\n" + _PROSE + "\nAWS key AKIAIOSFODNN7EXAMPLE here.\n"
    (c / "CLAUDE.md").write_text(tainted, encoding="utf-8")
    called = {"n": 0}

    def _provider(_f):
        called["n"] += 1
        return {}

    res = curate.curate(c, dry_run=True, plan_provider=_provider)
    assert res.rc == 2
    assert "guardrail" in res.detail
    assert called["n"] == 0  # tainted content never reaches the LLM


def test_curate_dry_run_previews_without_writing(tmp_path: Path) -> None:
    c, claude = _consumer_with_loose_claude(tmp_path)
    res = curate.curate(c, dry_run=True, plan_provider=lambda f: _plan_for(_PROSE))
    assert res.rc == 0
    assert "DRY-RUN curate plan" in res.detail
    # Nothing written.
    assert (c / "CLAUDE.md").read_text(encoding="utf-8") == claude
    assert not (c / "docs" / "architecture.md").exists()


def test_curate_apply_moves_prose_and_leaves_pointer(tmp_path: Path) -> None:
    c, _ = _consumer_with_loose_claude(tmp_path)
    res = curate.curate(c, consent=True, plan_provider=lambda f: _plan_for(_PROSE))
    assert res.rc == 0, res.detail
    assert res.moves_applied == 1
    claude_after = (c / "CLAUDE.md").read_text(encoding="utf-8")
    # Prose gone from the dispatcher; pointer left.
    assert "Substantive dispatcher paragraph line 7" not in claude_after
    assert "See [architecture](docs/architecture.md)" in claude_after
    # Prose landed in the leaf doc.
    leaf = (c / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "Substantive dispatcher paragraph line 7" in leaf
    # BASE snapshot captured (uninstall anchor).
    from scripts._backup_helper import base_record_for
    assert base_record_for(c, "CLAUDE.md") is not None


def test_curate_converges_second_run_is_noop(tmp_path: Path) -> None:
    c, _ = _consumer_with_loose_claude(tmp_path)
    curate.curate(c, consent=True, plan_provider=lambda f: _plan_for(_PROSE))
    # After the move, the dispatcher is pointer-shaped → no drift → no-op (D3).
    res2 = curate.curate(c, consent=True, plan_provider=lambda f: pytest.fail("should not call LLM"))
    assert res2.rc == 0
    assert "nothing to curate" in res2.detail


def test_curate_rejects_invalid_llm_plan(tmp_path: Path) -> None:
    c, _ = _consumer_with_loose_claude(tmp_path)
    res = curate.curate(c, consent=True, plan_provider=lambda f: {"schema": "curate-plan/v1", "moves": [
        {"source_rel_path": "CLAUDE.md", "source_excerpt": "FABRICATED unseen text " * 3,
         "dest_rel_path": "docs/x.md", "pointer": "See [x](docs/x.md)."}
    ]})
    assert res.rc == 1
    assert "rejected" in res.detail


# --- all-or-nothing apply ----------------------------------------------------


def test_curate_unwritable_destination_leaves_source_intact(tmp_path: Path) -> None:
    """Destination write fails → the prose must still be in the source."""
    c, claude = _consumer_with_loose_claude(tmp_path)
    (c / "docs" / "architecture.md").mkdir(parents=True)  # dest path is a directory
    res = curate.curate(c, consent=True, plan_provider=lambda f: _plan_for(_PROSE))
    assert res.rc == 1
    assert "rolled back" in res.detail
    assert (c / "CLAUDE.md").read_text(encoding="utf-8") == claude
    assert not list(c.rglob("*.curate-tmp"))


def test_curate_partial_failure_rolls_back_written_destinations(tmp_path: Path) -> None:
    c, claude = _consumer_with_loose_claude(tmp_path)
    agents = (c / "AGENTS.md").read_text(encoding="utf-8")
    lines = _PROSE.split("\n")
    first, second = "\n".join(lines[:8]), "\n".join(lines[8:])
    (c / "docs" / "architecture.md").mkdir(parents=True)
    plan = {"schema": "curate-plan/v1", "moves": [
        {"source_rel_path": "CLAUDE.md", "source_excerpt": first,
         "dest_rel_path": "docs/new-leaf.md", "pointer": "See [leaf](docs/new-leaf.md)."},
        {"source_rel_path": "CLAUDE.md", "source_excerpt": second,
         "dest_rel_path": "AGENTS.md", "pointer": "See [agents](AGENTS.md)."},
        {"source_rel_path": "CLAUDE.md", "source_excerpt": "## Architecture notes",
         "dest_rel_path": "docs/architecture.md", "pointer": "See [a](docs/architecture.md)."},
    ]}
    res = curate.curate(c, consent=True, plan_provider=lambda f: plan)
    assert res.rc == 1, res.detail
    assert (c / "CLAUDE.md").read_text(encoding="utf-8") == claude
    assert (c / "AGENTS.md").read_text(encoding="utf-8") == agents
    assert not (c / "docs" / "new-leaf.md").exists()


def test_curate_per_run_backup_holds_prose_added_after_install(tmp_path: Path) -> None:
    """BASE is taken once at install; the per-run snapshot must hold later prose."""
    from scripts._backup_helper import backup_base, read_index

    c, _ = _consumer_with_loose_claude(tmp_path)
    original = (c / "CLAUDE.md").read_text(encoding="utf-8")
    (c / "CLAUDE.md").write_text("# CLAUDE.md\n", encoding="utf-8")
    backup_base(c, c / "CLAUDE.md")  # install-time BASE, before the prose existed
    (c / "CLAUDE.md").write_text(original, encoding="utf-8")

    res = curate.curate(c, consent=True, plan_provider=lambda f: _plan_for(_PROSE))
    assert res.rc == 0, res.detail
    snaps = [
        (c / r.backup_rel_path).read_text(encoding="utf-8")
        for r in read_index(c) if r.rel_path == "CLAUDE.md" and r.session_id != "base"
    ]
    assert any("paragraph line 7" in s for s in snaps)
