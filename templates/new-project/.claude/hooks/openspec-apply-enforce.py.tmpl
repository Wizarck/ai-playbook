#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write/MultiEdit on a slice's write_paths
unless the openspec-apply-change skill has signalled a `start` marker for
the current Claude session.

Shipped with ai-playbook v0.14.0 (slice enforce-apply-skill).

Contracts:
- specs/apply-skill-enforcement.md §2 (hook contract + decision flow)
- specs/error-message-standard.md (block message shape)
- specs/break-glass.md (AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE env)

Adoption notes
--------------
1. Copy this template to `.claude/hooks/openspec-apply-enforce.py` in the
   consumer project (project-local; not a global hook).
2. Register it in `.claude/settings.json` under
   `hooks.PreToolUse[*].matcher = "Edit|Write|MultiEdit"`.
3. Helper script `.ai-playbook/scripts/openspec_apply_marker.py` must be
   reachable from the project root (delivered via the `.ai-playbook` git
   submodule).

This file is plain Python (no template placeholders today; rendering is a
copy). If future placeholders are introduced, document them at the top of
this header.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


MARKER_HELPER_REL = Path(".ai-playbook/scripts/openspec_apply_marker.py")
GATED_TOOLS = {"Edit", "Write", "MultiEdit"}
WRITE_PATHS_HEADING_RE = re.compile(r"^\s*##\s*owns\b.*write_paths", re.IGNORECASE)
NEXT_HEADING_RE = re.compile(r"^\s*##\s+")
BULLET_PATH_RE = re.compile(r"^\s*[*\-]\s+`([^`]+)`")


def _read_stdin_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _project_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "openspec" / "changes").is_dir():
            return candidate
    # No openspec/changes/ found — caller is outside any gated context
    return cwd.resolve()


def _project_relative(project: Path, file_path: str) -> str | None:
    if not file_path:
        return None
    try:
        target = Path(file_path).resolve()
        return str(target.relative_to(project)).replace("\\", "/")
    except ValueError:
        return None


def _parse_write_paths(tasks_md: Path) -> list[str]:
    if not tasks_md.is_file():
        return []
    out: list[str] = []
    in_section = False
    for line in tasks_md.read_text(encoding="utf-8").splitlines():
        if WRITE_PATHS_HEADING_RE.match(line):
            in_section = True
            continue
        if in_section and NEXT_HEADING_RE.match(line):
            break
        if in_section:
            m = BULLET_PATH_RE.match(line)
            if m:
                out.append(m.group(1).strip())
    return out


def _path_matches(target: str, write_path: str) -> bool:
    """Glob-aware match. target and write_path are both project-relative."""
    target = target.replace("\\", "/")
    write_path = write_path.replace("\\", "/")
    if write_path == target:
        return True
    if fnmatch.fnmatchcase(target, write_path):
        return True
    # Treat a bare directory path as a prefix match (e.g. `tests/blueprints/revalid/`)
    return write_path.endswith("/") and target.startswith(write_path)


def _find_matching_changes(project: Path, target_rel: str) -> list[tuple[str, list[str]]]:
    """Return list of (change_id, matched_write_paths) for active changes."""
    matches: list[tuple[str, list[str]]] = []
    changes_root = project / "openspec" / "changes"
    if not changes_root.is_dir():
        return matches
    for child in sorted(changes_root.iterdir()):
        if not child.is_dir():
            continue
        tasks_md = child / "tasks.md"
        if not tasks_md.is_file():
            # Pre-apply phase: no tasks.md yet → not gated
            continue
        write_paths = _parse_write_paths(tasks_md)
        matched = [wp for wp in write_paths if _path_matches(target_rel, wp)]
        if matched:
            matches.append((child.name, matched))
    return matches


def _is_change_own_folder(target_rel: str) -> bool:
    """`openspec/changes/<id>/anything` is part of the change's own metadata — never gated."""
    return target_rel.startswith("openspec/changes/")


def _session_started(project: Path, change_id: str, session_id: str) -> bool:
    helper = project / MARKER_HELPER_REL
    if not helper.is_file():
        # Fail OPEN (allow + warn) when helper script missing; gate is then advisory only
        print(
            f"⚠ apply-enforce: marker helper not found at {helper}; allowing edit",
            file=sys.stderr,
        )
        return True
    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = session_id
    result = subprocess.run(
        [sys.executable, str(helper), "session_started", "--change-id", change_id],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _record_override(project: Path, change_id: str, reason: str, file_path: str, session_id: str) -> None:
    helper = project / MARKER_HELPER_REL
    if not helper.is_file():
        return
    env = os.environ.copy()
    env["CLAUDE_SESSION_ID"] = session_id
    subprocess.run(
        [
            sys.executable,
            str(helper),
            "override",
            "--change-id",
            change_id,
            "--reason",
            reason,
            "--file-path",
            file_path,
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _emit_block(change_id: str, file_path: str) -> int:
    print(
        f"❌ apply phase bypass detected at {file_path}",
        file=sys.stderr,
    )
    print(
        f"   The tool tried to edit a path in the write_paths of `{change_id}`",
        file=sys.stderr,
    )
    print(
        "   but this session has no `start` record in",
        file=sys.stderr,
    )
    print(
        f"   `openspec/changes/{change_id}/.apply_log.jsonl`.",
        file=sys.stderr,
    )
    print(
        f"   FIX: invoke the skill `/openspec-apply-change {change_id}` first,",
        file=sys.stderr,
    )
    print(
        f"        or run `python .ai-playbook/scripts/openspec_apply_marker.py start --change-id {change_id}`.",
        file=sys.stderr,
    )
    print(
        '   OVERRIDE: export AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE="<≥10-char reason>"',
        file=sys.stderr,
    )
    print(
        "   See: specs/apply-skill-enforcement.md §3 (break-glass clause).",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    payload = _read_stdin_payload()
    tool_name = payload.get("tool_name", "")
    if tool_name not in GATED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    cwd = Path(payload.get("cwd") or os.getcwd())

    project = _project_root(cwd)
    target_rel = _project_relative(project, file_path)
    if target_rel is None:
        # Outside project tree — not gated
        return 0
    if _is_change_own_folder(target_rel):
        # Refining proposal/design/tasks for any change is always allowed
        return 0

    matches = _find_matching_changes(project, target_rel)
    if not matches:
        return 0

    override_reason = os.environ.get("AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE", "").strip()

    # Allow if ANY matching change has a session_started record
    for change_id, _wps in matches:
        if _session_started(project, change_id, session_id):
            return 0

    # No matching change has a marker → either override or block
    blocking_change = matches[0][0]
    if override_reason and len(override_reason) >= 10:
        for change_id, _wps in matches:
            _record_override(project, change_id, override_reason, target_rel, session_id)
        return 0

    return _emit_block(blocking_change, target_rel)


if __name__ == "__main__":
    sys.exit(main())
