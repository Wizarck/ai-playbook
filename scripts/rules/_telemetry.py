"""Telemetry wrapper for rule scripts AND direct-CLI helpers.

Each ``scripts/rules/<slug>.rule.py`` ends with::

    if __name__ == "__main__":
        from scripts.rules._telemetry import cli_emit
        raise SystemExit(cli_emit("<slug>", main))

Direct-CLI helpers (``doctor``, ``bootstrap``, ``secrets_scan``, …) end with::

    if __name__ == "__main__":
        from scripts.rules._telemetry import script_emit
        raise SystemExit(script_emit("<slug>", main))

Both paths share the same plumbing — ``script_emit`` is a thin alias that
sets ``kind="script"``. The shared wrapper times ``main()`` and maps its
exit code to a ``rule-event/v2`` verdict, then emits the same observation
through TWO transports:

1. **OTel span** via ``scripts.tracing.trace_emit.span``
   (named ``rule.<slug>``), so the event lands in Langfuse / Tempo / any
   OTLP-compatible backend wired up via ``init_tracing``. Span duration
   carries the latency naturally; ``ai_playbook.rule.*`` attributes carry
   the verdict + trigger + llm so downstream UIs can group/filter.
2. **JSONL row** appended via ``scripts.telemetry.rule_event_logger.log_event``
   to the local ``rule-events.jsonl`` file — works offline, no creds, no
   network, and serves as the source of truth for the monthly
   ``scripts.telemetry.report`` CLI.

Both transports are fail-safe: any exception from either is swallowed and
the caller's exit code is never altered by telemetry side-effects.

Each JSONL row carries a ``kind`` field (``"rule"`` | ``"script"``) so the
monthly ``scripts.telemetry.report`` CLI can split counts between L1 rules
and direct-CLI invocations without losing the unified aggregation surface.

Verdict mapping
---------------

* ``rc == 0`` → ``verdict="allow"``  — rule/script passed.
* ``rc == 1`` → ``verdict="block"``  — rule/script found a violation.
* ``rc >= 2`` → ``verdict="warn"``   — schema break / fatal (could not evaluate).

Environment passthrough
-----------------------

The wrapper reads three optional env vars to enrich the event without
changing the script's CLI contract:

* ``AI_PLAYBOOK_LLM`` — model identifier (default ``"unknown"``).
* ``AI_PLAYBOOK_HOOK_TRIGGER`` — hook label, e.g. ``PreToolUse:Edit``
  (default ``"cli:direct"`` for direct invocations).
* ``CLAUDE_CODE_SESSION_ID`` (preferred) or ``AI_PLAYBOOK_SESSION_ID``
  (fallback) — raw session id; hashed by the logger before storage.

Public API: ``cli_emit(slug, main_fn, argv=None, *, kind="rule")`` and
``script_emit(slug, main_fn, argv=None)`` (alias: ``kind="script"``).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable

__all__ = ["cli_emit", "script_emit", "verdict_from_rc"]

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
    *,
    kind: str = "rule",
) -> int:
    """Invoke ``main_fn(argv)``, emit one telemetry event over OTel + JSONL,
    return the rc.

    ``kind="rule"`` (default) preserves the historical contract for the 41
    ``*.rule.py`` callers. ``kind="script"`` is for direct-CLI helpers wrapped
    via :func:`script_emit` — both paths share the same JSONL surface so the
    monthly report can aggregate or split as needed.

    Fail-safe: any telemetry-side exception is silently swallowed so the
    caller's own exit code reaches the caller unchanged.

    Toggle short-circuit: if the consumer's ``rules-toggle.json`` has
    ``rules.<slug>.enabled=false`` (or ``layers.L1=false``), skip ``main_fn``
    entirely, emit a ``verdict=warn`` event with ``block_class=rule_disabled``,
    and return 0.
    """
    _ensure_utf8_streams()

    trigger = os.environ.get("AI_PLAYBOOK_HOOK_TRIGGER", "cli:direct")
    llm = os.environ.get("AI_PLAYBOOK_LLM", "unknown")

    # OTel span wraps the rule execution so its duration is the span duration
    # and any spans the rule itself creates become children. `trace_emit.span`
    # yields a no-op-safe span when OTel is not installed/initialised — so
    # this branch never throws and never alters `rc`.
    try:
        from scripts.tracing import trace_emit

        span_cm = trace_emit.span(
            f"rule.{slug}",
            {
                "ai_playbook.rule.slug": slug,
                "ai_playbook.rule.trigger": trigger,
                "ai_playbook.rule.llm": llm,
            },
        )
    except Exception:  # noqa: BLE001 — defensive: tracing import path is optional
        from contextlib import nullcontext

        span_cm = nullcontext(None)

    start = time.monotonic()

    if _toggle_disabled(slug):
        latency_ms = (time.monotonic() - start) * 1000.0
        _emit_skipped(slug, latency_ms)
        return 0

    with span_cm as otel_span:
        rc = main_fn(argv) if argv is not None else main_fn()
        latency_ms = (time.monotonic() - start) * 1000.0
        verdict = verdict_from_rc(rc)

        # Annotate the span post-hoc with the outcome. set_attribute is a
        # no-op on the stand-in span returned when OTel is unavailable, so
        # the guard is purely defensive against future Tracer SDK changes.
        if otel_span is not None:
            try:
                otel_span.set_attribute("ai_playbook.rule.verdict", verdict)
                otel_span.set_attribute(
                    "ai_playbook.rule.latency_ms", round(latency_ms, 3)
                )
            except Exception:  # noqa: BLE001
                pass

    try:
        from scripts.telemetry.rule_event_logger import log_event

        log_event(
            slug=slug,
            llm=llm,
            verdict=verdict,
            latency_ms=latency_ms,
            trigger=trigger,
            session_id=(
                os.environ.get("CLAUDE_CODE_SESSION_ID")
                or os.environ.get("AI_PLAYBOOK_SESSION_ID")
                or ""
            ),
            self_check=False,
            extra={"kind": kind},
        )
    except Exception:  # noqa: BLE001 — telemetry must never break the rule
        _logger.warning("cli_emit(%r) telemetry drop", slug, exc_info=True)

    return rc


def script_emit(
    slug: str,
    main_fn: Callable[..., int],
    argv: list[str] | None = None,
) -> int:
    """Direct-CLI counterpart of :func:`cli_emit` — sets ``kind="script"``."""
    return cli_emit(slug, main_fn, argv, kind="script")
