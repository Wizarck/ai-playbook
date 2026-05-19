"""Anonymization helpers for telemetry events (Slice 6, v0.18.2).

Two responsibilities:

1. `hash_session_id(session_id)` — one-way hash so the raw session_id never
   lands in the JSONL log. sha256(session_id.encode())[:8] hex chars.
2. `scrub_event(event)` — defense-in-depth shape lint. Removes any key whose
   name suggests file paths, diff content, raw messages, or other PII before
   the logger writes the row.

Both functions are pure stdlib (no external deps) and never raise.

Privacy invariants verified by `tests/test_telemetry_privacy.py`:

- session_id is hashed to exactly 8 hex characters.
- No keys named `file_path` / `path` / `directory` survive.
- No keys named `diff` / `content` / `body` / `message` survive.
- The unhashed session_id is never present in any output dict.
"""
from __future__ import annotations

import hashlib
from typing import Any

# Keys that may carry PII (file content / diffs / paths / raw messages).
# The logger strips any of these before writing. The list is allow-list-by-default:
# the canonical event schema only permits the fields enumerated in
# schemas/schema-rule-event-v1.json, but we keep this denylist as a second-line
# guard in case the caller hands the logger a richer dict.
_PII_KEYS: frozenset[str] = frozenset(
    {
        "file_path",
        "filepath",
        "path",
        "directory",
        "dir",
        "diff",
        "content",
        "body",
        "message",
        "messages",
        "user_message",
        "raw_input",
        "tool_input",
        "stdin",
        "session_id",  # raw — only the hash is ever written.
    }
)


def hash_session_id(session_id: str) -> str:
    """Return sha256(session_id)[:8] hex chars.

    Empty / None inputs return the literal `"00000000"` so the event still
    validates against the schema's `^[0-9a-f]{8}$` pattern. Tests cover the
    collision-resistance over typical Claude/Gemini session ID populations.
    """
    if not session_id:
        return "00000000"
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return digest[:8]


def scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `event` with any PII-named keys removed.

    This is a SHAPE check, not a content check — we do not inspect values for
    secret patterns (that's `scripts/secrets_scan.py`'s job). The contract is:
    if the dispatcher accidentally hands the logger a `file_path` key, this
    function drops it before the row is written.
    """
    if not isinstance(event, dict):
        return {}
    return {k: v for k, v in event.items() if k not in _PII_KEYS}


__all__ = ["hash_session_id", "scrub_event"]
