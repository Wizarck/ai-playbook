"""ai-playbook canonical LLM gateway helper.

Per OpenSpec change `add-litellm-enforcement` (Phase 5 P5.4): every LLM call in
the codebase MUST go through `_llm.call(task_class, prompt, ...)`. The helper
hits the LiteLLM proxy at ``LITELLM_BASE_URL`` (default ``http://localhost:4000``),
which resolves the model from ``configs/litellm-router.yaml`` based on the
``task_class`` parameter.

Why this layer:

1. **Routing-as-config**: changes to the model matrix are YAML edits, not code
   edits. (D3.2)
2. **Per-consumer virtual key isolation**: LiteLLM enforces per-virtual-key
   budgets so a runaway agent cannot drain budget across consumers. (D3.3)
3. **Cost tracking unification**: every call emits the canonical
   ``gen_ai.usage.*`` attributes from `model-routing.md` §4 — one source of
   truth for `scripts/telemetry/report.py` (absorbed `cost_report.py` in Slice 6).
4. **Drift detection**: callers that bypass the helper are caught by
   `verify_llm_routing.py` (pre-commit hook, warn-only initially). (D3.5)

Public API
==========

    response = call(task_class, prompt, *, system=None, max_tokens=None,
                    consumer=None, **extra)

- ``task_class``: one of the 11 classes in `model-routing.md` §1. Validated
  against the YAML — unknown classes raise ``ValueError`` so typos fail fast.
- ``consumer``: optional override for the virtual-key consumer (``ADVISOR``,
  ``HERMES``, ``JUDGE``, ``WORKFLOWS``, etc). Default resolves from env
  ``AIPLAYBOOK_CONSUMER`` or falls back to the implicit consumer in the
  router config.
- ``extra`` is forwarded to the LiteLLM ``/chat/completions`` endpoint.

Returns ``LLMResponse`` (dataclass) with the text + usage + the actual
model that served the request (after any fallback hops).

Raises
======

- ``ValueError`` for unknown task_class.
- ``LLMRoutingError`` when the proxy is unreachable AND the helper has no
  local fallback. Callers MUST handle this (or let it propagate to a
  retry layer).

LiteLLM proxy
=============

Already running on the VPS via ``/start`` skill (port 4000). Local dev
machines can spin up the proxy via ``docker compose -f deploy/litellm/docker-compose.yml up``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)


# Canonical task classes from `docs/concepts/model-routing.md` v2.0.0 §1.
# Kept in sync via Task 8 of the OpenSpec change. The drift detector
# `verify_llm_routing.py` reads from this list, so don't fork the source of truth.
KNOWN_TASK_CLASSES: frozenset[str] = frozenset({
    # L tier
    "triage",
    "safety_judge",
    "conversational_agent",
    # M tier
    "daily_dev",
    "code_review_blind",
    "code_review_edge",
    "code_review_acceptance",
    "doc_writing_edit",
    # H tier
    "architecture_proposal",
    "retrospective",
    "doc_writing_draft",
    # Provider-internal
    "embeddings_rerank",
})


_DEFAULT_BASE_URL = "http://localhost:4000"
_DEFAULT_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Errors + response shape
# ---------------------------------------------------------------------------


class LLMRoutingError(RuntimeError):
    """Raised when the LiteLLM proxy is unreachable and no local fallback exists.

    The helper does NOT itself fall back to direct provider SDKs — that would
    re-introduce the very fragmentation this layer eliminates. Callers MUST
    handle this exception (typically by retrying with backoff or surfacing a
    user-visible degradation message).
    """


@dataclass
class LLMResponse:
    """Decoded response from the LiteLLM proxy.

    Attributes mirror the OTel attribute names from `model-routing.md` §4 so
    span emission is one-to-one.
    """
    text: str
    task_class: str
    model_actual: str          # gen_ai.response.model — after any fallback hops
    fallback_depth: int        # 0 = primary served; 1+ = hops down the chain
    consumer: str | None       # virtual-key consumer this request was billed to
    application: str | None = None  # functional grouping (per add-litellm-enforcement D3.8)
    usage: dict[str, int] = field(default_factory=dict)  # {"prompt_tokens", "completion_tokens", ...}
    raw: dict[str, Any] = field(default_factory=dict)    # full provider response for debugging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get("LITELLM_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _master_key() -> str | None:
    """LiteLLM master key for proxy auth (NOT the per-consumer virtual keys)."""
    val = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    return val or None


def _resolve_consumer(explicit: str | None) -> str | None:
    if explicit:
        return explicit.upper()
    env = os.environ.get("AIPLAYBOOK_CONSUMER", "").strip()
    return env.upper() if env else None


def _resolve_application(explicit: str | None) -> str | None:
    """Resolve the `application` tag for OTel attribution.

    Per add-litellm-enforcement D3.8: this is a SEPARATE dimension from
    `consumer`. `consumer` groups by budget bucket; `application` groups
    by functional subsystem. M:M cardinality (one consumer fans out to
    many applications, one application can hit many consumers via
    different task classes).

    Canonical roster lives in `model-routing.md` §5. Validation against
    that roster is warn-only in v1, strict in v2 (post-migration).
    """
    if explicit:
        # Lowercased + kebab — `hermes-bot`, `aiops-workflow-vps-maintainer`.
        return explicit.strip().lower()
    env = os.environ.get("AIPLAYBOOK_APPLICATION", "").strip()
    return env.lower() if env else None


def _events_path() -> Path:
    """Same convention as scripts/notify.py — single audit log per repo."""
    override = os.environ.get("AIPLAYBOOK_EVENTS_FILE", "").strip()
    if override:
        return Path(override)
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate / ".ai-playbook" / "events.jsonl"
    return here / ".ai-playbook" / "events.jsonl"


def _emit_event(name: str, attrs: dict[str, Any]) -> None:
    """Append a `gen_ai.*` event to events.jsonl. Best-effort, never raises."""
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "event": name,
        **attrs,
    }
    try:
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call(
    task_class: str,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    consumer: str | None = None,
    application: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    **extra: Any,
) -> LLMResponse:
    """Call an LLM via the LiteLLM proxy, model resolved from `task_class`.

    Args:
        task_class: one of `KNOWN_TASK_CLASSES`. Routed via `litellm-router.yaml`.
        prompt: user message.
        system: optional system prompt.
        max_tokens: cap on output tokens.
        consumer: per-consumer virtual key (``ADVISOR``/``HERMES``/``JUDGE``/...).
            When set, LiteLLM applies that key's budget. Default reads
            ``AIPLAYBOOK_CONSUMER`` env or falls back to the YAML default.
        application: functional subsystem tag for cost attribution
            (``hermes-bot``/``dashboard-backend``/``aiops-workflow-<name>``).
            Per add-litellm-enforcement D3.8: SEPARATE dimension from
            ``consumer``; M:M cardinality. Default reads
            ``AIPLAYBOOK_APPLICATION`` env. Canonical roster in
            ``model-routing.md`` §5.

            Example::

                call("triage", "ping",
                     consumer="ADVISOR",            # budget bucket
                     application="dashboard-backend")  # functional bucket
        timeout_seconds: per-call wall-time cap.
        **extra: forwarded to the LiteLLM `/chat/completions` request body
            (e.g. `temperature`, `top_p`, `response_format`).

    Returns:
        :class:`LLMResponse` with the text, the actual model that served the
        request, and usage stats.

    Raises:
        ValueError: unknown ``task_class``.
        LLMRoutingError: proxy unreachable.
    """
    if task_class not in KNOWN_TASK_CLASSES:
        raise ValueError(
            f"unknown task_class={task_class!r}; must be one of {sorted(KNOWN_TASK_CLASSES)}. "
            "If this is a new class, add it to docs/concepts/model-routing.md AND configs/litellm-router.yaml first."
        )

    consumer_resolved = _resolve_consumer(consumer)
    application_resolved = _resolve_application(application)

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": task_class,   # router resolves this to a concrete provider/model
        "messages": messages,
        # LiteLLM-specific metadata header round-trip — emitted as OTel attrs.
        "metadata": {
            "task_class": task_class,
            "consumer": consumer_resolved,
            "application": application_resolved,
        },
        **extra,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    mk = _master_key()
    if mk:
        headers["Authorization"] = f"Bearer {mk}"

    url = f"{_base_url()}/chat/completions"

    started = time.time()
    _emit_event("gen_ai.request.started", {
        "ai_playbook.task_class": task_class,
        "ai_playbook.consumer": consumer_resolved,
        "ai_playbook.application": application_resolved,
        "gen_ai.request.model": task_class,  # resolved by proxy
    })

    # OTel span — wraps the HTTP call so its duration is the span duration and
    # post-hoc set the canonical gen_ai.* attrs once we know the resolved model
    # + token usage. `trace_emit.span` yields a no-op span when OTel is not
    # installed/initialised; failures here never alter the LLM call's outcome.
    span_cm: Any
    try:
        from scripts.tracing import trace_emit
        span_cm = trace_emit.span(
            "llm.call",
            {
                "ai_playbook.task_class": task_class,
                "ai_playbook.consumer": consumer_resolved or "",
                "ai_playbook.application": application_resolved or "",
                "gen_ai.request.model": task_class,
            },
        )
    except Exception:  # noqa: BLE001
        from contextlib import nullcontext
        span_cm = nullcontext(None)

    with span_cm as otel_span:
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                r = client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                body = r.json()
        except httpx.HTTPError as e:
            _emit_event("gen_ai.request.failed", {
                "ai_playbook.task_class": task_class,
                "ai_playbook.consumer": consumer_resolved,
                "ai_playbook.application": application_resolved,
                "error": f"{type(e).__name__}: {e}",
                "elapsed_seconds": round(time.time() - started, 3),
                "severity": "error",
            })
            if otel_span is not None:
                try:
                    otel_span.set_attribute("error.type", type(e).__name__)
                    otel_span.record_exception(e)
                except Exception:  # noqa: BLE001
                    pass
            raise LLMRoutingError(
                f"LiteLLM proxy unreachable at {url}: {type(e).__name__}: {e}. "
                "Verify the proxy is running (/start) and LITELLM_BASE_URL is correct."
            ) from e

        # Parse the response. LiteLLM follows the OpenAI shape; the actual provider
        # model lands in `body["model"]` (not necessarily what we asked for — could
        # be a fallback hop).
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            _emit_event("gen_ai.request.malformed", {
                "ai_playbook.task_class": task_class,
                "ai_playbook.consumer": consumer_resolved,
                "ai_playbook.application": application_resolved,
                "error": f"{type(e).__name__}: {e}",
                "raw_keys": list(body.keys()) if isinstance(body, dict) else "non-dict",
                "severity": "error",
            })
            if otel_span is not None:
                try:
                    otel_span.set_attribute("error.type", type(e).__name__)
                    otel_span.record_exception(e)
                except Exception:  # noqa: BLE001
                    pass
            raise LLMRoutingError(
                "LiteLLM returned a malformed response: missing choices[0].message.content"
            ) from e

        model_actual = body.get("model", "unknown")
        meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        fallback_depth = meta.get("fallback_depth", 0) if meta else 0
        usage = body.get("usage", {}) or {}

        _emit_event("gen_ai.usage", {
            "ai_playbook.task_class": task_class,
            "ai_playbook.consumer": consumer_resolved,
            "ai_playbook.application": application_resolved,
            "gen_ai.request.model": task_class,
            "gen_ai.response.model": model_actual,
            "ai_playbook.routing.fallback_depth": fallback_depth,
            "gen_ai.usage.prompt_tokens": usage.get("prompt_tokens", 0),
            "gen_ai.usage.completion_tokens": usage.get("completion_tokens", 0),
            "elapsed_seconds": round(time.time() - started, 3),
        })

        # Post-annotate the span with the resolved model, fallback hops, and
        # token usage so downstream Langfuse/Tempo dashboards see the same shape
        # the JSONL events carry. Provider is best-effort — LiteLLM doesn't
        # always echo it back in the response body.
        if otel_span is not None:
            try:
                provider_guess = body.get("provider")
                if not provider_guess and "/" in str(model_actual):
                    provider_guess = str(model_actual).split("/", 1)[0]
                otel_span.set_attribute("gen_ai.system", str(provider_guess or "unknown"))
                otel_span.set_attribute("gen_ai.response.model", str(model_actual))
                otel_span.set_attribute("ai_playbook.routing.fallback_depth", int(fallback_depth))
                otel_span.set_attribute("gen_ai.usage.input_tokens", int(usage.get("prompt_tokens", 0) or 0))
                otel_span.set_attribute("gen_ai.usage.output_tokens", int(usage.get("completion_tokens", 0) or 0))
                # Cache hits land either directly under `cache_read_input_tokens`
                # or nested under OpenAI-style `prompt_tokens_details.cached_tokens`.
                cache_read = usage.get("cache_read_input_tokens")
                if cache_read is None:
                    details = usage.get("prompt_tokens_details")
                    if isinstance(details, dict):
                        cache_read = details.get("cached_tokens")
                if cache_read is not None:
                    otel_span.set_attribute("gen_ai.usage.cache_read_input_tokens", int(cache_read))
            except Exception:  # noqa: BLE001 — span annotation must never break the call
                pass

    return LLMResponse(
        text=text,
        task_class=task_class,
        model_actual=model_actual,
        fallback_depth=fallback_depth,
        consumer=consumer_resolved,
        application=application_resolved,
        usage=usage,
        raw=body,
    )


# ---------------------------------------------------------------------------
# CLI helper for debugging
# ---------------------------------------------------------------------------


def _main() -> None:
    """Quick smoke test:  python -m scripts._llm triage 'ping'."""
    import argparse
    parser = argparse.ArgumentParser(description="canonical LLM call helper (LiteLLM-routed)")
    parser.add_argument("task_class", choices=sorted(KNOWN_TASK_CLASSES))
    parser.add_argument("prompt")
    parser.add_argument("--system", default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--consumer", default=None)
    parser.add_argument("--application", default=None,
                        help="Functional tag (e.g. dashboard-backend); see model-routing.md §5")
    args = parser.parse_args()

    try:
        resp = call(
            args.task_class, args.prompt,
            system=args.system, max_tokens=args.max_tokens,
            consumer=args.consumer,
            application=args.application,
        )
    except LLMRoutingError as e:
        print(f"ERROR: {e}", flush=True)
        raise SystemExit(2) from e

    print(f"--- model_actual: {resp.model_actual} (fallback_depth={resp.fallback_depth}) ---")
    print(f"--- usage: {resp.usage} ---")
    print(resp.text)


if __name__ == "__main__":
    _main()
