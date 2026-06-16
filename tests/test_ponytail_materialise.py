"""Tests for scripts.ponytail.materialise — inject/strip AGENTS.md block."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ponytail import materialise

# ---------------------------------------------------------------------------
# render_block_content — content derivation from SKILL.md
# ---------------------------------------------------------------------------


def test_render_block_content_full_mode() -> None:
    body = materialise.render_block_content("full")
    assert "**Ponytail: ON · intensity full" in body
    assert "The ladder:" in body
    assert "Mode (full):" in body
    assert "When NOT to be lazy:" in body
    assert "Boundaries:" in body
    assert "YAGNI" in body  # from the ladder
    assert "python -m scripts.ponytail off" in body  # from footer


def test_render_block_content_lite_mode_includes_lite_section() -> None:
    body = materialise.render_block_content("lite")
    assert "Mode (lite):" in body
    assert "lazier alternative" in body.lower()


def test_render_block_content_ultra_mode_includes_ultra_section() -> None:
    body = materialise.render_block_content("ultra")
    assert "Mode (ultra):" in body
    assert "extremist" in body.lower()


def test_render_block_content_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="invalid mode"):
        materialise.render_block_content("extremist")


def test_render_block_content_raises_on_missing_section(tmp_path: Path) -> None:
    fake_playbook = tmp_path / "playbook"
    (fake_playbook / "skills" / "ponytail").mkdir(parents=True)
    (fake_playbook / "specs").mkdir()
    (fake_playbook / "scripts").mkdir()
    (fake_playbook / "schemas").mkdir()
    skill = fake_playbook / "skills" / "ponytail" / "SKILL.md"
    skill.write_text(
        "---\nname: ponytail\ndescription: Use when test.\n---\n\n# ponytail\n\nNo sections.\n",
        encoding="utf-8",
    )
    with pytest.raises(LookupError, match="missing required section"):
        materialise.render_block_content("full", playbook_root=fake_playbook)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agents_md(project: Path, content: str = "# fake project\n\n## 1 Bootstrap\n\nDo X.\n") -> Path:
    p = project / "AGENTS.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# materialise — inject path
# ---------------------------------------------------------------------------


def test_materialise_injects_into_clean_agents_md(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    backup = materialise.materialise(tmp_path, "full")
    assert backup.is_file()
    assert backup.parent == tmp_path / ".ai-playbook" / "backups" / "agents"

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN auto-managed: ponytail/ruleset:full -->" in text
    assert "<!-- END auto-managed -->" in text
    assert "Ponytail: ON" in text


def test_materialise_preserves_existing_content(tmp_path: Path) -> None:
    original = "# fake project\n\n## 1 Bootstrap\n\nDo X.\n## 2 Dispatcher\n\nLinks.\n"
    _make_agents_md(tmp_path, original)
    materialise.materialise(tmp_path, "full")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# fake project" in text
    assert "## 1 Bootstrap" in text
    assert "Do X." in text
    assert "## 2 Dispatcher" in text


def test_materialise_creates_backup_before_writing(tmp_path: Path) -> None:
    original = "# fake project\nbody\n"
    _make_agents_md(tmp_path, original)
    backup = materialise.materialise(tmp_path, "full")
    assert backup.read_text(encoding="utf-8") == original


def test_materialise_idempotent_same_mode(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    materialise.materialise(tmp_path, "full")
    text_after_first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    materialise.materialise(tmp_path, "full")
    text_after_second = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text_after_first == text_after_second


def test_materialise_refresh_changes_mode(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    materialise.materialise(tmp_path, "full")
    materialise.materialise(tmp_path, "ultra")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "ponytail/ruleset:ultra" in text
    assert "ponytail/ruleset:full" not in text
    assert text.count("<!-- BEGIN auto-managed: ponytail/ruleset:") == 1


def test_materialise_raises_when_agents_md_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="AGENTS.md"):
        materialise.materialise(tmp_path, "full")


def test_materialise_rejects_invalid_mode(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    with pytest.raises(ValueError, match="invalid mode"):
        materialise.materialise(tmp_path, "extremist")


def test_materialise_refuses_multiple_existing_blocks(tmp_path: Path) -> None:
    content = (
        "# project\n\n"
        "<!-- BEGIN auto-managed: ponytail/ruleset:full -->\nbody1\n<!-- END auto-managed -->\n"
        "\n"
        "<!-- BEGIN auto-managed: ponytail/ruleset:lite -->\nbody2\n<!-- END auto-managed -->\n"
    )
    _make_agents_md(tmp_path, content)
    with pytest.raises(ValueError, match="2 ponytail blocks"):
        materialise.materialise(tmp_path, "full")


# ---------------------------------------------------------------------------
# strip — removal path
# ---------------------------------------------------------------------------


def test_strip_removes_block(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    materialise.materialise(tmp_path, "full")
    assert materialise.is_materialised(tmp_path)

    backup = materialise.strip(tmp_path)
    assert backup is not None
    assert backup.is_file()
    assert not materialise.is_materialised(tmp_path)

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "BEGIN auto-managed: ponytail" not in text
    assert "# fake project" in text


def test_strip_idempotent_when_no_block(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    result = materialise.strip(tmp_path)
    assert result is None
    backups_dir = tmp_path / ".ai-playbook" / "backups"
    assert not backups_dir.exists() or not list(backups_dir.rglob("*.bak"))


def test_strip_returns_none_when_agents_md_missing(tmp_path: Path) -> None:
    result = materialise.strip(tmp_path)
    assert result is None


def test_strip_then_materialise_round_trip_preserves_original(tmp_path: Path) -> None:
    original = "# fake project\n\n## 1 Bootstrap\n\nDo X.\n"
    _make_agents_md(tmp_path, original)
    materialise.materialise(tmp_path, "full")
    materialise.strip(tmp_path)
    final = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert final == original


# ---------------------------------------------------------------------------
# is_materialised
# ---------------------------------------------------------------------------


def test_is_materialised_false_when_no_agents_md(tmp_path: Path) -> None:
    assert materialise.is_materialised(tmp_path) is False


def test_is_materialised_false_when_no_block(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    assert materialise.is_materialised(tmp_path) is False


def test_is_materialised_true_after_materialise(tmp_path: Path) -> None:
    _make_agents_md(tmp_path)
    materialise.materialise(tmp_path, "full")
    assert materialise.is_materialised(tmp_path) is True
