"""Tests for the hook + rules-toggle integration (Phase F).

Validates that when ``<project>/.ai-playbook/rules-toggle.json`` carries
``apply-skill-enforcement.enabled=false`` (or ``layers.L1=false``), the L1
PreToolUse hook short-circuits with ``verdict=warn`` /
``block_class=rule_disabled`` / ``toggle_layer=L1`` and exits 0.

Mirrors the helper shape from ``tests/test_apply_enforce_hook_template.py``
to keep the assertion surface small and consistent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = (
    REPO_ROOT
    / "templates"
    / "new-project"
    / ".claude"
    / "hooks"
    / "openspec-apply-enforce.py.tmpl"
)


def _render_hook(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _seed_project_with_change(tmp_path: Path, change_id: str, write_paths: list[str]) -> Path:
    project = tmp_path / "myproj"
    project.mkdir()
    # Helper module under .ai-playbook/scripts/ — the hook fail-opens if absent.
    playbook = project / ".ai-playbook"
    (playbook / "scripts").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "scripts" / "openspec_apply_marker.py",
        playbook / "scripts" / "openspec_apply_marker.py",
    )
    # An active OpenSpec change with declared write_paths so the hook has
    # something to block against in the baseline case.
    change_dir = project / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text(f"# {change_id}\n", encoding="utf-8")
    bullets = "\n".join(f"* `{p}`" for p in write_paths)
    (change_dir / "tasks.md").write_text(
        f"# tasks — {change_id}\n\n## Owns (write_paths)\n\n{bullets}\n\n## Reads\n\n* nothing\n",
        encoding="utf-8",
    )
    return project


def _write_toggle_state(project: Path, state: dict) -> None:
    p = project / ".ai-playbook" / "rules-toggle.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _invoke_hook(
    hook: Path,
    project: Path,
    tool_name: str,
    tool_input: dict,
    *,
    session_id: str = "test-session-toggle",
    state_dir: Path,
) -> subprocess.CompletedProcess[str]:
    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(project),
        "session_id": session_id,
    }
    env = os.environ.copy()
    env.pop("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", None)
    env.pop("AIPLAYBOOK_BASH_INSPECTION", None)
    env["CLAUDE_SESSION_ID"] = session_id
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    env["AI_PLAYBOOK_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(hook)],
        cwd=project,
        env=env,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _read_telemetry(state_dir: Path) -> list[dict]:
    p = state_dir / "rule-events.jsonl"
    if not p.is_file():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_edit_blocked_without_toggle(tmp_path: Path) -> None:
    """Baseline: without a toggle file, the hook still blocks (control case)."""
    project = _seed_project_with_change(tmp_path, "demo", ["be/foo.py"])
    hook = _render_hook(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    result = _invoke_hook(
        hook,
        project,
        "Edit",
        {"file_path": str(project / "be" / "foo.py")},
        state_dir=state_dir,
    )
    # Baseline: blocks with exit 2 (hook contract — see hook source).
    assert result.returncode != 0
    events = _read_telemetry(state_dir)
    assert any(e.get("verdict") == "block" for e in events)


def test_edit_skipped_when_l1_disabled(tmp_path: Path) -> None:
    """Toggle OFF at L1 → hook exits 0 + emits warn + block_class=rule_disabled."""
    project = _seed_project_with_change(tmp_path, "demo", ["be/foo.py"])
    hook = _render_hook(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_toggle_state(project, {
        "schema": "rules-toggle/v1",
        "rules": {
            "apply-skill-enforcement": {
                "enabled": False,
                "reason": "test ten-chars reason",
            }
        },
    })
    result = _invoke_hook(
        hook,
        project,
        "Edit",
        {"file_path": str(project / "be" / "foo.py")},
        state_dir=state_dir,
    )
    assert result.returncode == 0, f"expected pass-through, got {result.returncode}; stderr={result.stderr}"
    events = _read_telemetry(state_dir)
    assert any(
        e.get("verdict") == "warn" and e.get("block_class") == "rule_disabled" and e.get("toggle_layer") == "L1"
        for e in events
    ), f"expected rule_disabled warn event, got: {events}"


def test_bash_skipped_when_l1_disabled(tmp_path: Path) -> None:
    """Same short-circuit applies to Bash decisions."""
    project = _seed_project_with_change(tmp_path, "demo", ["be/foo.py"])
    hook = _render_hook(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_toggle_state(project, {
        "schema": "rules-toggle/v1",
        "rules": {
            "apply-skill-enforcement": {
                "enabled": True,
                "layers": {"L1": False},
            }
        },
    })
    result = _invoke_hook(
        hook,
        project,
        "Bash",
        {"command": "echo x > be/foo.py"},
        state_dir=state_dir,
    )
    assert result.returncode == 0, f"expected pass-through, got {result.returncode}; stderr={result.stderr}"
    events = _read_telemetry(state_dir)
    assert any(
        e.get("verdict") == "warn"
        and e.get("block_class") == "rule_disabled"
        and e.get("toggle_layer") == "L1"
        and e.get("block_tool") == "Bash"
        for e in events
    ), f"expected Bash rule_disabled warn event, got: {events}"


def test_layer_l3_only_disabled_does_not_affect_hook(tmp_path: Path) -> None:
    """L3 OFF must NOT short-circuit L1; the hook still blocks Edit."""
    project = _seed_project_with_change(tmp_path, "demo", ["be/foo.py"])
    hook = _render_hook(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_toggle_state(project, {
        "schema": "rules-toggle/v1",
        "rules": {
            "apply-skill-enforcement": {
                "enabled": True,
                "layers": {"L3": False},
            }
        },
    })
    result = _invoke_hook(
        hook,
        project,
        "Edit",
        {"file_path": str(project / "be" / "foo.py")},
        state_dir=state_dir,
    )
    # L1 still active → blocks.
    assert result.returncode != 0
    events = _read_telemetry(state_dir)
    # Should be a block event, NOT a rule_disabled warn.
    assert any(e.get("verdict") == "block" for e in events)
    assert not any(e.get("block_class") == "rule_disabled" for e in events)
