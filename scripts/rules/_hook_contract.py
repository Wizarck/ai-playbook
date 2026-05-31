"""In-process L1 hook contract (D21 — dispatcher-executed rules).

A rule that wants to run as an in-process PreToolUse/PostToolUse hook (executed
by ``scripts/hook_dispatcher.py`` rather than as a CLI subprocess) exposes a
module-level function::

    def pretooluse(event: dict) -> HookVerdict | None: ...
    def posttooluse(event: dict) -> HookVerdict | None: ...

Return ``None`` (or ``allow()``) when the rule has nothing to say about this
event — the dispatcher treats that as allow. Return ``block(msg)`` to veto the
tool call (the dispatcher exits non-zero so Claude Code blocks it and shows the
message), or ``warn(msg)`` to surface a non-blocking note.

Rules WITHOUT these functions (the git/PR/session validators) are simply not
executed by the dispatcher; they keep their CLI ``validate`` enforcement via
CI + pre-commit.

Stdlib-only: this module is imported on the hot path (≤50ms SLA) and inside
consumer subprocesses that ship only the ``.ai-playbook`` submodule.
"""
from __future__ import annotations

from dataclasses import dataclass

ALLOW = "allow"
BLOCK = "block"
WARN = "warn"


@dataclass
class HookVerdict:
    verdict: str = ALLOW          # "allow" | "block" | "warn"
    message: str = ""             # shown to the user/model on block or warn

    @property
    def blocked(self) -> bool:
        return self.verdict == BLOCK


def allow() -> HookVerdict:
    return HookVerdict(ALLOW)


def block(message: str) -> HookVerdict:
    return HookVerdict(BLOCK, message)


def warn(message: str) -> HookVerdict:
    return HookVerdict(WARN, message)


# ---------------------------------------------------------------------------
# Event accessors — normalise the PreToolUse/PostToolUse payload Claude Code
# pipes on stdin: {tool_name, tool_input: {file_path, content, new_string,
# command, edits[]}, session_id, cwd, ...}. Mirrors the bespoke
# openspec-apply-enforce hook so the two stay consistent.
# ---------------------------------------------------------------------------


def tool_name(event: dict) -> str:
    return str(event.get("tool_name") or event.get("tool") or "")


def tool_input(event: dict) -> dict:
    ti = event.get("tool_input") or event.get("params")
    return ti if isinstance(ti, dict) else {}


def edited_path(event: dict) -> str:
    return str(tool_input(event).get("file_path") or "")


def edited_text(event: dict) -> str:
    """Best-effort new content from an Edit / Write / MultiEdit event."""
    ti = tool_input(event)
    if "content" in ti:                      # Write
        return str(ti.get("content") or "")
    if "new_string" in ti:                   # Edit
        return str(ti.get("new_string") or "")
    edits = ti.get("edits")                  # MultiEdit
    if isinstance(edits, list):
        return "\n".join(
            str(e.get("new_string") or "") for e in edits if isinstance(e, dict)
        )
    return ""


def bash_command(event: dict) -> str:
    return str(tool_input(event).get("command") or "")


__all__ = [
    "ALLOW", "BLOCK", "WARN", "HookVerdict", "allow", "block", "warn",
    "tool_name", "tool_input", "edited_path", "edited_text", "bash_command",
]
