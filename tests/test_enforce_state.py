"""Tests for scripts._enforce_state — opt-out state file reader."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import _enforce_state


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Defaults: missing file → empty set
# ---------------------------------------------------------------------------


def test_disabled_skills_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _enforce_state.disabled_skills(tmp_path) == set()


def test_disabled_mcps_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _enforce_state.disabled_mcps(tmp_path) == set()


# ---------------------------------------------------------------------------
# Happy path: well-formed v1 state file
# ---------------------------------------------------------------------------


def test_disabled_skills_reads_v1_state(tmp_path: Path) -> None:
    _write(
        _enforce_state.skills_state_path(tmp_path),
        {"schema": "skills-enforce/v1", "disabled": ["bmad-tea", "bmad-create-prd"]},
    )
    assert _enforce_state.disabled_skills(tmp_path) == {"bmad-tea", "bmad-create-prd"}


def test_disabled_mcps_reads_v1_state(tmp_path: Path) -> None:
    _write(
        _enforce_state.mcps_state_path(tmp_path),
        {"schema": "mcps-enforce/v1", "disabled": ["guardrails-mcp"]},
    )
    assert _enforce_state.disabled_mcps(tmp_path) == {"guardrails-mcp"}


def test_empty_disabled_list_reads_as_empty_set(tmp_path: Path) -> None:
    _write(
        _enforce_state.skills_state_path(tmp_path),
        {"schema": "skills-enforce/v1", "disabled": []},
    )
    assert _enforce_state.disabled_skills(tmp_path) == set()


# ---------------------------------------------------------------------------
# Tolerance: malformed / wrong-schema / non-string entries
# ---------------------------------------------------------------------------


def test_malformed_json_returns_empty(tmp_path: Path) -> None:
    p = _enforce_state.skills_state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {{", encoding="utf-8")
    assert _enforce_state.disabled_skills(tmp_path) == set()


def test_wrong_schema_returns_empty(tmp_path: Path) -> None:
    _write(
        _enforce_state.skills_state_path(tmp_path),
        {"schema": "something-else/v1", "disabled": ["bmad-tea"]},
    )
    assert _enforce_state.disabled_skills(tmp_path) == set()


def test_non_list_disabled_returns_empty(tmp_path: Path) -> None:
    _write(
        _enforce_state.skills_state_path(tmp_path),
        {"schema": "skills-enforce/v1", "disabled": "not-a-list"},
    )
    assert _enforce_state.disabled_skills(tmp_path) == set()


def test_non_string_entries_are_dropped(tmp_path: Path) -> None:
    _write(
        _enforce_state.mcps_state_path(tmp_path),
        {
            "schema": "mcps-enforce/v1",
            "disabled": ["good-id", 42, None, "another-good-id", {"bad": "obj"}],
        },
    )
    assert _enforce_state.disabled_mcps(tmp_path) == {"good-id", "another-good-id"}


def test_skills_and_mcps_isolated(tmp_path: Path) -> None:
    """Writing only the skills state must NOT leak into mcps reads."""
    _write(
        _enforce_state.skills_state_path(tmp_path),
        {"schema": "skills-enforce/v1", "disabled": ["bmad-tea"]},
    )
    assert _enforce_state.disabled_skills(tmp_path) == {"bmad-tea"}
    assert _enforce_state.disabled_mcps(tmp_path) == set()
