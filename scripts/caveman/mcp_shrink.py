"""Wrap MCP server commands with ``caveman-shrink`` (npm-published proxy).

The wrapping replaces a stdio server's ``command`` + ``args`` with
``npx caveman-shrink -- <original-command> <original-args>...`` so the
proxy intercepts MCP traffic and compresses tool descriptions on the
wire. Result: ~30-50% reduction in tool-description tokens sent on every
turn.

Both ``.mcp.json`` (Claude Code) and ``.gemini/settings.json`` (Gemini CLI)
formats are supported. HTTP / SSE servers (those with ``url``/``httpUrl``
instead of ``command``) are skipped — caveman-shrink wraps stdio only.

Idempotency: an entry that already has ``_caveman_wrapped: true`` is left
alone, so running shrink twice is a no-op. Unwrap restores the original
``command`` + ``args`` from ``_caveman_original``, dropping the marker
keys.

Backup convention: every mutation writes a backup first via
``scripts.caveman.backup`` under area ``mcp``. The backup is the file
state *before* this mutation — restore-from-latest gives back exactly
what was there before.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from scripts.caveman.backup import latest_backup, make_backup  # noqa: E402

SHRINK_BIN = "caveman-shrink"
WRAPPED_MARKER = "_caveman_wrapped"
ORIGINAL_MARKER = "_caveman_original"


# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------


def is_shrink_available() -> bool:
    """Return True if ``npx caveman-shrink --help`` works.

    Use to decide between warn-and-skip vs hard-fail at the CLI level.
    Never used as a precondition inside the wrap functions themselves
    (those don't try to invoke the binary — they only rewrite config).
    """
    try:
        result = subprocess.run(
            ["npx", "-y", SHRINK_BIN, "--help"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Single-entry transformations
# ---------------------------------------------------------------------------


def _is_stdio_entry(entry: dict[str, Any]) -> bool:
    """Heuristic: stdio servers carry ``command``; HTTP/SSE carry ``url``/``httpUrl``."""
    if not isinstance(entry, dict):
        return False
    if "command" not in entry:
        return False
    # Reject entries that ALSO carry a URL — those are weird mixed entries we
    # should not touch.
    return not ("url" in entry or "httpUrl" in entry)


def wrap_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a wrapped copy of ``entry`` (idempotent).

    Stores the original ``command``/``args`` under ``_caveman_original`` so
    ``unwrap_entry`` can reverse cleanly. Adds ``_caveman_wrapped: true``.

    Raises ``ValueError`` if ``entry`` is not a stdio entry (caller should
    pre-filter with ``_is_stdio_entry``).
    """
    if not _is_stdio_entry(entry):
        raise ValueError("wrap_entry only handles stdio entries (with 'command').")
    if entry.get(WRAPPED_MARKER) is True:
        return entry  # idempotent — already wrapped

    original_cmd = entry["command"]
    original_args = list(entry.get("args") or [])
    new_entry = dict(entry)
    new_entry["command"] = "npx"
    new_entry["args"] = ["-y", SHRINK_BIN, "--", original_cmd, *original_args]
    new_entry[WRAPPED_MARKER] = True
    new_entry[ORIGINAL_MARKER] = {"command": original_cmd, "args": original_args}
    return new_entry


def unwrap_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the unwrapped copy of ``entry``, restoring original cmd+args.

    If ``entry`` is not wrapped (no marker), returns it unchanged. Drops
    ``_caveman_wrapped`` and ``_caveman_original`` keys on success.
    """
    if not isinstance(entry, dict):
        return entry
    if entry.get(WRAPPED_MARKER) is not True:
        return entry
    original = entry.get(ORIGINAL_MARKER) or {}
    if not isinstance(original, dict) or "command" not in original:
        # Marker present but no usable original — return entry stripped of
        # markers (best-effort; backup is the safety net).
        cleaned = dict(entry)
        cleaned.pop(WRAPPED_MARKER, None)
        cleaned.pop(ORIGINAL_MARKER, None)
        return cleaned

    new_entry = dict(entry)
    new_entry["command"] = original["command"]
    new_entry["args"] = list(original.get("args") or [])
    new_entry.pop(WRAPPED_MARKER, None)
    new_entry.pop(ORIGINAL_MARKER, None)
    return new_entry


# ---------------------------------------------------------------------------
# Document-level operations
# ---------------------------------------------------------------------------


def _process_doc(
    doc: dict[str, Any],
    *,
    wrap: bool,
) -> tuple[dict[str, Any], int]:
    """Apply wrap or unwrap to every ``mcpServers.<id>`` entry. Returns (doc, count)."""
    if not isinstance(doc, dict):
        return doc, 0
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        return doc, 0
    new_servers: dict[str, Any] = {}
    count = 0
    for sid, entry in servers.items():
        if wrap:
            if _is_stdio_entry(entry) and entry.get(WRAPPED_MARKER) is not True:
                new_servers[sid] = wrap_entry(entry)
                count += 1
            else:
                new_servers[sid] = entry
        else:
            if isinstance(entry, dict) and entry.get(WRAPPED_MARKER) is True:
                new_servers[sid] = unwrap_entry(entry)
                count += 1
            else:
                new_servers[sid] = entry
    new_doc = dict(doc)
    new_doc["mcpServers"] = new_servers
    return new_doc, count


def _read_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(p: Path, doc: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    p.write_text(body, encoding="utf-8")


def shrink_file(project_root: Path, file_path: Path) -> tuple[Path | None, int]:
    """Wrap every stdio MCP entry in ``file_path``. Returns (backup_path, n_wrapped).

    If the file is missing or contains no stdio entries to wrap, returns
    ``(None, 0)`` and never writes a backup.
    """
    doc = _read_json(file_path)
    if doc is None:
        return None, 0
    new_doc, count = _process_doc(doc, wrap=True)
    if count == 0:
        return None, 0
    backup = make_backup(project_root, "mcp", file_path)
    _write_json(file_path, new_doc)
    return backup, count


def restore_file(project_root: Path, file_path: Path) -> tuple[Path | None, int]:
    """Unwrap every wrapped MCP entry in ``file_path``. Returns (backup_path, n_unwrapped).

    Two paths to restoration:
    1. If markers are present, transformed in-place (preferred — works even
       if backups are missing).
    2. Otherwise, restores from the latest .ai-playbook/backups/mcp/ backup
       if one exists for this filename.
    """
    doc = _read_json(file_path)
    if doc is None:
        # Try restore from backup file if no live config.
        bp = latest_backup(project_root, "mcp", file_path.name)
        if bp is not None and bp.is_file():
            shutil.copy2(bp, file_path)
            return bp, 1
        return None, 0

    new_doc, count = _process_doc(doc, wrap=False)
    if count == 0:
        # No markers found — fall back to backup restore (handles case where
        # someone hand-edited the wrapped command lines and lost the markers).
        bp = latest_backup(project_root, "mcp", file_path.name)
        if bp is not None and bp.is_file():
            shutil.copy2(bp, file_path)
            return bp, 1
        return None, 0

    backup = make_backup(project_root, "mcp", file_path)
    _write_json(file_path, new_doc)
    return backup, count


def shrink_project(project_root: Path) -> dict[str, Any]:
    """Wrap both ``.mcp.json`` and ``.gemini/settings.json`` in the project.

    Returns a dict suitable for ``--json`` CLI output:
        {
          "claude": {"backup": str|None, "wrapped": int},
          "gemini": {"backup": str|None, "wrapped": int},
        }
    """
    claude = project_root / ".mcp.json"
    gemini = project_root / ".gemini" / "settings.json"
    cbp, ccount = shrink_file(project_root, claude)
    gbp, gcount = shrink_file(project_root, gemini)
    return {
        "claude": {
            "path": claude.as_posix(),
            "backup": cbp.as_posix() if cbp else None,
            "wrapped": ccount,
        },
        "gemini": {
            "path": gemini.as_posix(),
            "backup": gbp.as_posix() if gbp else None,
            "wrapped": gcount,
        },
    }


def restore_project(project_root: Path) -> dict[str, Any]:
    """Unwrap both ``.mcp.json`` and ``.gemini/settings.json``."""
    claude = project_root / ".mcp.json"
    gemini = project_root / ".gemini" / "settings.json"
    cbp, ccount = restore_file(project_root, claude)
    gbp, gcount = restore_file(project_root, gemini)
    return {
        "claude": {
            "path": claude.as_posix(),
            "backup": cbp.as_posix() if cbp else None,
            "unwrapped": ccount,
        },
        "gemini": {
            "path": gemini.as_posix(),
            "backup": gbp.as_posix() if gbp else None,
            "unwrapped": gcount,
        },
    }


__all__ = [
    "SHRINK_BIN",
    "WRAPPED_MARKER",
    "ORIGINAL_MARKER",
    "is_shrink_available",
    "wrap_entry",
    "unwrap_entry",
    "shrink_file",
    "restore_file",
    "shrink_project",
    "restore_project",
]
