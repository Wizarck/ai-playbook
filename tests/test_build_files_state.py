"""Tests for ``scripts.build_files_state`` — generates files-state.js sidecar."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import build_files_state as bfs


def _write_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    c = tmp_path / "consumer"
    c.mkdir()
    _write_lf(c / "AGENTS.md", (
        "## §1 Project identity\nWe ship.\n\n"
        "<!-- ai-playbook:begin id=bootstrap-directive sha=abc -->\n"
        "canonical text\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    _write_lf(c / ".gitignore", (
        "dist/\n"
        "# >>> ai-playbook:begin id=playbook-patterns >>>\n"
        ".ai-playbook/overrides.log\n"
        "# <<< ai-playbook:end playbook-patterns <<<\n"
    ))
    # Applied-config with a manifest that matches the AGENTS.md content
    from scripts._template_classifier import compute_sha
    expected_agents = {"bootstrap-directive": compute_sha("canonical text")}
    expected_gitignore = {"playbook-patterns": compute_sha(".ai-playbook/overrides.log")}
    applied = {
        "schema": "ai-playbook-config/v1",
        "file_states": {
            "AGENTS.md": {"manifest": expected_agents, "last_applied": "2026-05-27T00:00:00Z"},
            ".gitignore": {"manifest": expected_gitignore, "last_applied": "2026-05-27T00:00:00Z"},
        },
    }
    _write_lf(c / ".ai-playbook" / "applied-config.json", json.dumps(applied))
    return c


def test_build_files_state_lists_managed_files(consumer: Path) -> None:
    state = bfs.build_files_state(consumer)
    rel_paths = {f["rel_path"] for f in state["files"]}
    assert "AGENTS.md" in rel_paths
    assert ".gitignore" in rel_paths


def test_classification_marks_canonical_when_sha_matches(consumer: Path) -> None:
    state = bfs.build_files_state(consumer)
    agents = next(f for f in state["files"] if f["rel_path"] == "AGENTS.md")
    canonical = [s for s in agents["sections"] if s["origin"] == "canonical"]
    assert len(canonical) == 1
    assert canonical[0]["id"] == "bootstrap-directive"


def test_classification_marks_drifted_when_sha_mismatches(consumer: Path) -> None:
    # Overwrite the canonical content so SHA mismatches the manifest.
    _write_lf(consumer / "AGENTS.md", (
        "<!-- ai-playbook:begin id=bootstrap-directive sha=abc -->\n"
        "user-edited body\n"
        "<!-- ai-playbook:end bootstrap-directive -->\n"
    ))
    state = bfs.build_files_state(consumer)
    agents = next(f for f in state["files"] if f["rel_path"] == "AGENTS.md")
    drifted = [s for s in agents["sections"] if s["origin"] == "drifted"]
    assert len(drifted) == 1


def test_write_files_state_emits_window_assignment(consumer: Path, tmp_path: Path) -> None:
    state = bfs.build_files_state(consumer)
    out = tmp_path / "out.js"
    bfs.write_files_state(state, out)
    content = out.read_text(encoding="utf-8")
    assert content.startswith("/* Auto-generated")
    assert "window.FILES_STATE = " in content
    # Round-trip parse the JSON inside the JS.
    m = re.search(r"window\.FILES_STATE\s*=\s*(\{.*\});", content, re.DOTALL)
    assert m is not None
    parsed = json.loads(m.group(1))
    assert parsed["schema"] == "files-state/v1"


def test_main_writes_sidecar(consumer: Path) -> None:
    rc = bfs.main(["--target", str(consumer), "--quiet"])
    assert rc == 0
    out = consumer / ".ai-playbook-state" / "files-state.js"
    assert out.is_file()
    assert "window.FILES_STATE" in out.read_text(encoding="utf-8")


def test_backups_section_populated(consumer: Path) -> None:
    from scripts._backup_helper import BackupLocation, backup_once
    backup_once(consumer, consumer / "AGENTS.md", location=BackupLocation.NEXT_TO_FILE, with_timestamp=True)
    state = bfs.build_files_state(consumer)
    assert len(state["backups"]) == 1
    assert state["backups"][0]["rel_path"] == "AGENTS.md"


def test_file_sha_emitted_for_cas(consumer: Path) -> None:
    """Every listed file carries a whole-file `file_sha` CAS token matching
    compute_file_sha of its current content."""
    from scripts._template_classifier import compute_file_sha
    state = bfs.build_files_state(consumer)
    for f in state["files"]:
        assert "file_sha" in f
        text = (consumer / f["rel_path"]).read_text(encoding="utf-8")
        assert f["file_sha"] == compute_file_sha(text)
