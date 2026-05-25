"""Tests for the PreToolUse hook template
`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`.

Slice: enforce-apply-skill (v0.14.0). Phase B T4.

Strategy
--------
The template is a Python script with `{{PLACEHOLDER}}`-style substitutions for
project-specific values. Tests render the template into a temp project, then
invoke the rendered script as a subprocess, feeding synthetic Claude Code
hook input on stdin and asserting exit code + stderr per the canonical error
shape (per `docs/rules/error-message-standard.rule.md`).

Contracts:
- design.md §2 (hook contract)
- design.md §2.2 (decision flow)
- design.md §2.3 (canonical error message)
- docs/rules/break-glass.rule.md (override env)
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def _invoke_hook_bash(
    hook: Path,
    project: Path,
    command: str,
    *,
    session_id: str = "test-session-1",
    override: str | None = None,
    bash_inspection: str | None = None,
    state_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the rendered hook with a Bash tool payload.

    Bash payloads carry `tool_input.command`, not `file_path`. The hook
    must inspect the command string heuristically and decide allow/block
    based on whether any extracted target path falls under a declared
    write_path without a session marker.
    """
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project),
        "session_id": session_id,
    }
    env = os.environ.copy()
    env.pop("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", None)
    env.pop("AIPLAYBOOK_BASH_INSPECTION", None)
    env["CLAUDE_SESSION_ID"] = session_id
    # Inject PYTHONPATH so the hook can import scripts.telemetry from the
    # upstream repo (consumers receive this via the .ai-playbook submodule
    # in production; tests use the source-of-truth modules directly).
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(REPO_ROOT)
    )
    if override is not None:
        env["AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE"] = override
    if bash_inspection is not None:
        env["AIPLAYBOOK_BASH_INSPECTION"] = bash_inspection
    if state_dir is not None:
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


def _read_telemetry_events(state_dir: Path) -> list[dict]:
    """Read all rule-event JSONL rows written under state_dir/rule-events.jsonl."""
    events_path = state_dir / "rule-events.jsonl"
    if not events_path.is_file():
        return []
    rows: list[dict] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _invoke_hook(
    hook: Path,
    project: Path,
    file_path: str,
    *,
    tool_name: str = "Edit",
    session_id: str = "test-session-1",
    override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the rendered hook script in a hermetic env.

    Test isolation note (slice doc-drift-enforcement, v0.16.0):
    The parent test process may inherit `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE`
    from a wrapper harness (e.g. a worker-orchestration session that sets the
    env to signal "background work — auto-override the apply-skill gate").
    That inheritance is correct for the harness but POLLUTES this test:
    every "expect a block" assertion would silently pass through the
    legitimate override path in the hook (`docs/rules/apply-skill-enforcement.rule.md`
    §3) and report exit 0 instead of the expected block (exit 2).

    Fix: drop the override env explicitly. When a test wants to exercise the
    override path, it passes `override="..."` and we set it back.
    """
    payload = {
        "tool_name": tool_name,
        "tool_input": {"file_path": str(project / file_path)},
        "cwd": str(project),
        "session_id": session_id,
    }
    env = os.environ.copy()
    env.pop("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", None)
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


# ---------------------------------------------------------------------------
# Bash heuristic tests (v0.20.0+)
#
# The hook intercepts Bash tool_input.command and extracts candidate write
# targets via regex. High-confidence matches against declared write_paths
# without a session marker block (exit 2); ambiguous commands and commands
# not touching declared paths pass (exit 0).
# ---------------------------------------------------------------------------


def test_hook_blocks_bash_redirect_write_to_write_path(tmp_path: Path) -> None:
    """`echo "x" > backend/foo.py` writes to a declared write_path → block."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, 'echo "x" > backend/foo.py')
    assert proc.returncode == 2, proc.stderr
    assert "Bash command writes to declared write_path" in proc.stderr
    assert "demo-slice" in proc.stderr


def test_hook_blocks_bash_sed_inplace_to_write_path(tmp_path: Path) -> None:
    """`sed -i 's/a/b/' backend/foo.py` → block with pattern_kind=sed-i."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "sed -i 's/a/b/' backend/foo.py")
    assert proc.returncode == 2, proc.stderr
    assert "sed-i" in proc.stderr


def test_hook_blocks_bash_python_c_open_write(tmp_path: Path) -> None:
    """python -c "open('path', 'w').write(...)" → block with pattern_kind=python-c-open."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(
        hook, project,
        "python -c \"open('backend/foo.py', 'w').write('hi')\"",
    )
    assert proc.returncode == 2, proc.stderr
    assert "python-c-open" in proc.stderr


def test_hook_blocks_bash_tee_to_write_path(tmp_path: Path) -> None:
    """`echo x | tee backend/foo.py` → block."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "echo x | tee backend/foo.py")
    assert proc.returncode == 2, proc.stderr
    assert "tee" in proc.stderr


def test_hook_blocks_bash_powershell_setcontent(tmp_path: Path) -> None:
    """`Set-Content -Path backend/foo.py "x"` (PowerShell) → block."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(
        hook, project, 'Set-Content -Path backend/foo.py "hello"',
    )
    assert proc.returncode == 2, proc.stderr
    assert "powershell-setcontent" in proc.stderr


def test_hook_blocks_bash_powershell_outfile(tmp_path: Path) -> None:
    """`"x" | Out-File backend/foo.py` (PowerShell) → block."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(
        hook, project, '"x" | Out-File backend/foo.py',
    )
    assert proc.returncode == 2, proc.stderr
    assert "powershell-outfile" in proc.stderr


def test_hook_allows_bash_redirect_outside_write_paths(tmp_path: Path) -> None:
    """`echo x > /tmp/scratch` (outside declared write_paths) → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "echo x > /tmp/scratch")
    assert proc.returncode == 0, f"unrelated path should pass; stderr={proc.stderr}"


def test_hook_allows_bash_git_status(tmp_path: Path) -> None:
    """`git status` (no mutation pattern) → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "git status")
    assert proc.returncode == 0, proc.stderr


def test_hook_allows_bash_python_c_read_only(tmp_path: Path) -> None:
    """`python -c "print('hi')"` (no write mode) → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "python -c \"print('hi')\"")
    assert proc.returncode == 0, proc.stderr


def test_hook_allows_bash_when_marker_present(tmp_path: Path) -> None:
    """Bash redirect to write_path WITH marker → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    marker = project / "openspec" / "changes" / "demo-slice" / ".apply_log.jsonl"
    marker.write_text(
        '{"event":"start","change_id":"demo-slice","session_id":"test-session-1",'
        '"ts":"2026-05-25T10:00:00.000Z","skill_version":"1.1"}\n',
        encoding="utf-8",
    )
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, 'echo "x" > backend/foo.py')
    assert proc.returncode == 0, proc.stderr


def test_hook_feature_flag_disables_bash_branch(tmp_path: Path) -> None:
    """AIPLAYBOOK_BASH_INSPECTION=0 skips Bash inspection entirely → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(
        hook, project, 'echo "x" > backend/foo.py',
        bash_inspection="0",
    )
    assert proc.returncode == 0, (
        f"AIPLAYBOOK_BASH_INSPECTION=0 should bypass Bash gate; stderr={proc.stderr}"
    )


def test_hook_honours_bash_override_env(tmp_path: Path) -> None:
    """AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE allows a Bash bypass + audits it."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(
        hook, project, 'echo "x" > backend/foo.py',
        override="emergency post-review hotfix",
    )
    assert proc.returncode == 0, proc.stderr
    marker = project / "openspec" / "changes" / "demo-slice" / ".apply_log.jsonl"
    assert marker.is_file()
    records = [
        json.loads(line)
        for line in marker.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    overrides = [r for r in records if r.get("event") == "override"]
    assert len(overrides) == 1
    assert "emergency" in overrides[0]["reason"]


def test_hook_allows_bash_ambiguous_with_no_match(tmp_path: Path) -> None:
    """Command without recognisable mutation pattern → allow."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    proc = _invoke_hook_bash(hook, project, "ls -la backend/foo.py")
    assert proc.returncode == 0, proc.stderr


def test_hook_emits_telemetry_on_bash_block(tmp_path: Path) -> None:
    """Bash block emits a rule-event JSONL row with verdict=block and pattern_kind."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "ai-playbook-state"
    proc = _invoke_hook_bash(
        hook, project, "sed -i 's/a/b/' backend/foo.py",
        state_dir=state_dir,
    )
    assert proc.returncode == 2, proc.stderr
    events = _read_telemetry_events(state_dir)
    block_events = [e for e in events if e.get("verdict") == "block"]
    assert len(block_events) == 1, f"expected 1 block event, got {events}"
    ev = block_events[0]
    assert ev["slug"] == "apply-skill-enforcement"
    assert ev["trigger"] == "PreToolUse:Bash"
    # Schema v2 fields (passed via extra; logger merges them).
    assert ev.get("block_class") == "apply_phase_bypass"
    assert ev.get("block_tool") == "Bash"
    assert ev.get("bash_pattern_kind") == "sed-i"
    assert ev.get("change_id") == "demo-slice"
    assert ev.get("target_rel") == "backend/foo.py"
    assert ev.get("marker_present") is False


def test_hook_emits_telemetry_on_edit_block(tmp_path: Path) -> None:
    """Edit block emits rule-event with block_tool=Edit and no bash_pattern_kind."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "ai-playbook-state"
    env = os.environ.copy()
    env.pop("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", None)
    env["CLAUDE_SESSION_ID"] = "test-session-1"
    env["AI_PLAYBOOK_STATE_DIR"] = str(state_dir)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(REPO_ROOT)
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(project / "backend/foo.py")},
        "cwd": str(project),
        "session_id": "test-session-1",
    }
    proc = subprocess.run(
        [sys.executable, str(hook)],
        cwd=project, env=env, input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert proc.returncode == 2, proc.stderr
    events = _read_telemetry_events(state_dir)
    block = next((e for e in events if e.get("verdict") == "block"), None)
    assert block is not None, f"expected block event; got {events}"
    assert block["trigger"] == "PreToolUse:Edit"
    assert block.get("block_tool") == "Edit"
    assert block.get("bash_pattern_kind") is None
    assert block.get("change_id") == "demo-slice"


def test_hook_emits_telemetry_on_allow(tmp_path: Path) -> None:
    """Non-blocking decisions also emit telemetry (with block_class=none)."""
    project = _seed_project(tmp_path)
    _seed_change(project, "demo-slice", ["backend/foo.py"])
    hook = _render_template(project / ".claude" / "hooks" / "openspec-apply-enforce.py")
    state_dir = tmp_path / "ai-playbook-state"
    proc = _invoke_hook_bash(hook, project, "git status", state_dir=state_dir)
    assert proc.returncode == 0
    events = _read_telemetry_events(state_dir)
    allow = next((e for e in events if e.get("verdict") == "allow"), None)
    assert allow is not None, f"expected allow event; got {events}"
    assert allow["trigger"] == "PreToolUse:Bash"
    assert allow.get("block_class") == "none"
