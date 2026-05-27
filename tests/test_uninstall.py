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
    # First apply_config would have backed this up + replaced it.
    bh.backup_once(
        consumer, consumer / "AGENTS.md",
        location=bh.BackupLocation.NEXT_TO_FILE,
        with_timestamp=True,
    )
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
