"""Tests for scripts/openspec_apply_marker.py.

Slice: enforce-apply-skill (v0.14.0). Phase A T1.

Contracts:
- design.md §1 (marker JSONL schema, location, lifecycle)
- design.md §1.3 (CLI surface)
- docs/rules/error-message-standard.rule.md (error shape on failure paths)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Resolve script path relative to repo root (parent of tests/)
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "openspec_apply_marker.py"


def _seed_change(project_root: Path, change_id: str) -> Path:
    """Create the minimum directory structure the marker helper expects."""
    change_dir = project_root / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text(f"# {change_id}\n", encoding="utf-8")
    return change_dir


def _run(
    project_root: Path,
    *args: str,
    session_id: str = "test-session-1",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the marker script with a project_root cwd and explicit session_id."""
    full_env = os.environ.copy()
    full_env["CLAUDE_SESSION_ID"] = session_id
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=project_root,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _marker_lines(project_root: Path, change_id: str) -> list[dict]:
    marker = project_root / "openspec" / "changes" / change_id / ".apply_log.jsonl"
    if not marker.exists():
        return []
    return [
        json.loads(line)
        for line in marker.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_start_creates_marker_with_required_fields(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    proc = _run(tmp_path, "start", "--change-id", "demo-slice")
    assert proc.returncode == 0, proc.stderr
    records = _marker_lines(tmp_path, "demo-slice")
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == "start"
    assert rec["change_id"] == "demo-slice"
    assert rec["session_id"] == "test-session-1"
    assert "ts" in rec
    assert "skill_version" in rec


def test_start_is_idempotent_within_session(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    _run(tmp_path, "start", "--change-id", "demo-slice")
    proc = _run(tmp_path, "start", "--change-id", "demo-slice")
    assert proc.returncode == 0, proc.stderr
    records = _marker_lines(tmp_path, "demo-slice")
    # Two start records — same session, both audit-visible
    assert len(records) == 2
    assert all(r["event"] == "start" for r in records)


def test_stop_records_outcome_and_tasks(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    _run(tmp_path, "start", "--change-id", "demo-slice")
    proc = _run(
        tmp_path,
        "stop",
        "--change-id",
        "demo-slice",
        "--outcome",
        "completed",
        "--tasks-completed",
        "7",
        "--tasks-total",
        "11",
    )
    assert proc.returncode == 0, proc.stderr
    records = _marker_lines(tmp_path, "demo-slice")
    assert any(
        r["event"] == "stop"
        and r["outcome"] == "completed"
        and r["tasks_completed"] == 7
        and r["tasks_total"] == 11
        for r in records
    )


def test_is_active_matches_session(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    _run(tmp_path, "start", "--change-id", "demo-slice", session_id="session-A")
    matching = _run(
        tmp_path, "is_active", "--change-id", "demo-slice", session_id="session-A"
    )
    not_matching = _run(
        tmp_path, "is_active", "--change-id", "demo-slice", session_id="session-B"
    )
    assert matching.returncode == 0
    assert not_matching.returncode != 0


def test_session_started_returns_true_after_start(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    before = _run(tmp_path, "session_started", "--change-id", "demo-slice")
    assert before.returncode != 0
    _run(tmp_path, "start", "--change-id", "demo-slice")
    after = _run(tmp_path, "session_started", "--change-id", "demo-slice")
    assert after.returncode == 0, after.stderr


def test_corrupt_jsonl_is_recoverable(tmp_path: Path) -> None:
    change_dir = _seed_change(tmp_path, "demo-slice")
    marker = change_dir / ".apply_log.jsonl"
    # Mix valid + invalid lines
    marker.write_text(
        '{"event":"start","change_id":"demo-slice","session_id":"test-session-1",'
        '"ts":"2026-05-15T10:00:00Z","skill_version":"1.1"}\n'
        "NOT-JSON-AT-ALL\n"
        '{"event":"stop","change_id":"demo-slice","session_id":"other","outcome":"completed",'
        '"ts":"2026-05-15T11:00:00Z"}\n',
        encoding="utf-8",
    )
    proc = _run(tmp_path, "session_started", "--change-id", "demo-slice")
    # Valid 'start' for test-session-1 still found despite corrupt middle line
    assert proc.returncode == 0, proc.stderr


def test_override_writes_audit_record(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    proc = _run(
        tmp_path,
        "override",
        "--change-id",
        "demo-slice",
        "--reason",
        "post-review-fix touches same file",
        "--file-path",
        "backend/app/foo.py",
    )
    assert proc.returncode == 0, proc.stderr
    records = _marker_lines(tmp_path, "demo-slice")
    overrides = [r for r in records if r["event"] == "override"]
    assert len(overrides) == 1
    assert overrides[0]["reason"] == "post-review-fix touches same file"
    assert overrides[0]["file_path"] == "backend/app/foo.py"


def test_missing_change_folder_errors_per_standard(tmp_path: Path) -> None:
    # No seed; change folder does not exist
    proc = _run(tmp_path, "start", "--change-id", "nonexistent")
    assert proc.returncode != 0
    # error-message-standard.md shape: must include FIX line
    assert "FIX" in proc.stderr or "fix" in proc.stderr.lower()


def test_list_emits_jsonl_records(tmp_path: Path) -> None:
    _seed_change(tmp_path, "demo-slice")
    _run(tmp_path, "start", "--change-id", "demo-slice")
    _run(
        tmp_path,
        "stop",
        "--change-id",
        "demo-slice",
        "--outcome",
        "aborted",
    )
    proc = _run(tmp_path, "list", "--change-id", "demo-slice", "--json")
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert any(r["event"] == "start" for r in lines)
    assert any(r["event"] == "stop" and r["outcome"] == "aborted" for r in lines)
