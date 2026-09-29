"""Tests for ``scripts.uninstall`` — graceful removal of playbook integration."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import _backup_helper as bh
from scripts import uninstall as un


def _write_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def installed_consumer(tmp_path: Path) -> Path:
    """A consumer with marker blocks + a .bak snapshot from earlier apply_config."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "## §1 Project identity\n"
        "My customisation here.\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical bootstrap.\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    _write_lf(consumer / ".gitignore", (
        "dist/\n\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    return consumer


@pytest.fixture
def installed_with_bak(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer-bak"
    consumer.mkdir()
    # Pre-playbook state (without markers)
    pre_text = "# my original AGENTS.md\nNo markers here.\n"
    _write_lf(consumer / "AGENTS.md", pre_text)
    # bootstrap captures the BASE (pre-playbook) snapshot before replacing it.
    bh.backup_base(consumer, consumer / "AGENTS.md")
    # Now simulate post-apply state.
    _write_lf(consumer / "AGENTS.md", (
        "<!-- ai-playbook:begin id=bootstrap-directive -->\n"
        "Canonical\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    return consumer


# ---------------------------------------------------------------------------
# strip_markers_from_file
# ---------------------------------------------------------------------------


def test_strip_markers_keeps_custom_segments(installed_consumer: Path) -> None:
    changed = un.strip_markers_from_file(installed_consumer / "AGENTS.md")
    assert changed
    content = (installed_consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "My customisation here." in content
    assert "Canonical bootstrap." not in content
    assert "ai-playbook:begin" not in content


def test_strip_markers_noop_when_no_markers(tmp_path: Path) -> None:
    f = tmp_path / "plain.md"
    _write_lf(f, "# nothing managed\n")
    assert un.strip_markers_from_file(f) is False


def test_strip_markers_handles_missing_file(tmp_path: Path) -> None:
    assert un.strip_markers_from_file(tmp_path / "nope.md") is False


# ---------------------------------------------------------------------------
# Restore from .bak
# ---------------------------------------------------------------------------


def test_restore_originals_recovers_pre_playbook_content(installed_with_bak: Path) -> None:
    report = un.UninstallReport(target=installed_with_bak)
    un.restore_originals(installed_with_bak, report)
    assert any("AGENTS.md ←" in entry for entry in report.restored)
    content = (installed_with_bak / "AGENTS.md").read_text(encoding="utf-8")
    assert "my original AGENTS.md" in content
    assert "Canonical" not in content


# ---------------------------------------------------------------------------
# Full uninstall — no submodule (skips submodule deinit cleanly)
# ---------------------------------------------------------------------------


def test_uninstall_strips_markers_and_removes_state_dir(installed_consumer: Path) -> None:
    # Pretend state dir exists
    (installed_consumer / ".ai-playbook-state").mkdir()
    (installed_consumer / ".ai-playbook-state" / "applied-config.json").write_text("{}", encoding="utf-8")
    report = un.uninstall(installed_consumer, restore_from_bak=False)
    assert "AGENTS.md" in report.stripped
    assert ".gitignore" in report.stripped
    assert report.state_dir_removed
    # Verify the marker blocks are gone.
    agents = (installed_consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "ai-playbook:begin" not in agents
    gitignore = (installed_consumer / ".gitignore").read_text(encoding="utf-8")
    assert "dist/" in gitignore
    assert "ai-playbook:begin" not in gitignore


def test_uninstall_dry_run_does_not_modify(installed_consumer: Path) -> None:
    before_agents = (installed_consumer / "AGENTS.md").read_text(encoding="utf-8")
    report = un.uninstall(installed_consumer, dry_run=True)
    # Files untouched
    assert (installed_consumer / "AGENTS.md").read_text(encoding="utf-8") == before_agents
    # Plan reported
    assert any("would strip" in entry for entry in report.stripped)


def test_uninstall_keep_state_dir(installed_consumer: Path) -> None:
    (installed_consumer / ".ai-playbook-state").mkdir()
    report = un.uninstall(installed_consumer, restore_from_bak=False, keep_state_dir=True)
    assert (installed_consumer / ".ai-playbook-state").exists()
    assert not report.state_dir_removed


def test_uninstall_idempotent(installed_consumer: Path) -> None:
    un.uninstall(installed_consumer, restore_from_bak=False)
    # Second run: markers already gone, nothing to do
    report2 = un.uninstall(installed_consumer, restore_from_bak=False)
    assert report2.stripped == []


def test_restore_prefers_base_tagged_record_over_later_oldest(tmp_path: Path) -> None:
    """When a base snapshot exists, restore uses IT — even if other (older-index)
    backups also exist — because `base` is the authoritative pre-playbook anchor."""
    consumer = tmp_path / "consumer-base"
    consumer.mkdir()
    pre_text = "# the true pre-playbook AGENTS.md\n"
    _write_lf(consumer / "AGENTS.md", pre_text)
    # Capture BASE (the pre-playbook anchor).
    bh.backup_base(consumer, consumer / "AGENTS.md")
    # Then ordinary apply churn produces more backups of mutated content.
    _write_lf(consumer / "AGENTS.md", "# mutated v1\n")
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True)
    _write_lf(consumer / "AGENTS.md", "# mutated v2 with markers\n")

    report = un.UninstallReport(target=consumer)
    un.restore_originals(consumer, report)
    assert (consumer / "AGENTS.md").read_text(encoding="utf-8") == pre_text


# ---------------------------------------------------------------------------
# Regression: lifecycle defects (BASE loss, stale-backup restore, dangling hooks)
# ---------------------------------------------------------------------------


def test_uninstall_restores_base_for_files_outside_managed_paths(tmp_path: Path) -> None:
    """bootstrap.copy_templates BASE-snapshots CLAUDE.md, docs/runbook.md, ...
    Uninstall must restore them, not rmtree the only copy with the state dir."""
    consumer = tmp_path / "c"
    consumer.mkdir()
    _write_lf(consumer / "CLAUDE.md", "# hand-written CLAUDE\n")
    _write_lf(consumer / "docs" / "runbook.md", "# my runbook\n")
    bh.backup_base(consumer, consumer / "CLAUDE.md")
    bh.backup_base(consumer, consumer / "docs" / "runbook.md")
    _write_lf(consumer / "CLAUDE.md", "# alpha — CLAUDE.md (template)\n")
    _write_lf(consumer / "docs" / "runbook.md", "# alpha — Runbook (template)\n")

    report = un.uninstall(consumer)

    assert (consumer / "CLAUDE.md").read_text(encoding="utf-8") == "# hand-written CLAUDE\n"
    assert (consumer / "docs" / "runbook.md").read_text(encoding="utf-8") == "# my runbook\n"
    assert report.state_dir_removed
    assert not report.errors


def test_uninstall_keeps_state_dir_when_base_not_restored(tmp_path: Path) -> None:
    """--no-restore must not destroy BASE snapshots by removing the state dir."""
    consumer = tmp_path / "c"
    consumer.mkdir()
    _write_lf(consumer / "CLAUDE.md", "# hand-written\n")
    bh.backup_base(consumer, consumer / "CLAUDE.md")
    _write_lf(consumer / "CLAUDE.md", "# template\n")

    report = un.uninstall(consumer, restore_from_bak=False)

    assert not report.state_dir_removed
    assert bh.base_record_for(consumer, "CLAUDE.md") is not None
    assert any("CLAUDE.md" in w for w in report.warnings)


def test_uninstall_ignores_ordinary_backup_and_strips_in_place(tmp_path: Path) -> None:
    """Without a BASE record, an ordinary (post-playbook) backup must NOT be
    restored over the latest edits; strip markers in place instead."""
    consumer = tmp_path / "c"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "v1 edits\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\nold\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    bh.backup_once(consumer, consumer / "AGENTS.md", with_timestamp=True, session_id="apply-1")
    _write_lf(consumer / "AGENTS.md", (
        "v3 latest edits\n"
        "<!-- ai-playbook:begin id=bootstrap-directive -->\nnew\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))

    report = un.uninstall(consumer)

    text = (consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "v3 latest edits" in text
    assert "ai-playbook:begin" not in text
    assert report.restored == []
    assert "AGENTS.md" in report.stripped


def test_uninstall_removes_playbook_hooks_from_settings(tmp_path: Path) -> None:
    """Hooks pointing into .ai-playbook/ would exit 2 after the submodule is
    gone and block every Claude Code tool call."""
    import json

    consumer = tmp_path / "c"
    consumer.mkdir()
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Edit", "hooks": [
                    {"type": "command", "command": 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/mine.py"'},
                ]},
                {"matcher": "Edit|Bash", "hooks": [
                    {"type": "command",
                     "command": 'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/hook_dispatcher.py" PreToolUse'},
                ]},
            ],
            "UserPromptSubmit": [
                {"hooks": [
                    {"type": "command",
                     "command": 'python "$CLAUDE_PROJECT_DIR/.ai-playbook/scripts/rules/caveman-reinforce.rule.py"'},
                ]},
            ],
        },
        "permissions": {"deny": ["Bash(rm -rf /)"]},
    }
    _write_lf(consumer / ".claude" / "settings.json", json.dumps(settings, indent=2) + "\n")

    report = un.uninstall(consumer)

    after = json.loads((consumer / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert ".ai-playbook/" not in json.dumps(after)
    assert after["hooks"] == {"PreToolUse": [settings["hooks"]["PreToolUse"][0]]}
    assert after["permissions"] == settings["permissions"]
    assert ".claude/settings.json" in report.stripped


def test_uninstall_strips_feature_ruleset_blocks(tmp_path: Path) -> None:
    consumer = tmp_path / "c"
    consumer.mkdir()
    _write_lf(consumer / "AGENTS.md", (
        "# mine\n\n"
        "<!-- BEGIN auto-managed: caveman/ruleset:ultra -->\ncave\n<!-- END auto-managed -->\n"
        "<!-- BEGIN auto-managed: ponytail/ruleset:ultra -->\npony\n<!-- END auto-managed -->\n"
    ))

    un.uninstall(consumer)

    text = (consumer / "AGENTS.md").read_text(encoding="utf-8")
    assert "auto-managed" not in text
    assert "# mine" in text
