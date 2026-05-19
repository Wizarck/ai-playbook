"""Telemetry wrapper for L1 rule CLI scripts (Slice v0.19.1).

Each ``scripts/rules/<slug>.rule.py`` ends with::

    if __name__ == "__main__":
        from scripts.rules._telemetry import cli_emit
        raise SystemExit(cli_emit("<slug>", main))

``cli_emit`` times the rule's ``main()`` call, maps its exit code to a
``rule-event/v1`` verdict, and appends one JSONL row via
``scripts.telemetry.rule_event_logger.log_event``. Logging is fail-safe — any
exception from the logger is swallowed; the rule's exit code is never
altered by telemetry side-effects.

Verdict mapping
---------------

* ``rc == 0`` → ``verdict="allow"``  — rule passed.
* ``rc == 1`` → ``verdict="block"``  — rule found a violation.
* ``rc >= 2`` → ``verdict="warn"``   — schema break / fatal (could not evaluate).

Environment passthrough
-----------------------

The wrapper reads three optional env vars to enrich the event without
changing the rule's CLI contract:

* ``AI_PLAYBOOK_LLM`` — model identifier (default ``"unknown"``).
* ``AI_PLAYBOOK_HOOK_TRIGGER`` — hook label, e.g. ``PreToolUse:Edit``
  (default ``"cli:direct"`` for direct invocations).
* ``CLAUDE_CODE_SESSION_ID`` (preferred) or ``AI_PLAYBOOK_SESSION_ID``
  (fallback) — raw session id; hashed by the logger before storage.

Public API: ``cli_emit(slug, main_fn, argv=None)``.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable

__all__ = ["cli_emit", "verdict_from_rc"]


def verdict_from_rc(rc: int) -> str:
    """Map an L1 rule script exit code to a ``rule-event/v1`` verdict literal."""
    if rc == 0:
        return "allow"
    if rc == 1:
        return "block"
    return "warn"


def cli_emit(
    slug: str,
    main_fn: Callable[..., int],
    argv: list[str] | None = None,
) -> int:
    """Invoke ``main_fn(argv)``, log one telemetry event, return the rc.

    Fail-safe: any telemetry-side exception is silently swallowed so the
    rule's own exit code reaches the caller unchanged.
    """
    start = time.monotonic()
    rc = main_fn(argv) if argv is not None else main_fn()
    latency_ms = (time.monotonic() - start) * 1000.0

    try:
        from scripts.telemetry.rule_event_logger import log_event

        log_event(
            slug=slug,
            llm=os.environ.get("AI_PLAYBOOK_LLM", "unknown"),
            verdict=verdict_from_rc(rc),
            latency_ms=latency_ms,
            trigger=os.environ.get("AI_PLAYBOOK_HOOK_TRIGGER", "cli:direct"),
            session_id=(
                os.environ.get("CLAUDE_CODE_SESSION_ID")
                or os.environ.get("AI_PLAYBOOK_SESSION_ID")
                or ""
            ),
            self_check=False,
        )
    except Exception:  # noqa: BLE001 — telemetry must never break the rule
        pass

    return rc
