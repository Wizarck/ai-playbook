"""Unit tests for scripts/tracing/otel_setup.py + scripts/tracing/trace_emit.py.

These tests are designed to pass WITHOUT `opentelemetry` or `langfuse`
installed. Tests that require the real SDK use `pytest.importorskip`.
"""
from __future__ import annotations

import builtins
import importlib

import pytest

from scripts.tracing import otel_setup, trace_emit

# ---------------------------------------------------------------------------
# init_tracing() behaviour
# ---------------------------------------------------------------------------


def test_init_tracing_disabled_env_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPLAYBOOK_TRACING_DISABLED", "1")
    tracer = otel_setup.init_tracing("test-service")
    # No-op tracer exposes start_as_current_span returning something with context-manager shape.
    span = tracer.start_as_current_span("x")
    with span as s:
        assert s is not None
        s.set_attribute("k", "v")  # must not raise


def test_init_tracing_without_otel_installed_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate `opentelemetry` being absent. init_tracing() must degrade."""
    monkeypatch.delenv("AIPLAYBOOK_TRACING_DISABLED", raising=False)
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated absent module: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tracer = otel_setup.init_tracing("test-service")
    # Should be the no-op stand-in — duck-typed check.
    span_cm = tracer.start_as_current_span("x")
    with span_cm as s:
        s.set_attribute("k", "v")
        s.add_event("evt", {"a": 1})


def test_init_tracing_without_langfuse_keys_skips_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIPLAYBOOK_TRACING_DISABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    # Without OTel installed locally in the CI env, we still expect a usable tracer.
    tracer = otel_setup.init_tracing("test-service", enable_langfuse=True, enable_otlp=True)
    span_cm = tracer.start_as_current_span("x")
    with span_cm as s:
        s.set_attribute("probe", True)


def test_read_playbook_version_returns_string() -> None:
    v = otel_setup._read_playbook_version()
    assert isinstance(v, str)
    assert v  # not empty


def test_noop_tracer_start_span_also_works() -> None:
    t = otel_setup._NoOpTracer()
    span_cm = t.start_as_current_span("foo", attributes={"a": 1})
    with span_cm as s:
        s.set_attributes({"b": 2})
        s.add_event("e", {"x": 1})
        s.record_exception(RuntimeError("nope"))
        assert s.get_span_context() is None
        s.end()


# ---------------------------------------------------------------------------
# trace_emit.span() context manager
# ---------------------------------------------------------------------------


def test_span_context_manager_without_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force trace module import to fail, confirm span() still yields a no-op."""
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with trace_emit.span("qa.verdict", {"severity": "S1"}) as s:
        # no-op span is fine
        s.set_attribute("extra", "v")
        s.add_event("checkpoint", {"at": "start"})


def test_current_trace_id_without_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert trace_emit.current_trace_id() is None


def test_add_event_is_noop_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Must not raise.
    trace_emit.add_event("some.event", {"k": "v"})
    trace_emit.add_event("some.event")


# ---------------------------------------------------------------------------
# Semantic-convention helpers — returned dict shape is the contract
# ---------------------------------------------------------------------------


def test_gen_ai_attrs_has_all_canonical_keys() -> None:
    d = trace_emit.gen_ai_attrs(
        model="claude-sonnet-4-6",
        provider="anthropic",
        tokens_in=1234,
        tokens_out=56,
        cache_read=800,
    )
    assert d["gen_ai.system"] == "anthropic"
    assert d["gen_ai.request.model"] == "claude-sonnet-4-6"
    assert d["gen_ai.response.model"] == "claude-sonnet-4-6"
    assert d["gen_ai.usage.input_tokens"] == 1234
    assert d["gen_ai.usage.output_tokens"] == 56
    assert d["gen_ai.usage.cache_read_input_tokens"] == 800


def test_gen_ai_attrs_response_model_override() -> None:
    d = trace_emit.gen_ai_attrs(
        model="claude-opus-4-7",
        provider="anthropic",
        tokens_in=10,
        tokens_out=20,
        response_model="claude-sonnet-4-6",
    )
    assert d["gen_ai.request.model"] == "claude-opus-4-7"
    assert d["gen_ai.response.model"] == "claude-sonnet-4-6"


def test_routing_attrs_depth_and_reason() -> None:
    d = trace_emit.routing_attrs("daily-dev", fallback_depth=2, reason="rate_limit")
    assert d["ai_playbook.task_class"] == "daily-dev"
    assert d["ai_playbook.routing.fallback_depth"] == 2
    assert d["ai_playbook.routing.reason"] == "rate_limit"


def test_routing_attrs_no_reason_when_primary() -> None:
    d = trace_emit.routing_attrs("triage", fallback_depth=0)
    assert "ai_playbook.routing.reason" not in d
    assert d["ai_playbook.routing.fallback_depth"] == 0


def test_degradation_attrs_full_set() -> None:
    d = trace_emit.degradation_attrs(
        state="DEGRADED_QUALITY",
        reason="fallback_depth",
        started_at="2026-04-22T10:00:00+00:00",
        ttl_estimate=120,
    )
    assert d["ai_playbook.degradation.state"] == "DEGRADED_QUALITY"
    assert d["ai_playbook.degradation.reason"] == "fallback_depth"
    assert d["ai_playbook.degradation.started_at"] == "2026-04-22T10:00:00+00:00"
    assert d["ai_playbook.degradation.ttl_estimate"] == 120


def test_degradation_attrs_healthy_minimal() -> None:
    d = trace_emit.degradation_attrs("HEALTHY")
    assert d == {"ai_playbook.degradation.state": "HEALTHY"}


def test_override_attrs_shape() -> None:
    d = trace_emit.override_attrs(
        gate="schema_validate",
        reason="bootstrapping acme-shop, submodule not added yet",
        actor="jane@acme.example",
        script="scripts/schema_validate.py",
    )
    assert d["ai_playbook.override"] is True
    assert d["ai_playbook.override_gate"] == "schema_validate"
    assert d["ai_playbook.override_reason"].startswith("bootstrapping")
    assert d["ai_playbook.override_actor"] == "jane@acme.example"
    assert d["ai_playbook.override_script"] == "scripts/schema_validate.py"


# ---------------------------------------------------------------------------
# Real-SDK smoke (only if OTel is installed in the test env)
# ---------------------------------------------------------------------------


def test_real_sdk_smoke_if_available() -> None:
    pytest.importorskip("opentelemetry")
    # Re-import to pick up a fresh module state in case earlier monkeypatches touched it.
    importlib.reload(otel_setup)
    tracer = otel_setup.init_tracing("ai-playbook-test-smoke")
    with tracer.start_as_current_span("probe") as s:
        s.set_attribute("gen_ai.system", "probe")


# ---------------------------------------------------------------------------
# _setup_langfuse_once — explicit tracer_provider wiring
# ---------------------------------------------------------------------------


def test_setup_langfuse_passes_tracer_provider_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `init_tracing` builds a TracerProvider it threads it through to
    `Langfuse(tracer_provider=...)`. This guards against a regression back to
    the old global-only wiring (which silently breaks if another import
    swaps the process-global TracerProvider afterward)."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    captured: dict[str, object] = {}

    class _FakeLangfuse:
        def __init__(self, **kw: object) -> None:
            captured.update(kw)

    fake_module = type(
        "_FakeLangfuseModule", (), {"Langfuse": _FakeLangfuse}
    )()
    monkeypatch.setitem(__import__("sys").modules, "langfuse", fake_module)

    sentinel_provider = object()
    ok = otel_setup._setup_langfuse_once(provider=sentinel_provider)
    assert ok is True
    assert captured.get("tracer_provider") is sentinel_provider


def test_setup_langfuse_falls_back_when_no_provider_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling `_setup_langfuse_once()` with no provider keeps backwards
    compatibility: Langfuse() is constructed without kwargs and the SDK
    falls back to its global-TracerProvider behaviour."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    captured: dict[str, object] = {}

    class _FakeLangfuse:
        def __init__(self, **kw: object) -> None:
            captured.update(kw)

    fake_module = type(
        "_FakeLangfuseModule", (), {"Langfuse": _FakeLangfuse}
    )()
    monkeypatch.setitem(__import__("sys").modules, "langfuse", fake_module)

    ok = otel_setup._setup_langfuse_once()
    assert ok is True
    assert "tracer_provider" not in captured
