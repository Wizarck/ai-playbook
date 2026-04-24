# model-routing.md

> **Status**: v1.0.0.

The routing matrix below is the canonical taxonomy every playbook consumer uses to pick a model for a given task class. It is **LLM-agnostic at the spec layer**: the primary and fallback columns name specific model IDs as of 2026-04, but the task classes and the fallback semantics are intended to outlive any specific generation of models. When a new family ships, bump IDs in the table; do not reshape the taxonomy lightly.

Providers addressed here:

- **Anthropic** — `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`.
- **Google** — `gemini-2.5-pro`, `gemini-2.5-pro-thinking`, `gemini-2.5-flash`.
- **OpenRouter** — `openrouter/llama-4-70b` (open-weights fallback).
- **Ollama (local)** — `gpt-oss-20b` (currently ELIGIA low-criticality tier, per `eligia-core` commit `a85830f`).
- **LiteLLM** — sits on ELIGIA port `4000`; it is the routing point for embeddings, rerank, and any OpenAI-compatible fan-out. The router itself does not need to know which embedding model is in use.

## 1. Task classes (canonical taxonomy)

Cost tiers (**L** low, **M** medium, **H** high) are **qualitative and relative within this matrix**, not absolute USD. They reflect input+output token price at typical volume for the task; see `degradation-modes.md` for the composition rule when the primary is unavailable.

Latency tiers refer to **time-to-first-token for interactive tasks**, or **total wall time** for batch tasks where that distinction matters.

| Task class | Primary | Fallback chain | Rationale | Cost tier | Latency tier |
|---|---|---|---|---|---|
| Classification / triage (<500 tok) | `claude-haiku-4-5` | `gemini-2.5-flash` → `openrouter/llama-4-70b` → `ollama/gpt-oss-20b` | Fast, cheap, consistent. Triage is high-volume and low-stakes per call; the local fallback ensures we never block on a network hiccup. | L | L |
| Code review — Blind Hunter layer | `claude-sonnet-4-6` | `gemini-2.5-pro` → `claude-haiku-4-5` (with a quality-degraded tag) | Parallel review layer 1: reads diff cold, no context about intent. Sonnet-tier reasoning is the floor for useful signal. | M | M |
| Code review — Edge Case Hunter layer | `claude-sonnet-4-6` | `gemini-2.5-pro-thinking` → `claude-sonnet-4-6` retry | Parallel layer 2: walks boundary conditions. Benefits from thinking-mode on the Gemini fallback when available. | M | M |
| Code review — Acceptance Auditor layer | `claude-sonnet-4-6` | `gemini-2.5-pro` → `claude-opus-4-7` (upgrade if budget allows) | Parallel layer 3: reconciles diff against acceptance criteria. If fallback is Opus, log it and flag the cost anomaly in the retrospective. | M | M |
| Daily dev / story implementation | `claude-sonnet-4-6` | `gemini-2.5-pro` → `claude-haiku-4-5` (with a quality-degraded tag) | Workhorse tier. Most IDE-assisted work lands here; downgrading to Haiku is a visible event — users must see `DEGRADED_QUALITY` state. | M | M |
| Architecture proposal / ADR drafting | `claude-opus-4-7` | `gemini-2.5-pro-thinking` → `claude-sonnet-4-6` | Reasoning-heavy, low-volume. Sonnet is the last acceptable floor — below that, the task should block, not silently degrade (see §3). | H | H |
| Retrospective / reflection / wide synthesis | `claude-opus-4-7` | `gemini-2.5-pro-thinking` → block | Needs wide context and synthesis across many trace spans. A Sonnet-tier output here is not worth producing; better to queue the retro. | H | H |
| Doc writing (playbook specs, runbooks) | `claude-opus-4-7` for initial drafts, `claude-sonnet-4-6` for edits | `gemini-2.5-pro` → `claude-sonnet-4-6` | Dispatch-file architecture demands dense, cross-referenced prose. Opus for the first pass amortizes better than multiple Sonnet revisions. | H (draft) / M (edit) | M |
| Embeddings / rerank | LiteLLM-routed (see `eligia-core` LiteLLM config) | Provider-internal; LiteLLM handles its own fallback set | The router emits `gen_ai.request.model="litellm"` and the concrete embedding model as a span attribute. Consumers should not hard-code an embedding model in their code paths. | L | L |
| LLM-as-judge (prompt injection filter, PII screen, etc.) | `claude-haiku-4-5` | `gemini-2.5-flash` → `openrouter/llama-4-70b` | Judges should be small, fast, and boring. Avoid Opus-tier judges — they invent nuance where none exists, hurt latency, and balloon cost. | L | L |

### Cost/latency tier rationale (one sentence each)

- **L cost**: small-model pricing, short outputs; acceptable to run on every interaction.
- **M cost**: workhorse-tier pricing; budget-visible but not alarming at daily volume.
- **H cost**: reasoning-tier pricing; budget-visible; only justified for reasoning/synthesis work.
- **L latency**: sub-second to ~2s typical; fits inside an IDE completion loop.
- **M latency**: 2-10s typical; fine for a review pass or a story-implementation turn.
- **H latency**: 10s+; acceptable for batch-style work (doc drafts, retros, proposals).

## 2. Fallback chain semantics

1. **Try primary.** On hard failure (5xx, timeout past per-call budget, rate-limit error) or soft failure (quality-degraded signal from a health probe), move to the next element in the chain.
2. **One step is silent, further steps are not.** A single-step fallback (primary → first element) is emitted as a span attribute but does not break the caller's flow. Falling back **two or more steps** MUST produce a user-visible notification per `notification-policy.md` and tag the session as `DEGRADED_QUALITY` per `degradation-modes.md`.
3. **No cross-task-class promotion without a reason.** If a triage task falls all the way through and the router is tempted to ask Opus, it must refuse: downgrading is fine; upgrading a class silently is not. The caller can explicitly opt in with break-glass (`break-glass.md`).
4. **Depth is tracked.** The router emits `ai_playbook.routing.fallback_depth` (int, 0 = primary). Alerts fire at depth ≥ 2 sustained for >5 minutes in a session.
5. **Chain is evaluated per call, not per session.** A transient rate-limit on turn 3 does not pin subsequent turns to the fallback; it should probe the primary again on turn 4 (see circuit-breaker rules in `degradation-modes.md`).

Degradation state (triggered by the router and observed by the rest of the stack) lives in [degradation-modes.md](degradation-modes.md).

## 3. Provider-specific quirks

### Anthropic

- Context window: 200k baseline, 1M on specific IDs (`claude-opus-4-7[1m]`, etc.). Do not assume 1M is available on every ID.
- Rate limits: tier-based, measured in tokens/min and requests/min. Exhaust is a `429` — retry with exponential backoff, then fall back.
- Strength: strongest at multi-step reasoning and code review. Best cache ergonomics thanks to explicit `cache_control`.
- Weakness: rate-limit ceilings are the operational bottleneck in this codebase; also the most expensive per output token.
- Watch: advisor-tool beta is in use in `eligia-core/lib/advisor.py`; header is `anthropic-beta: advisor-tool-2026-03-01`. When the beta GA-ships, the header moves.

### Google Gemini

- Context window: up to ~2M on `gemini-2.5-pro`; very large windows change cache economics significantly.
- Rate limits: project-level quota; thinking mode counts against a separate budget on some plans.
- Strength: long-context retrieval and cross-document synthesis; thinking mode meaningfully helps on edge-case hunting.
- Weakness: tool-use reliability still lags Anthropic; be prepared to re-prompt if a tool call returns malformed args.
- Watch: Context Caching API has a 32k-token minimum — see `prompt-caching.md`.

### OpenRouter (Llama 4 70B)

- Context window: model-dependent (~128k on `llama-4-70b`); reported by OpenRouter metadata.
- Rate limits: soft; OpenRouter load-balances across upstream providers. Failure modes are usually an upstream hiccup rather than a hard quota.
- Strength: provider-redundant, single API surface, open-weights reassurance for privacy-sensitive triage.
- Weakness: quality is a meaningful step down from the flagship tier; reserve for fallback-of-fallback on triage and judge tasks, not primary dev.
- Watch: OpenRouter's OpenAI-compatible surface means implicit prefix caching behavior depends on the upstream — treat it as best-effort.

### Ollama (local)

- Context window: model-dependent; `gpt-oss-20b` is typically 128k on this rig but assume less if the host is memory-constrained.
- Rate limits: none, other than local hardware.
- Strength: offline fallback for `OFFLINE` state; zero marginal cost; keeps low-criticality tasks moving when WAN is flaky.
- Weakness: quality is noticeably below flagship tier; no KV cache reuse across processes; latency is machine-dependent.
- Watch: ELIGIA reserves `gpt-oss-20b` for low-criticality tasks (per `eligia-core` commit `a85830f`). Do not promote it above its tier without the retro explicitly approving.

## 4. OpenTelemetry attributes emitted by the router

Every LLM call wrapped by the router emits a span with at minimum:

| Attribute | Type | Semantics |
|---|---|---|
| `gen_ai.request.model` | string | The model ID the router **asked for** (primary at call time). |
| `gen_ai.response.model` | string | The model ID that actually responded (differs from request on fallback). |
| `gen_ai.usage.input_tokens` | int | Prompt tokens billed. |
| `gen_ai.usage.output_tokens` | int | Completion tokens billed. |
| `gen_ai.usage.cache_read_input_tokens` | int | Cached-prefix tokens read (0 if provider did not report). |
| `ai_playbook.task_class` | string | Canonical class from §1 (e.g., `daily-dev`, `code-review-blind-hunter`, `llm-as-judge`). |
| `ai_playbook.routing.fallback_depth` | int | 0 on primary, 1 on first fallback, etc. |
| `ai_playbook.routing.reason` | string | Present when `fallback_depth > 0`; enum-ish: `rate_limit`, `timeout`, `error`, `health_probe`. |

These attribute names align with the OpenTelemetry Semantic Conventions for Generative AI (the `gen_ai.*` family) and with the existing Langfuse wrappers in `eligia-core/lib/telemetry/{anthropic,gemini,ollama}_tracer.py`. Keep the attribute surface additive — `additionalProperties: true` applies.

## 5. Hooks and existing code

- **`scripts/doctor.py`** — primary-provider health check at session start: ping each primary referenced by `AIPLAYBOOK_DEFAULT_TASK_CLASSES` (or the full set), record RTT, and warn on any class whose primary is unreachable.
- **`scripts/log_event.py`** — emits the OTel span attributes listed in §4. The router calls it; callers don't emit these directly.
- **`eligia-core/lib/advisor.py`** — existing advisor-pattern implementation. **This spec informs `advisor.py`; `advisor.py` is not modified by this spec.** The mapping is: `AdvisorSession.executor_*` corresponds to the "Daily dev / story implementation" task class, and `AdvisorSession.advisor_*` corresponds to the "Architecture proposal / ADR drafting" class. When the advisor is cross-provider (the `_run_manual_2call` path), both calls are independently subject to this matrix's fallback semantics.
- **`eligia-core/lib/telemetry/*.py`** — existing Langfuse wrappers. Consumers in ELIGIA trace through these; the playbook router emits the same `gen_ai.*` attributes so the two telemetry paths line up.

## 6. Break-glass

A user can pin a specific model against the matrix using the break-glass flag:

```
--force-model=<id> --force-with-reason="<≥10 chars>"
```

The override produces the audit trail defined in `break-glass.md` and surfaces in the retrospective. Forcing a model does **not** bypass degradation: if the forced model is itself degraded, the call still fails fast and the override reason is logged alongside the failure.

## See also

- [degradation-modes.md](degradation-modes.md) — state machine the router feeds into.
- [prompt-caching.md](prompt-caching.md) — cache ordering that applies regardless of provider.
- [parallel-review.md](parallel-review.md) — consumer of the three "Code review" task classes.
- [break-glass.md](break-glass.md) — `--force-with-reason` semantics referenced in §6.
- [notification-policy.md](notification-policy.md) — when and how user-visible fallback notifications are delivered.
