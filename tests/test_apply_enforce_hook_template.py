"""Tests for the PreToolUse hook template
`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`.

Slice: enforce-apply-skill (v0.14.0). Phase B T4.

Strategy
--------
The template is a Python script with `{{PLACEHOLDER}}`-style substitutions for
project-specific values. Tests render the template into a temp project, then
invoke the rendered script as a subprocess, feeding synthetic Claude Code
hook input on stdin and asserting exit code + stderr per the canonical error
shape (per `specs/error-message-standard.md`).

Contracts:
- design.md §2 (hook contract)
- design.md §2.2 (decision flow)
- design.md §2.3 (canonical error message)
- specs/break-glass.md (override env)
"""
from __future__ import annotations

import ast
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


def _render_template(target: Path) -> Path:
    """Copy the template into target, substituting placeholders.

    The template currently has no placeholders other than the shebang and is
    valid Python as written; rendering is a straight copy. Kept as a helper
    so future placeholder substitution lives in one place.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    return target


def _seed_project(tmp_path: Path) -> Path:
    """Create a minimal project layout with the ai-playbook scripts symlinked.

    Returns the project root.
    """
    project = tmp_path / "myproj"
    project.mkdir()
    # Mirror .ai-playbook/scripts/openspec_apply_marker.py so the hook can find it.
    playbook = project / ".ai-playbook"
    (playbook / "scripts").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "scripts" / "openspec_apply_marker.py",
        playbook / "scripts" / "openspec_apply_marker.py",
    )
    return project


def _seed_change(
    project: Path,
    change_id: str,
    write_paths: list[str],
    with_tasks: bool = True,
) -> Path:
    change_dir = project / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text(f"# {change_id}\n", encoding="utf-8")
    if with_tasks:
        bullets = "\n".join(f"* `{p}`" for p in write_paths)
        (change_dir / "tasks.md").write_text(
            f"# tasks — {change_id}\n\n## Owns (write_paths)\n\n{bullets}\n\n## Reads\n\n* nothing\n",
            encoding="utf-8",
        )
    return change_dir


def _invoke_hook(
    hook: Path,
    project: Path,
    file_path: str,
    *,
    tool_name: str = "Edit",
    session_id: str = "test-session-1",
    override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    payload = {
        "tool_name": tool_name,
        "tool_input": {"file_path": str(project / file_path)},
        "cwd": str(project),
        "session_id": session_id,
    }
    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = session_id
    if override is not None:
        env["AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE"] = override
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hook_template_renders_clean_python(tmp_path: Path) -> None:
    rendered = _render_template(tmp_path / ".claude" / "hooks" / "openspec-apply-enforce.py")
    src = rendered.read_text(encoding="utf-8")
    # Must parse as Python AST
    ast.parse(src)
    # Must have a shebang
    assert src.startswith("#!"), "hook must declare a shebang"


def test_hook_blocks_when_no_marker(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/foo.py")
    assert proc.returncode == 2, f"expected block (2), got {proc.returncode}; stderr={proc.stderr}"
    assert "apply phase bypass" in proc.stderr.lower()


def test_hook_allows_when_marker_present(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    # Pre-seed marker with a start record for our session
    marker = project / "openspec" / "changes" / "demo-slice" / ".apply_log.jsonl"
    marker.write_text(
        '{"event":"start","change_id":"demo-slice","session_id":"test-session-1",'
        '"ts":"2026-05-15T10:00:00.000Z","skill_version":"1.1"}\n',
        encoding="utf-8",
    )
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/foo.py")
    assert proc.returncode == 0, f"expected allow (0), got {proc.returncode}; stderr={proc.stderr}"


def test_hook_allows_path_outside_write_paths(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "frontend/unrelated.tsx")
    assert proc.returncode == 0, proc.stderr


def test_hook_allows_path_in_changes_folder(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    # Editing the change's own proposal.md is part of propose/design refinement → ALLOW
    proc = _invoke_hook(hook, project, "openspec/changes/demo-slice/proposal.md")
    assert proc.returncode == 0, proc.stderr


def test_hook_allows_when_tasks_md_absent(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    # Change folder exists with proposal but NO tasks.md → pre-apply phase
    _seed_change(project, "demo-slice", ["backend/foo.py"], with_tasks=False)
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/foo.py")
    assert proc.returncode == 0, f"pre-apply edits should not be gated; stderr={proc.stderr}"


def test_hook_honours_override_env(tmp_path: Path) -> None:
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(
        hook,
        project,
        "backend/foo.py",
        override="emergency post-review hotfix",
    )
    assert proc.returncode == 0, f"override env should allow; stderr={proc.stderr}"
    # Override is audited in the marker
    marker = project / "openspec" / "changes" / "demo-slice" / ".apply_log.jsonl"
    assert marker.exists(), "override record should be appended to marker"
    records = [
        json.loads(line)
        for line in marker.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    overrides = [r for r in records if r.get("event") == "override"]
    assert len(overrides) == 1
    assert "emergency" in overrides[0]["reason"]


def test_hook_handles_glob_in_write_paths(tmp_path: Path) -> None:
    """write_paths can use globs (e.g., `tests/foo/*`); hook must glob-match."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/services/*.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/services/auth.py")
    # No marker → block
    assert proc.returncode == 2, proc.stderr
    # Outside the glob → allow
    proc2 = _invoke_hook(hook, project, "backend/handlers/auth.py")
    assert proc2.returncode == 0, proc2.stderr


def test_hook_skips_when_no_changes_folder(tmp_path: Path) -> None:
    """Project with no openspec/changes/ at all → ALLOW (nothing to gate)."""
    project = _seed_project(tmp_path)
    # No openspec/changes/ directory
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/foo.py")
    assert proc.returncode == 0, proc.stderr


def test_hook_writes_canonical_error_shape(tmp_path: Path) -> None:
    """Block message follows error-message-standard.md WHY/FIX/OVERRIDE shape."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook(hook, project, "backend/foo.py")
    assert proc.returncode == 2
    stderr = proc.stderr
    # Required sigil + sections
    assert "❌" in stderr
    assert "FIX" in stderr
    assert "OVERRIDE" in stderr
    # Slice id surfaces
    assert "demo-slice" in stderr
