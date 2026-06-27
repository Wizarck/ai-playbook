"""Tests for scripts.caveman.toggle — state read/write + schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.caveman import toggle

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


def test_find_project_root_ai_playbook_dir_alone_insufficient(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ".ai-playbook/" alone must NOT identify a project root, because
    # ~/.ai-playbook/ is the personal registry and would cause every dir
    # under $HOME to resolve as the home directory.
    (tmp_path / ".ai-playbook").mkdir()
    # Constrain the search: start inside tmp_path, then forbid the walk from
    # discovering the user's home AGENTS.md by inspecting only the direct
    # result. If find_project_root walks up and finds an AGENTS.md on the
    # real machine, that's a real project root higher up — we only care
    # that tmp_path itself is NOT returned.
    found = toggle.find_project_root(tmp_path)
    assert found != tmp_path


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
    """Regression for the ``.ai-playbook/.ai-playbook/`` nesting bug.

    When cwd is inside a consumer's playbook submodule (which carries its
    own ``AGENTS.md``), the walk MUST skip past the submodule and resolve
    to the consumer root — otherwise caveman state is written nested
    under ``<consumer>/.ai-playbook/.ai-playbook/caveman.json``.
    """
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")
    submodule = consumer / ".ai-playbook"
    (submodule / "scripts").mkdir(parents=True)
    (submodule / "AGENTS.md").write_text("# playbook self\n", encoding="utf-8")

    # cwd anywhere inside the submodule resolves to the consumer root.
    assert toggle.find_project_root(submodule) == consumer
    assert toggle.find_project_root(submodule / "scripts") == consumer


def test_find_project_root_skips_skills_sources_mirror(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "AGENTS.md").write_text("# consumer\n", encoding="utf-8")
    mirror = consumer / ".skills-sources" / "ai-playbook"
    (mirror / "scripts").mkdir(parents=True)
    (mirror / "AGENTS.md").write_text("# playbook self mirror\n", encoding="utf-8")

    assert toggle.find_project_root(mirror) == consumer
    assert toggle.find_project_root(mirror / "scripts") == consumer


# ---------------------------------------------------------------------------
# Default state shape
# ---------------------------------------------------------------------------


def test_default_state_shape() -> None:
    s = toggle.default_state()
    assert s["schema"] == "caveman-toggle/v1"
    assert s["enabled"] is False
    assert s["mode"] == "ultra"
    assert set(s["components"].keys()) == {
        "response_style",
        "compress_docs",
        "subagents_cavecrew",
        "commit_caveman",
        "review_caveman",
        "mcp_shrink",
    }
    assert all(v is False for v in s["components"].values())
    # applied_at must be ISO-8601 parseable
    from datetime import datetime
    datetime.fromisoformat(s["applied_at"])


def test_default_state_passes_schema() -> None:
    schema = toggle._load_schema()
    jsonschema.validate(toggle.default_state(), schema)


# ---------------------------------------------------------------------------
# read_state / write_state round-trip
# ---------------------------------------------------------------------------


def test_read_state_returns_default_when_missing(tmp_path: Path) -> None:
    state = toggle.read_state(tmp_path)
    assert state["enabled"] is False
    assert state["mode"] == "ultra"
    # File should NOT be created by read.
    assert not toggle.state_path(tmp_path).is_file()


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["enabled"] = True
    s["mode"] = "ultra"
    s["components"]["response_style"] = True
    s["components"]["mcp_shrink"] = True
    toggle.write_state(tmp_path, s)

    p = toggle.state_path(tmp_path)
    assert p.is_file()

    loaded = toggle.read_state(tmp_path)
    assert loaded["enabled"] is True
    assert loaded["mode"] == "ultra"
    assert loaded["components"]["response_style"] is True
    assert loaded["components"]["mcp_shrink"] is True
    assert loaded["components"]["compress_docs"] is False


def test_write_state_creates_state_dir(tmp_path: Path) -> None:
    assert not (tmp_path / ".ai-playbook").exists()
    toggle.write_state(tmp_path, toggle.default_state())
    assert (tmp_path / ".ai-playbook").is_dir()
    assert toggle.state_path(tmp_path).is_file()


def test_write_state_atomic_no_temp_left_behind(tmp_path: Path) -> None:
    s = toggle.default_state()
    toggle.write_state(tmp_path, s)
    # No .caveman-*.tmp leftover in the state dir.
    leftovers = list((tmp_path / ".ai-playbook").glob(".caveman-*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# Schema validation enforcement
# ---------------------------------------------------------------------------


def test_write_state_rejects_invalid_mode(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["mode"] = "telegraphic"  # not in enum
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_write_state_rejects_missing_required_field(tmp_path: Path) -> None:
    s = toggle.default_state()
    del s["enabled"]
    with pytest.raises(jsonschema.ValidationError):
        toggle.write_state(tmp_path, s)


def test_write_state_rejects_unknown_component(tmp_path: Path) -> None:
    s = toggle.default_state()
    s["components"]["wenyan_mode"] = True  # not in schema
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
    # Hand-craft a state file that's valid JSON but wrong schema version
    p.write_text(json.dumps({"schema": "caveman-toggle/v999", "enabled": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        toggle.read_state(tmp_path)


def test_read_state_raises_on_bad_json(tmp_path: Path) -> None:
    p = toggle.state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        toggle.read_state(tmp_path)
