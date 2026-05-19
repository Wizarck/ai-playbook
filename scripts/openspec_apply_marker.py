"""Append-only marker for OpenSpec apply-phase orchestration.

Slice: enforce-apply-skill (v0.14.0).

Writes a JSONL audit record per session+event to
`openspec/changes/<change-id>/.apply_log.jsonl`. The PreToolUse hook
(`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`) reads
this marker to allow Edit/Write on a slice's `write_paths` only when an
`openspec-apply-change` skill session has signalled `start` first.

Contracts:
- docs/rules/apply-skill-enforcement.rule.md §1 (marker contract)
- docs/rules/error-message-standard.rule.md (error shape)
- docs/rules/break-glass.rule.md (override flow consumed elsewhere; this script just
  appends an `override` record when a caller invokes it).

CLI
---
    python -m scripts.openspec_apply_marker start --change-id <id>
                                            [--session-id <id>]
                                            [--skill-version <ver>]
    python -m scripts.openspec_apply_marker stop  --change-id <id>
                                            --outcome {completed|aborted|blocked-by-spec}
                                            [--tasks-completed N --tasks-total M]
                                            [--session-id <id>]
    python -m scripts.openspec_apply_marker override --change-id <id>
                                            --reason "<text>" --file-path <path>
                                            [--session-id <id>]
    python -m scripts.openspec_apply_marker is_active --change-id <id>
                                            [--session-id <id>]
    python -m scripts.openspec_apply_marker session_started --change-id <id>
                                            [--session-id <id>]
    python -m scripts.openspec_apply_marker list --change-id <id> [--json]

Exit codes
----------
    0 = success / match
    1 = mismatch (is_active / session_started found no record for session)
    2 = error (missing change folder, bad arguments, etc.) — error shape per
        error-message-standard.md
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


MARKER_FILENAME = ".apply_log.jsonl"
DEFAULT_SKILL_VERSION = "1.0"
VALID_OUTCOMES = {"completed", "aborted", "blocked-by-spec"}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(UTC).microsecond // 1000:03d}Z"


def _resolve_project_root(start: Path) -> Path | None:
    """Walk up from `start` until a directory containing `openspec/` is found."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "openspec").is_dir():
            return candidate
    return None


def _resolve_session_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_value = os.environ.get("CLAUDE_SESSION_ID")
    if env_value:
        return env_value
    user = _git_user() or os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    host = socket.gethostname()
    return f"local-{user}-{host}-{os.getpid()}"


def _git_user() -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _resolve_agent() -> str:
    return os.environ.get("CLAUDE_AGENT", "unknown")


def _emit_error(why: str, where: str, fix: str, override: str = "none") -> int:
    print(f"❌ {why} at {where}", file=sys.stderr)
    print(f"   FIX: {fix}", file=sys.stderr)
    print(f"   OVERRIDE: {override}", file=sys.stderr)
    return 2


def _require_change_dir(project_root: Path, change_id: str) -> Path | None:
    change_dir = project_root / "openspec" / "changes" / change_id
    if not change_dir.is_dir():
        return None
    return change_dir


def _marker_path(project_root: Path, change_id: str) -> Path:
    return project_root / "openspec" / "changes" / change_id / MARKER_FILENAME


def _append_record(marker: Path, record: dict) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def _read_records(marker: Path) -> list[dict]:
    if not marker.exists():
        return []
    out: list[dict] = []
    for line in marker.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Best-effort: skip malformed lines (corrupt-line recovery per design.md edge cases)
            continue
    return out


def cmd_start(args: argparse.Namespace, project_root: Path) -> int:
    if _require_change_dir(project_root, args.change_id) is None:
        return _emit_error(
            why=f"OpenSpec change folder missing for `{args.change_id}`",
            where=str(project_root / "openspec" / "changes" / args.change_id),
            fix=(
                f"create the change folder first (e.g. `openspec/changes/{args.change_id}/proposal.md`) "
                "or pass a real change-id."
            ),
        )
    session_id = _resolve_session_id(args.session_id)
    record = {
        "ts": _now_iso(),
        "event": "start",
        "change_id": args.change_id,
        "session_id": session_id,
        "skill_version": args.skill_version,
        "user": _git_user() or "unknown",
        "agent": _resolve_agent(),
    }
    _append_record(_marker_path(project_root, args.change_id), record)
    return 0


def cmd_stop(args: argparse.Namespace, project_root: Path) -> int:
    if _require_change_dir(project_root, args.change_id) is None:
        return _emit_error(
            why=f"OpenSpec change folder missing for `{args.change_id}`",
            where=str(project_root / "openspec" / "changes" / args.change_id),
            fix="ensure the change exists before calling stop.",
        )
    if args.outcome not in VALID_OUTCOMES:
        return _emit_error(
            why=f"outcome `{args.outcome}` is not one of {sorted(VALID_OUTCOMES)}",
            where="argparse",
            fix=f"pass one of: {', '.join(sorted(VALID_OUTCOMES))}.",
        )
    session_id = _resolve_session_id(args.session_id)
    record: dict = {
        "ts": _now_iso(),
        "event": "stop",
        "change_id": args.change_id,
        "session_id": session_id,
        "outcome": args.outcome,
    }
    if args.tasks_completed is not None:
        record["tasks_completed"] = args.tasks_completed
    if args.tasks_total is not None:
        record["tasks_total"] = args.tasks_total
    _append_record(_marker_path(project_root, args.change_id), record)
    return 0


def cmd_override(args: argparse.Namespace, project_root: Path) -> int:
    if _require_change_dir(project_root, args.change_id) is None:
        return _emit_error(
            why=f"OpenSpec change folder missing for `{args.change_id}`",
            where=str(project_root / "openspec" / "changes" / args.change_id),
            fix="ensure the change exists before recording an override.",
        )
    if len(args.reason.strip()) < 10:
        return _emit_error(
            why="override reason must be at least 10 chars (per break-glass.md MIN_REASON_LEN)",
            where="argparse --reason",
            fix='pass --reason "<≥10-char justification>".',
        )
    session_id = _resolve_session_id(args.session_id)
    record = {
        "ts": _now_iso(),
        "event": "override",
        "change_id": args.change_id,
        "session_id": session_id,
        "reason": args.reason.strip()[:120],
        "file_path": args.file_path,
    }
    _append_record(_marker_path(project_root, args.change_id), record)
    return 0


def cmd_is_active(args: argparse.Namespace, project_root: Path) -> int:
    session_id = _resolve_session_id(args.session_id)
    records = _read_records(_marker_path(project_root, args.change_id))
    starts = [r for r in records if r.get("event") == "start" and r.get("session_id") == session_id]
    stops = [r for r in records if r.get("event") == "stop" and r.get("session_id") == session_id]
    # Active = at least one start and no later stop for the same session
    if not starts:
        return 1
    last_start = starts[-1]
    later_stop = [s for s in stops if s["ts"] >= last_start["ts"]]
    return 1 if later_stop else 0


def cmd_session_started(args: argparse.Namespace, project_root: Path) -> int:
    session_id = _resolve_session_id(args.session_id)
    records = _read_records(_marker_path(project_root, args.change_id))
    matches = [
        r for r in records
        if r.get("event") == "start" and r.get("session_id") == session_id
    ]
    return 0 if matches else 1


def cmd_list(args: argparse.Namespace, project_root: Path) -> int:
    records = _read_records(_marker_path(project_root, args.change_id))
    if args.json:
        for rec in records:
            print(json.dumps(rec, separators=(",", ":")))
    else:
        for rec in records:
            print(
                f"{rec.get('ts','?')} {rec.get('event','?'):<8} "
                f"session={rec.get('session_id','?')} "
                + (f"outcome={rec.get('outcome')}" if rec.get("event") == "stop" else "")
                + (f"file={rec.get('file_path')}" if rec.get("event") == "override" else "")
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openspec_apply_marker",
        description="Append-only marker for OpenSpec apply-phase orchestration.",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    common_change = argparse.ArgumentParser(add_help=False)
    common_change.add_argument("--change-id", required=True)
    common_change.add_argument("--session-id", default=None)

    p_start = subparsers.add_parser("start", parents=[common_change])
    p_start.add_argument("--skill-version", default=DEFAULT_SKILL_VERSION)

    p_stop = subparsers.add_parser("stop", parents=[common_change])
    p_stop.add_argument("--outcome", required=True)
    p_stop.add_argument("--tasks-completed", type=int, default=None)
    p_stop.add_argument("--tasks-total", type=int, default=None)

    p_over = subparsers.add_parser("override", parents=[common_change])
    p_over.add_argument("--reason", required=True)
    p_over.add_argument("--file-path", required=True)

    subparsers.add_parser("is_active", parents=[common_change])
    subparsers.add_parser("session_started", parents=[common_change])

    p_list = subparsers.add_parser("list", parents=[common_change])
    p_list.add_argument("--json", action="store_true")

    return parser


DISPATCH = {
    "start": cmd_start,
    "stop": cmd_stop,
    "override": cmd_override,
    "is_active": cmd_is_active,
    "session_started": cmd_session_started,
    "list": cmd_list,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = _resolve_project_root(Path.cwd())
    if project_root is None:
        return _emit_error(
            why="no `openspec/` directory found from cwd up the tree",
            where=str(Path.cwd()),
            fix="cd into a repo that has an `openspec/` directory at its root.",
        )
    return DISPATCH[args.cmd](args, project_root)


if __name__ == "__main__":
    sys.exit(main())
