"""Helpers to emit OTel spans with `gen_ai.*` + `ai_playbook.*` attributes.

This module provides:

- ``span(name, attrs=None)`` — context manager that starts a current span and
  tolerates tracing being disabled (yields a no-op span instead of raising).
- ``current_trace_id()`` — hex trace id (32 hex chars / 16 bytes) or ``None``.
- ``add_event(name, attrs=None)`` — attach an event to the current span.
- ``gen_ai_attrs(...)`` — canonical ``gen_ai.*`` dict per OTel Semantic
  Conventions for Generative AI (see `specs/model-routing.md` §4).
- ``routing_attrs(...)`` — canonical ``ai_playbook.routing.*`` dict.
- ``degradation_attrs(...)`` — canonical ``ai_playbook.degradation.*`` dict.
- ``override_attrs(...)`` — canonical ``ai_playbook.override.*`` dict
  (per `specs/break-glass.md`).

All helpers return plain dicts so callers can merge them into whatever span
creation API they prefer. The no-op behaviour is imported lazily — this module
stays importable even without ``opentelemetry`` installed.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Force UTF-8 stdio for consistency with the rest of the toolchain.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


def _get_trace_module() -> Any | None:
    """Return the ``opentelemetry.trace`` module if importable, else ``None``."""
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
    except ImportError:
        return None
    return trace


@contextmanager
def span(name: str, attrs: dict[str, Any] | None = None) -> Iterator[Any]:
    """Yield a current span. No-op safe when OTel isn't available or disabled.

    Usage::

        with span("qa.verdict", {"severity": "S1"}) as s:
            s.set_attribute("track", "blind-hunter")
            ...
    """
    trace = _get_trace_module()
    if trace is None:
        # No OTel installed — yield a tiny stand-in.
        yield _NoOpSpan()
        return

    tracer = trace.get_tracer("ai-playbook")
    # Some OTel versions differ on kwarg support for attributes; stay permissive.
    ctx_manager = tracer.start_as_current_span(name)
    s = ctx_manager.__enter__()
    try:
        if attrs:
            for k, v in attrs.items():
                try:
                    s.set_attribute(k, v)
                except Exception:  # noqa: BLE001 — never crash the caller
                    pass
        yield s
    finally:
        try:
            ctx_manager.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


def current_trace_id() -> str | None:
    """Return the current span's trace id as a 32-char hex string, or None."""
    trace = _get_trace_module()
    if trace is None:
        return None
    try:
        current = trace.get_current_span()
        if current is None:
            return None
        ctx = current.get_span_context()
        if ctx is None or not getattr(ctx, "is_valid", False):
            return None
        return f"{ctx.trace_id:032x}"
    except Exception:  # noqa: BLE001
        return None


def add_event(name: str, attrs: dict[str, Any] | None = None) -> None:
    """Attach an event to the current span. No-op safe."""
    trace = _get_trace_module()
    if trace is None:
        return
    try:
        current = trace.get_current_span()
        if current is None:
            return
        current.add_event(name, attributes=attrs or {})
    except Exception:  # noqa: BLE001
        return


# ---------------------------------------------------------------------------
# Semantic-convention helpers — build plain dicts, return them.
# Attribute names are CANONICAL; do not invent new prefixes.
# ---------------------------------------------------------------------------


def gen_ai_attrs(
    model: str,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    cache_read: int = 0,
    *,
    response_model: str | None = None,
) -> dict[str, Any]:
    """Return the OTel Semantic-Conv `gen_ai.*` attribute set.

    Keys per `specs/model-routing.md` §4:
      - ``gen_ai.system``
      - ``gen_ai.request.model``
      - ``gen_ai.response.model`` (optional; defaults to ``model``)
      - ``gen_ai.usage.input_tokens``
      - ``gen_ai.usage.output_tokens``
      - ``gen_ai.usage.cache_read_input_tokens``
    """
    return {
        "gen_ai.system": provider,
        "gen_ai.request.model": model,
        "gen_ai.response.model": response_model or model,
        "gen_ai.usage.input_tokens": int(tokens_in),
        "gen_ai.usage.output_tokens": int(tokens_out),
        "gen_ai.usage.cache_read_input_tokens": int(cache_read),
    }


def routing_attrs(
    task_class: str,
    fallback_depth: int = 0,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return the `ai_playbook.task_class` + `ai_playbook.routing.*` set.

    Keys per `specs/model-routing.md` §4.
    """
    out: dict[str, Any] = {
        "ai_playbook.task_class": task_class,
        "ai_playbook.routing.fallback_depth": int(fallback_depth),
    }
    if reason:
        out["ai_playbook.routing.reason"] = reason
    return out


def degradation_attrs(
    state: str,
    reason: str | None = None,
    *,
    started_at: str | None = None,
    ttl_estimate: int | None = None,
) -> dict[str, Any]:
    """Return the `ai_playbook.degradation.*` set.

    Keys per `specs/degradation-modes.md` §5. ``state`` must be one of
    ``HEALTHY``, ``DEGRADED_CAPACITY``, ``DEGRADED_QUALITY``,
    ``DEGRADED_CONTEXT``, ``OFFLINE`` — but consumers tolerate unknown values
    by treating them as ``DEGRADED_CAPACITY`` (see spec §1).
    """
    out: dict[str, Any] = {"ai_playbook.degradation.state": state}
    if reason:
        out["ai_playbook.degradation.reason"] = reason
    if started_at:
        out["ai_playbook.degradation.started_at"] = started_at
    if ttl_estimate is not None:
        out["ai_playbook.degradation.ttl_estimate"] = int(ttl_estimate)
    return out


def override_attrs(
    gate: str,
    reason: str,
    actor: str | None = None,
    *,
    script: str | None = None,
) -> dict[str, Any]:
    """Return the `ai_playbook.override.*` set.

    Keys per `specs/break-glass.md` — these flow through whenever a caller
    invokes ``--force-with-reason``.
    """
    out: dict[str, Any] = {
        "ai_playbook.override": True,
        "ai_playbook.override_gate": gate,
        "ai_playbook.override_reason": reason,
    }
    if actor:
        out["ai_playbook.override_actor"] = actor
    if script:
        out["ai_playbook.override_script"] = script
    return out


class _NoOpSpan:
    """Minimal stand-in used when ``opentelemetry`` is absent."""

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def get_span_context(self) -> Any:
        return None

    def end(self) -> None:
        return None


__all__ = [
    "span",
    "current_trace_id",
    "add_event",
    "gen_ai_attrs",
    "routing_attrs",
    "degradation_attrs",
    "override_attrs",
]
