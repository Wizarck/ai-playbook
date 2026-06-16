"""Tests for scripts.ponytail.toggle — state read/write + schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.ponytail import toggle

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_find_playbook_root_found() -> None:
    root = toggle.find_playbook_root()
    assert root is not None
    assert (root / "specs").is_dir()
    assert (root / "scripts").is_dir()
    assert (root / "schemas").is_dir()


def test_find_project_root_with_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# fake project\n", encoding="utf-8")
    found = toggle.find_project_root(tmp_path)
    assert found == tmp_path


def test_find_project_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# root\n", encoding="utf-8")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    found = toggle.find_project_root(nested)
    assert found == tmp_path


def test_find_project_root_returns_none_when_no_markers(tmp_path: Path) -> None:
    found = toggle.find_project_root(tmp_path)
    assert found is None


def test_find_project_root_skips_playbook_submodule(tmp_path: Path) -> None:
    """Regression for the ``.ai-playbook/.ai-playbook/`` nesting bug."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")
    submodule = consumer / ".ai-playbook"
    (submodule / "scripts").mkdir(parents=True)
    (submodule / "AGENTS.md").write_text("# playbook self\n", encoding="utf-8")

    assert toggle.find_project_root(submodule) == consumer
    assert toggle.find_project_root(submodule / "scripts") == consumer


# ---------------------------------------------------------------------------
# Default state shape
# ---------------------------------------------------------------------------


def test_default_state_shape() -> None:
    s = toggle.default_state()
    assert s["schema"] == "ponytail-toggle/v1"
    assert s["enabled"] is False
    assert s["mode"] == "full"
    assert set(s["components"].keys()) == {
        "code_style",
        "review_ponytail",
        "audit_ponytail",
        "debt_ponytail",
    }
    assert all(v is False for v in s["components"].values())
    from datetime import datetime
    datetime.fromisoformat(s["applied_at"])


def test_default_state_passes_schema() -> None:
    schema = toggle._load_schema()
    jsonschema.validate(toggle.default_state(), schema)


def test_components_constant_matches_schema() -> None:
    schema = toggle._load_schema()
    schema_keys = set(schema["properties"]["components"]["properties"].keys())
    assert set(toggle.COMPONENTS) == schema_keys


# ---------------------------------------------------------------------------
# read_state / write_state round-trip
# ---------------------------------------------------------------------------


def test_read_state_returns_default_when_missing(tmp_path: Path) -> None:
    state = toggle.read_state(tmp_path)
    assert state["enabled"] is False
    assert state["mode"] == "full"
    assert not toggle.state_path(tmp_path).is_file()


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["enabled"] = True
    s["mode"] = "ultra"
    s["components"]["code_style"] = True
    s["components"]["review_ponytail"] = True
    toggle.write_state(tmp_path, s)

    p = toggle.state_path(tmp_path)
    assert p.is_file()

    loaded = toggle.read_state(tmp_path)
    assert loaded["enabled"] is True
    assert loaded["mode"] == "ultra"
    assert loaded["components"]["code_style"] is True
    assert loaded["components"]["review_ponytail"] is True
    assert loaded["components"]["audit_ponytail"] is False


def test_write_state_creates_state_dir(tmp_path: Path) -> None:
    assert not (tmp_path / ".ai-playbook").exists()
    toggle.write_state(tmp_path, toggle.default_state())
    assert (tmp_path / ".ai-playbook").is_dir()
    assert toggle.state_path(tmp_path).is_file()


def test_write_state_atomic_no_temp_left_behind(tmp_path: Path) -> None:
    toggle.write_state(tmp_path, toggle.default_state())
    leftovers = list((tmp_path / ".ai-playbook").glob(".ponytail-*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# Schema validation enforcement
# ---------------------------------------------------------------------------


def test_write_state_rejects_invalid_mode(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["mode"] = "extremist"  # not in enum
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_write_state_rejects_missing_required_field(tmp_path: Path) -> None:
    s = toggle.default_state()
    del s["enabled"]
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_write_state_rejects_unknown_component(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["components"]["mcp_shrink"] = True  # caveman-only key, not in ponytail schema
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_write_state_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["secret_field"] = "x"  # additionalProperties is false
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_read_state_raises_on_invalid_schema_on_disk(tmp_path: Path) -> None:
    p = toggle.state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "ponytail-toggle/v999", "enabled": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        toggle.read_state(tmp_path)


def test_read_state_raises_on_bad_json(tmp_path: Path) -> None:
    p = toggle.state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        toggle.read_state(tmp_path)
