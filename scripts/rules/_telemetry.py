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

import logging
import os
import sys
import time
from collections.abc import Callable

__all__ = ["cli_emit", "verdict_from_rc"]

_logger = logging.getLogger(__name__)


def _ensure_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 so rule scripts can emit unicode on Windows.

    Windows defaults to cp1252 for console streams; any rule that prints `→`,
    `❌`, `ℹ`, etc. crashes with ``UnicodeEncodeError``. Swallowed silently
    because under pytest capsys (and similar capture layers) the replacement
    stream does not expose ``reconfigure``; that stream is already capable of
    holding arbitrary unicode without our help.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — never break the rule on stream tweak
            pass


def verdict_from_rc(rc: int) -> str:
    """Map an L1 rule script exit code to a ``rule-event/v1`` verdict literal."""
    if rc == 0:
        return "allow"
    if rc == 1:
        return "block"
    return "warn"


def _toggle_disabled(slug: str) -> bool:
    """Return True if `slug` is OFF at L1 per the consumer's rules-toggle.json.

    Fail-safe to False on any import / IO / parse error — the rule runs normally
    when the toggle subsystem is broken (defensive default: enforce > silent skip).
    """
    try:
        from scripts.rules_toggle import find_project_root, is_rule_disabled
        project = find_project_root()
        if project is None:
            return False
        return is_rule_disabled(project, slug, layer="L1")
    except Exception:  # noqa: BLE001 — never raise out of cli_emit
        return False


def _emit_skipped(slug: str, latency_ms: float) -> None:
    """Emit a `verdict=warn` telemetry event for a rule that was skipped by toggle."""
    try:
        from scripts.telemetry.rule_event_logger import log_event

        log_event(
            slug=slug,
            llm=os.environ.get("AI_PLAYBOOK_LLM", "unknown"),
            verdict="warn",
            latency_ms=latency_ms,
            trigger=os.environ.get("AI_PLAYBOOK_HOOK_TRIGGER", "cli:direct"),
            session_id=(
                os.environ.get("CLAUDE_CODE_SESSION_ID")
                or os.environ.get("AI_PLAYBOOK_SESSION_ID")
                or ""
            ),
            self_check=False,
            extra={"block_class": "rule_disabled", "toggle_layer": "L1"},
        )
    except Exception:  # noqa: BLE001 — telemetry must never break the rule
        _logger.warning("cli_emit(%r) skipped-event drop", slug, exc_info=True)


def cli_emit(
    slug: str,
    main_fn: Callable[..., int],
    argv: list[str] | None = None,
) -> int:
    """Invoke ``main_fn(argv)``, log one telemetry event, return the rc.

    Fail-safe: any telemetry-side exception is silently swallowed so the
    rule's own exit code reaches the caller unchanged.

    Toggle short-circuit: if the consumer's ``rules-toggle.json`` has
    ``rules.<slug>.enabled=false`` (or ``layers.L1=false``), skip ``main_fn``
    entirely, emit a ``verdict=warn`` event with ``block_class=rule_disabled``,
    and return 0.
    """
    _ensure_utf8_streams()
    start = time.monotonic()

    if _toggle_disabled(slug):
        latency_ms = (time.monotonic() - start) * 1000.0
        _emit_skipped(slug, latency_ms)
        return 0

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
        _logger.warning("cli_emit(%r) telemetry drop", slug, exc_info=True)

    return rc
