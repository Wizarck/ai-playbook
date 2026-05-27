"""Tests for ``scripts._managed_files`` — orchestration of file renders."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import _managed_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def fake_playbook(tmp_path: Path) -> Path:
    """Build a minimal playbook tree with the templates the orchestrator looks for."""
    root = tmp_path / "playbook"
    tdir = root / "templates" / "new-project"
    tdir.mkdir(parents=True)
    _write_lf(tdir / "AGENTS.md.tmpl", (
        "---\n"
        "schema: agents-md/v1\n"
        "project: {{PROJECT_NAME}}\n"
        "owner: {{OWNER_EMAIL}}\n"
        "---\n\n"
        "# {{PROJECT_NAME}} — AGENTS.md\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical bootstrap.\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n\n"
        "## §1 Project identity\n"
        "{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}\n"
    ))
    _write_lf(tdir / ".gitignore.tmpl", (
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    _write_lf(tdir / ".pre-commit-config.yaml.tmpl", (
        "repos:\n"
        "# >>> ai-playbook:begin id=playbook-hooks >>>\n"
        "  - repo: local\n"
        "    hooks: []\n"
        "# <<< ai-playbook:end playbook-hooks <<<\n"
    ))
    _write_lf(tdir / ".coderabbit.yaml.tmpl", "language: en-US\n")
    (tdir / ".claude").mkdir()
    _write_lf(tdir / ".claude" / "settings.local.json.tmpl", '{"seed": true}\n')
    _write_lf(tdir / "mcp-servers.project.yaml.tmpl", (
        "schema: mcp-servers/v1\n"
        "# >>> ai-playbook:begin id=project-servers-baseline >>>\n"
        "servers:\n"
        "  hindsight:\n"
        "    id: hindsight\n"
        "# <<< ai-playbook:end project-servers-baseline <<<\n"
    ))
    return root


@pytest.fixture
def fake_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "---\n"
        "schema: agents-md/v1\n"
        "project: myproj\n"
        "owner: dev@example.com\n"
        "---\n\n"
        "# myproj — AGENTS.md (stale)\n"
    ))
    return consumer


# ---------------------------------------------------------------------------
# compute_substitutions
# ---------------------------------------------------------------------------


def test_compute_substitutions_from_agents_md_frontmatter(fake_consumer: Path) -> None:
    subs = _managed_files.compute_substitutions(fake_consumer)
    assert subs["PROJECT_NAME"] == "myproj"
    assert subs["OWNER_EMAIL"] == "dev@example.com"
    assert subs["PROJECT_BANK"] == "myproj"
    assert "TODAY" in subs


def test_compute_substitutions_falls_back_to_dir_name(tmp_path: Path) -> None:
    consumer = tmp_path / "fresh-project"
    consumer.mkdir()
    subs = _managed_files.compute_substitutions(consumer)
    assert subs["PROJECT_NAME"] == "fresh-project"
    assert subs["OWNER_EMAIL"] == "unknown@example.com"


# ---------------------------------------------------------------------------
# apply_managed_files — no triggers
# ---------------------------------------------------------------------------


def test_no_trigger_sections_no_op(fake_playbook: Path, fake_consumer: Path) -> None:
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer,
        playbook_root=fake_playbook,
        bundle={"schema": "ai-playbook-config/v1"},
    )
    assert result.ok
    assert "no managed-file trigger sections" in result.detail
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8").startswith("---")


# ---------------------------------------------------------------------------
# apply_managed_files — AGENTS.md
# ---------------------------------------------------------------------------


def test_agents_md_rendered_when_project_meta_present(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "Acme builds widgets."},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    assert result.ok
    rendered = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "myproj" in rendered
    assert "Acme builds widgets." in rendered
    assert "Canonical bootstrap." in rendered
    assert result.restart_session_needed  # AGENTS.md is LLM-read
    assert "AGENTS.md" in result.file_states
    assert "bootstrap-directive" in result.file_states["AGENTS.md"]["manifest"]


def test_agents_md_backup_created_on_overwrite(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new identity"},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # Default backup_preferences = next + timestamped
    backups = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert len(backups) == 1


def test_agents_md_idempotent_no_backup_no_write(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "stable"},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # second apply with same bundle
    result2 = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # Only one backup from the first apply.
    backups = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert len(backups) == 1
    assert any("identical, no write" in c for c in result2.changes)


# ---------------------------------------------------------------------------
# apply_managed_files — .gitignore preservation
# ---------------------------------------------------------------------------


def test_gitignore_preserves_consumer_lines(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    _write_lf(fake_consumer / ".gitignore", (
        "# my custom\n"
        "dist/\n"
        "logs/\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    bundle = {
        "schema": "ai-playbook-config/v1",
        "gitignore_extras": {"patterns": ["*.swp"]},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    rendered = (fake_consumer / ".gitignore").read_text(encoding="utf-8")
    assert "dist/" in rendered
    assert "logs/" in rendered
    assert "*.swp" in rendered
    assert ".ai-playbook/overrides.log" in rendered


# ---------------------------------------------------------------------------
# apply_managed_files — seed-only behaviour
# ---------------------------------------------------------------------------


def test_settings_local_json_seed_only_when_missing(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "claude_settings_extras": {"permissions_allow": ["Edit"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    dest = fake_consumer / ".claude" / "settings.local.json"
    assert dest.is_file()
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["permissions"]["allow"] == ["Edit"]
    assert result.restart_session_needed


def test_settings_local_json_seed_only_kept_when_existing(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    dest = fake_consumer / ".claude" / "settings.local.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_lf(dest, '{"existing": true}\n')
    bundle = {
        "schema": "ai-playbook-config/v1",
        "claude_settings_extras": {"permissions_allow": ["Edit"]},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    # seed-only file already exists → kept as-is, NOT overwritten by extras.
    assert json.loads(dest.read_text(encoding="utf-8")) == {"existing": True}
    assert any("seed-only" in c for c in result.changes)


# ---------------------------------------------------------------------------
# apply_managed_files — dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_touch_disk(fake_playbook: Path, fake_consumer: Path) -> None:
    original = (fake_consumer / "AGENTS.md").read_text(encoding="utf-8")
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new"},
    }
    result = _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
        dry_run=True,
    )
    assert (fake_consumer / "AGENTS.md").read_text(encoding="utf-8") == original
    assert "DRY-RUN" in result.detail
    assert "AGENTS.md" in result.detail


# ---------------------------------------------------------------------------
# apply_managed_files — backup central location
# ---------------------------------------------------------------------------


def test_backup_central_location_respected(
    fake_playbook: Path, fake_consumer: Path,
) -> None:
    bundle = {
        "schema": "ai-playbook-config/v1",
        "project_meta": {"project_identity": "new"},
        "backup_preferences": {"location": "central", "with_timestamp": True},
    }
    _managed_files.apply_managed_files(
        consumer_root=fake_consumer, playbook_root=fake_playbook, bundle=bundle,
    )
    next_to_file = list(fake_consumer.glob("AGENTS.md.*.bak"))
    assert next_to_file == []
    central = list((fake_consumer / ".ai-playbook-state" / "backups").rglob("AGENTS.md.*.bak"))
    assert len(central) == 1
