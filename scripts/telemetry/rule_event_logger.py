"""Rule-event logger (Slice 6, v0.18.2).

Emits one JSONL row per L1 hook fire to `<state-dir>/rule-events.jsonl`.

State directory resolution order:

1. `AI_PLAYBOOK_STATE_DIR` env var (absolute path).
2. `<cwd>/.ai-playbook-state/` (the consumer-side gitignored location).

The logger is fail-safe: if the directory cannot be created or the file
cannot be written, the function silently returns without raising — the
L1 hook contract is "never break the user's tool call".

Daemon rotation: callers may invoke `rotate_if_stale(state_path, retain_days=7)`
to truncate / archive a log older than the retain window. The default behavior
keeps the most recent 7 days inline.

Public API:

    log_event(slug, llm, verdict, latency_ms, *,
              trigger="PreToolUse:Unknown",
              session_id="",
              self_check=False,
              tokens_in=None, tokens_out=None, cache_read_tokens=None,
              escape_hatch=None,
              state_dir=None,
              now=None)

Returns the absolute path of the JSONL file written (or `None` on silent fail).
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .anonymize import hash_session_id, scrub_event

EVENTS_FILENAME = "rule-events.jsonl"
SCHEMA_LITERAL = "rule-event/v1"
DEFAULT_RETAIN_DAYS = 7


def resolve_state_dir(state_dir: Path | str | None = None) -> Path:
    """Resolve the telemetry state directory.

    Precedence: explicit arg → `AI_PLAYBOOK_STATE_DIR` env → `<cwd>/.ai-playbook-state/`.
    """
    if state_dir is not None:
        return Path(state_dir).expanduser().resolve()
    env = os.environ.get("AI_PLAYBOOK_STATE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / ".ai-playbook-state").resolve()


def _iso_now(now: datetime | None = None) -> str:
    dt = now if now is not None else datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # Always emit with a `Z` suffix for cross-tool compatibility.
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event(
    slug: str,
    llm: str,
    verdict: str,
    latency_ms: float,
    *,
    trigger: str = "PreToolUse:Unknown",
    session_id: str = "",
    self_check: bool = False,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cache_read_tokens: int | None = None,
    escape_hatch: str | None = None,
    extra: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a fully-formed event dict (PII-scrubbed, schema-shaped)."""
    event: dict[str, Any] = {
        "schema": SCHEMA_LITERAL,
        "timestamp": _iso_now(now),
        "slug": slug,
        "llm": llm,
        "verdict": verdict,
        "latency_ms": round(float(latency_ms), 3),
        "session_id_hash": hash_session_id(session_id),
        "trigger": trigger,
        "self_check": bool(self_check),
    }
    if tokens_in is not None:
        event["tokens_in"] = int(tokens_in)
    if tokens_out is not None:
        event["tokens_out"] = int(tokens_out)
    if cache_read_tokens is not None:
        event["cache_read_tokens"] = int(cache_read_tokens)
    if escape_hatch:
        event["escape_hatch"] = str(escape_hatch)
    if extra:
        # Merge extras THROUGH the scrub so accidental PII never lands.
        merged = scrub_event({**extra, **event})
        # `extra` cannot overwrite required fields (we re-overlay event).
        merged.update(event)
        return merged
    return event


def log_event(
    slug: str,
    llm: str,
    verdict: str,
    latency_ms: float,
    *,
    trigger: str = "PreToolUse:Unknown",
    session_id: str = "",
    self_check: bool = False,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cache_read_tokens: int | None = None,
    escape_hatch: str | None = None,
    extra: dict[str, Any] | None = None,
    state_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path | None:
    """Append a single rule-event JSONL line. Returns the file path or None on silent fail."""
    try:
        event = build_event(
            slug=slug,
            llm=llm,
            verdict=verdict,
            latency_ms=latency_ms,
            trigger=trigger,
            session_id=session_id,
            self_check=self_check,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read_tokens=cache_read_tokens,
            escape_hatch=escape_hatch,
            extra=extra,
            now=now,
        )
    except Exception:  # noqa: BLE001 — never raise out of the hook path.
        return None

    try:
        target_dir = resolve_state_dir(state_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / EVENTS_FILENAME
        with target.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return target
    except OSError:
        return None


def rotate_if_stale(
    state_dir: Path | str | None = None,
    *,
    retain_days: int = DEFAULT_RETAIN_DAYS,
    now: datetime | None = None,
) -> Path | None:
    """Archive the events file when its mtime is older than `retain_days`.

    Returns the path of the archive (or None when no rotation happened). The
    new events file is created empty.
    """
    target_dir = resolve_state_dir(state_dir)
    events = target_dir / EVENTS_FILENAME
    if not events.is_file():
        return None
    try:
        mtime = datetime.fromtimestamp(events.stat().st_mtime, tz=UTC)
    except OSError:
        return None
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retain_days)
    if mtime >= cutoff:
        return None
    stamp = mtime.strftime("%Y%m%d")
    archive = target_dir / f"{events.stem}.{stamp}.jsonl.archive"
    try:
        shutil.move(str(events), str(archive))
        events.write_text("", encoding="utf-8", newline="\n")
    except OSError:
        return None
    return archive


__all__ = [
    "log_event",
    "build_event",
    "rotate_if_stale",
    "resolve_state_dir",
    "EVENTS_FILENAME",
    "SCHEMA_LITERAL",
]
