"""Tests for ``scripts.migrate_to_bundle`` — legacy → bundle extraction."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import migrate_to_bundle as mb


def _write_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# extract_project_meta
# ---------------------------------------------------------------------------


def test_extract_project_meta_basic() -> None:
    text = (
        "# myproj — AGENTS.md\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "canonical bootstrap text\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n\n"
        "## 1 Project identity\n"
        "We build widgets for Acme.\n"
        "Spanning multiple lines.\n\n"
        "## 3 Active work\n"
        "openspec/changes/T42-foo/\n\n"
        "## 4 Project hard rules\n"
        "- Never commit without tests.\n\n"
        "## 8 Gotchas\n"
        "- 2026-05-01 — beware Windows line endings.\n"
    )
    meta = mb.extract_project_meta(text)
    assert "Acme" in meta["project_identity"]
    assert "Spanning multiple lines" in meta["project_identity"]
    assert "T42-foo" in meta["active_work"]
    assert "Never commit without tests" in meta["hard_rules"]
    assert "Windows line endings" in meta["gotchas"]
    assert meta["inherited_overrides"] == ""


def test_extract_project_meta_handles_section_marker_with_section_sigil() -> None:
    text = (
        "## §1 Project identity\nAcme builds bots.\n\n"
        "## §3 Active work\nNone.\n"
    )
    meta = mb.extract_project_meta(text)
    assert meta["project_identity"] == "Acme builds bots."
    assert meta["active_work"] == "None."


def test_extract_project_meta_skips_canonical_blocks_inside_markers() -> None:
    text = (
        "<!-- ai-playbook:begin id=capability-map -->\n"
        "## 5 Capability map\nThis is canonical, should not be extracted.\n"
        "<!-- ai-playbook:end capability-map -->\n\n"
        "## 1 Project identity\nReal consumer content.\n"
    )
    meta = mb.extract_project_meta(text)
    assert meta["project_identity"] == "Real consumer content."
    # §5 capability-map lives inside a marker → no map for §5 in project_meta keys anyway.


def test_extract_project_meta_missing_sections_blank() -> None:
    text = "# only a header\n\n## 1 Project identity\nx\n"
    meta = mb.extract_project_meta(text)
    assert meta["project_identity"] == "x"
    assert meta["active_work"] == ""
    assert meta["hard_rules"] == ""
    assert meta["gotchas"] == ""


# ---------------------------------------------------------------------------
# extract_gitignore_extras
# ---------------------------------------------------------------------------


def test_extract_gitignore_extras_strips_markers_and_comments() -> None:
    text = (
        "# my project notes\n"
        "dist/\n"
        "logs/\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
        "\n"
        "*.swp\n"
    )
    extras = mb.extract_gitignore_extras(text)
    assert "dist/" in extras
    assert "logs/" in extras
    assert "*.swp" in extras
    assert ".ai-playbook/overrides.log" not in extras


def test_extract_gitignore_extras_dedups() -> None:
    text = "dist/\ndist/\nlogs/\n"
    extras = mb.extract_gitignore_extras(text)
    assert extras == ["dist/", "logs/"]


# ---------------------------------------------------------------------------
# extract_mcp_project_servers
# ---------------------------------------------------------------------------


def test_extract_mcp_project_servers_drops_hindsight_baseline(tmp_path: Path) -> None:
    yaml_path = tmp_path / "mcp-servers.project.yaml"
    _write_lf(yaml_path, (
        "schema: mcp-servers/v1\n"
        "servers:\n"
        "  hindsight:\n"
        "    id: hindsight\n"
        "  custom-server:\n"
        "    id: custom-server\n"
        "    transport: stdio\n"
        "    command: node\n"
    ))
    extras = mb.extract_mcp_project_servers(yaml_path)
    assert "hindsight" not in extras
    assert "custom-server" in extras
    assert extras["custom-server"]["command"] == "node"


def test_extract_mcp_project_servers_missing_file(tmp_path: Path) -> None:
    assert mb.extract_mcp_project_servers(tmp_path / "missing.yaml") == {}


# ---------------------------------------------------------------------------
# extract_claude_settings_extras
# ---------------------------------------------------------------------------


def test_extract_claude_settings_extras(tmp_path: Path) -> None:
    p = tmp_path / "settings.local.json"
    _write_lf(p, json.dumps({
        "permissions": {
            "allow": ["Edit", "Write"],
            "additionalDirectories": ["/extra"],
        },
    }))
    extras = mb.extract_claude_settings_extras(p)
    assert extras["permissions_allow"] == ["Edit", "Write"]
    assert extras["additional_directories"] == ["/extra"]


def test_extract_claude_settings_extras_missing_returns_empty(tmp_path: Path) -> None:
    assert mb.extract_claude_settings_extras(tmp_path / "no.json") == {}


# ---------------------------------------------------------------------------
# build_bundle integration
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "## 1 Project identity\nWe ship.\n\n"
        "## 4 Project hard rules\n- No skipping tests.\n"
    ))
    _write_lf(consumer / ".gitignore", "dist/\nlogs/\n")
    return consumer


def test_build_bundle_assembles_sections(legacy_consumer: Path) -> None:
    bundle = mb.build_bundle(legacy_consumer)
    assert bundle["schema"] == "ai-playbook-config/v1"
    assert bundle["project_meta"]["project_identity"] == "We ship."
    assert "No skipping tests" in bundle["project_meta"]["hard_rules"]
    assert bundle["gitignore_extras"]["patterns"] == ["dist/", "logs/"]
    # No mcp-servers.project.yaml → section absent
    assert "mcp_project_servers" not in bundle


def test_build_bundle_raises_when_agents_md_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="AGENTS.md not found"):
        mb.build_bundle(tmp_path)


def test_write_bundle_round_trip(legacy_consumer: Path, tmp_path: Path) -> None:
    bundle = mb.build_bundle(legacy_consumer)
    out = tmp_path / "out.json"
    mb.write_bundle(bundle, out)
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["project_meta"]["project_identity"] == "We ship."
