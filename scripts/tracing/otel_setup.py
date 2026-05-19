"""Bootstrap OTel SDK with dual exporters (OTLP Collector + Langfuse).

Design (per playbook planning): Langfuse gets prompts/outputs/cost (LLM-native
view); OTel Collector + Tempo gets infra correlation (logs/metrics/traces join).
This module wires both from a single `init_tracing()` call so consumers don't
have to know about the exporter plumbing.

Environment variables
---------------------
- ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, ``LANGFUSE_HOST`` — Langfuse
  SDK credentials. If either key is missing, the Langfuse exporter is skipped
  silently.
- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP Collector endpoint (e.g. the acme-corp
  Collector sidecar). If unset, the OTLP exporter is skipped.
- ``OTEL_EXPORTER_OTLP_HEADERS`` — optional OTLP headers, ``k1=v1,k2=v2`` form.
- ``AIPLAYBOOK_TRACING_DISABLED=1`` — hard short-circuit; ``init_tracing()``
  returns the no-op tracer regardless of other config. Useful in tests and in
  ``OFFLINE`` / ``DEGRADED_CONTEXT`` paths.

Graceful degradation
--------------------
Everything import-heavy (``opentelemetry.*``, ``langfuse``) is imported **inside**
``init_tracing()``. If any import fails, this module emits a one-line warning
to stderr and returns a no-op tracer. The caller can always trust the returned
object to honour the ``trace.Tracer`` contract.

Optional deps (declared in ``pyproject.toml`` ``[project.optional-dependencies].tracing``):
``opentelemetry-api``, ``opentelemetry-sdk``, ``opentelemetry-exporter-otlp``,
``langfuse``.

Return shape
------------
``init_tracing()`` returns an ``opentelemetry.trace.Tracer`` (or a no-op stand-in
object exposing ``start_as_current_span``) — the caller uses it identically in
both branches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 stdio — Windows default cp1252 cannot encode the ✅/⚠️/❌ sigils
# we emit on degradation warnings.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_VERSION_FILE = _REPO_ROOT / "VERSION"


def _read_playbook_version() -> str:
    """Read the playbook version from <repo>/VERSION; fall back to 'unknown'."""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


class _NoOpSpan:
    """Minimal span stand-in honouring the subset of the OTel API we touch."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
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

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None


class _NoOpTracer:
    """Tracer stand-in returned when OTel is unavailable or disabled."""

    def start_as_current_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        **_: Any,
    ) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        **_: Any,
    ) -> _NoOpSpan:
        return _NoOpSpan()


def _tracing_disabled() -> bool:
    return os.environ.get("AIPLAYBOOK_TRACING_DISABLED", "").strip() in {"1", "true", "TRUE", "yes"}


def _warn(msg: str) -> None:
    """Single-line stderr warning, prefixed so operators can grep it."""
    try:
        print(f"[ai-playbook.tracing] {msg}", file=sys.stderr)
    except OSError:
        pass


def _setup_langfuse_once() -> bool:
    """Best-effort construct the Langfuse client singleton.

    Returns True if configured, False otherwise. The Langfuse Python SDK reads
    its own env vars, so we only have to decide whether to call the constructor.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        return False
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except ImportError:
        _warn("langfuse not installed; skipping Langfuse exporter. `pip install langfuse`.")
        return False
    try:
        Langfuse()  # v4+ reads env vars automatically
    except Exception as exc:  # noqa: BLE001 — defensive; never crash the caller
        _warn(f"Langfuse init failed: {exc!r}; continuing without it.")
        return False
    return True


def init_tracing(
    service_name: str,
    *,
    enable_langfuse: bool = True,
    enable_otlp: bool = True,
) -> Any:
    """Initialise OTel SDK + optional Langfuse. Return a Tracer (or no-op).

    Safe to call multiple times; OTel's ``TracerProvider`` is process-global
    and subsequent calls rebind ``service.name`` attributes on a fresh provider
    only when none has been installed yet. If one is already installed we reuse
    it — this matches the common pattern in the acme-corp telemetry wrappers.
    """
    if _tracing_disabled():
        return _NoOpTracer()

    # Import OTel inside the function so the module remains importable on
    # systems that only need `log_event`'s JSONL writer.
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
        )
    except ImportError:
        _warn(
            "opentelemetry SDK not installed; returning no-op tracer. "
            "`pip install ai-playbook[tracing]` for full telemetry."
        )
        return _NoOpTracer()

    playbook_version = _read_playbook_version()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": playbook_version,
            "ai_playbook.playbook_version": playbook_version,
        }
    )

    current_provider = trace.get_tracer_provider()
    provider_is_default = not isinstance(current_provider, TracerProvider)

    if provider_is_default:
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
    else:
        provider = current_provider  # type: ignore[assignment]

    # OTLP exporter — infra correlation.
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if enable_otlp and otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter()  # reads endpoint + headers from env
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            _warn("OTLP HTTP exporter not installed; skipping OTLP export.")
        except Exception as exc:  # noqa: BLE001
            _warn(f"OTLP exporter init failed: {exc!r}; continuing without OTLP.")
    elif enable_otlp and not otlp_endpoint:
        # Silent by design — "no endpoint configured" is a valid state, not an error.
        pass

    # Langfuse — LLM-native view (prompts, outputs, cost). Lives alongside OTel
    # but uses its own SDK; we just flip the client on.
    match (enable_langfuse, _tracing_disabled()):
        case (True, False):
            _setup_langfuse_once()
        case _:
            pass

    return provider.get_tracer("ai-playbook", playbook_version)


__all__ = ["init_tracing"]
