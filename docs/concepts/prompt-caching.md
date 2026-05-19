---
schema: concept/v1
slug: prompt-caching
title: Prompt Caching
summary: |
  Prompt caching is the single largest cost and latency lever in this stack. A
  well-ordered prompt on a multi-turn dev session can recover 70%+ of its
  input-token cost from the provider's cache, and knock seconds off
  time-to-first-token. This spec defines the ordering rule,…
last_validated: "2026-05-19"
---

# Prompt Caching

Prompt caching is **the single largest cost and latency lever** in this stack. A well-ordered prompt on a multi-turn dev session can recover 70%+ of its input-token cost from the provider's cache, and knock seconds off time-to-first-token. This spec defines the ordering rule, provider-specific mechanics, anti-patterns, and the telemetry + config knobs that make cache behavior observable.

The ordering rule is provider-agnostic. The mechanics below are provider-specific.

## 1. Core ordering rule: stable → volatile

Every prompt is assembled as a sequence of tiers, strictly **most stable first, most volatile last**. Cache boundaries live between tiers; changing anything in a tier invalidates every byte after it, so tier discipline is not optional.

| Tier | Contents | Why it is at this position |
|---|---|---|
| 1. System prompt / persona | The role and tone of the agent. Changes rarely — a new persona version is a new session. | Stable across every turn of a session, and usually across days. Anchors the cache prefix. |
| 2. Inherited specs from playbook | `ai-playbook/specs/*.md` referenced via dispatcher. | Stable across sessions unless the playbook submodule is bumped. Bumping is a deliberate, visible event. |
| 3. Project `AGENTS.md` | The consuming project's dispatcher. | Stable per session. Edits to this file are rare mid-session; if they happen, the cache prefix invalidates — accept it. |
| 4. MCP capability lists | Enumerated tool/server inventory for the session. | Stable unless a new MCP server is wired up. Treat tool-server churn as a session boundary. |
| 5. Long-lived task context | Active OpenSpec change (`proposal.md`, `specs/*.md`, `design.md`), architecture docs, the PRD being implemented. | Stable per task. Bouncing between tasks is the primary legitimate reason to invalidate beyond this tier. |
| 6. Tool descriptions / schemas | JSON schemas, parameter lists, examples for each available tool. | Stable unless the tool set itself changes mid-session. Keep these in a block that does not include example outputs (those belong below). |
| 7. Memory recall results | Long-term memory snippets retrieved for this turn. | Semi-stable: usually identical turn-to-turn for the same working context, but not guaranteed. Acceptable cache-boundary position when memory is idempotent. |
| 8. Most recent user turn | The actual question or instruction for this turn. | Volatile by definition. |
| 9. Tool outputs from this turn | Results of any tool calls made while handling this turn. | Most volatile. Never cache these; never reorder them into earlier tiers. |

**The cache boundary sits between the stable cluster (tiers 1-6) and the volatile cluster (tiers 7-9).** Tier 7 is the pragmatic boundary for Anthropic's explicit `cache_control` and for Gemini's explicit Context Caching.

## 2. Provider notes

### 2.1 Anthropic (Claude)

- **Explicit cache via `cache_control`.** Mark the last stable block with `"cache_control": {"type": "ephemeral"}`. Everything at or before that marker is eligible for prefix caching; everything after it is not. Exactly one boundary per prompt is typical; up to four are allowed per provider rules, but more boundaries = more invalidation risk.
- **5-minute TTL.** A cached prefix goes stale after five minutes of no use on the same exact prefix. This is the mechanical reason for universal principle #4 (`/compact` preventivo at ~50% context): compaction preserves intent while resetting the volatile tier, keeping the stable prefix unchanged, which keeps the cache warm.
- **Cache-write is a one-time cost, cache-read is a discount.** The first turn that establishes the cache pays a write premium; subsequent turns within the TTL pay a steep discount on those same tokens. In a multi-turn session, a single prefix-building turn amortizes over many read-hit turns.
- **`cache_read_input_tokens` is reported in the usage block.** Log it. A low ratio of `cache_read_input_tokens / input_tokens` on a long session means tier ordering is broken — fix the prompt assembly before anything else.
- **Min tokens matter.** Anthropic requires a minimum prefix size for caching to engage. The playbook exposes `ANTHROPIC_CACHE_TOKENS_MIN` (see §5) to tune this; `scripts/doctor.py` warns if a typical session's tier-1-through-6 block is smaller than the configured floor.

### 2.2 Google Gemini

- **Explicit Context Caching API.** Separate HTTP surface from the generate call — you upload a cache, get back a handle, and pass the handle on subsequent calls. This decouples cache lifetime from the 5-minute-idle model that Anthropic uses.
- **32k-token minimum.** Gemini will not cache anything smaller. Consequence: on small-context tasks (triage, LLM-as-judge), Gemini caching is a non-factor — the ordering discipline still helps implicit prefix reuse on some generations, but the explicit API is not engaged.
- **TTL is configurable.** The cache resource carries an explicit TTL; you can set it much longer than Anthropic's 5 minutes when you know a stable prefix will be reused across an entire day.
- **Cache handle is a resource, not an attribute.** Manage it. Delete stale handles explicitly. The playbook router tracks outstanding cache handles per session and cleans up at session end.

### 2.3 OpenAI-compatible (OpenRouter, LiteLLM)

- **Implicit prefix caching, provider-dependent.** The OpenAI-compatible API surface does not expose a `cache_control` equivalent; caching behavior is up to the upstream. Stability still matters because upstreams that do cache use the prefix bytes as the key.
- **OpenRouter fan-out changes the equation.** A single logical OpenRouter call may route to different upstream providers on different turns, each with its own cache state. Expect lower cache hit rates than with a direct Anthropic or Gemini call.
- **LiteLLM at consumer-d port `4000`** uniformly exposes OpenAI-compatible responses. Cache-hit signals from upstream are passed through when present; absence of the field does not mean absence of caching, just absence of reporting.
- **Do not rely on OpenAI-compatible caching for cost guarantees.** Treat any savings here as bonus; budget as if every token were fresh.

### 2.4 Local (Ollama)

- **No request-level cache.** Ollama runs local inference with no equivalent to provider-side prefix caching.
- **KV cache warmth still matters.** Consistent ordering keeps the model's internal key-value cache warm across requests in the same process, shaving first-token latency meaningfully.
- **Model load is the bigger factor.** Keeping the model resident (long `keep_alive` in the Ollama config) dominates any ordering benefit. Configure `keep_alive` for task classes that use Ollama regularly.
- **Don't port Anthropic-style cache boundary markers to Ollama.** They are ignored, but cluttering the prompt with dead directives is bad hygiene — adapt the assembled prompt to the provider.

## 3. Anti-patterns

Each of these silently destroys cache hit rate. They are listed in rough order of how often they appear in practice:

- **Timestamps or session IDs in tier 1-6.** An ISO timestamp in the system prompt invalidates the cache on every single turn. If you need to inject "current time", do it in tier 8 as part of the user turn, not tier 1.
- **Reordering context on every turn.** Concatenating retrieval results in a different order each turn because "the ranker said so" kills caching. Pin an order (e.g., by document ID) once retrieval is stable enough.
- **Stuffing tool schemas into volatile positions.** Tool schemas belong in tier 6, before memory recall. Moving them to near the user turn "because they're long" is a false optimization — it collapses the cached prefix.
- **Editing `AGENTS.md` mid-session.** It happens when someone fixes a typo during an agent run. Accept the invalidation or batch the edit at a session boundary.
- **Mixing a "debug" flag into the system prompt.** Setting `DEBUG=1` into tier 1 for one session and unsetting for the next splits the cache two ways on the same agent. Put debug switches in tier 8 as metadata attached to the turn, or in headers/metadata fields that don't participate in the cache key.
- **Inlining large tool outputs back into context at tier 5.** Tool outputs belong in tier 9, even if they're "relevant forever". Summarize them during `/compact` and reference the summary from a stable tier if you need persistence.

## 4. Worked example: three consecutive spec writes in one session

Session goal: draft three adjacent specs (`model-routing.md`, `degradation-modes.md`, `prompt-caching.md`) in one go.

**Turn 1 — write `model-routing.md`.** Prompt assembly:

```
[tier 1] System: "You are a technical writer expanding stub specs..."
[tier 2] Playbook specs: dispatcher-chain.md, taxonomy.md, verdict-contract.md
[tier 3] Project AGENTS.md (ai-playbook)
[tier 4] MCP list: (none for this repo)
[tier 5] Task context: "Batch 2 Subagent B scope, stub file contents"
[tier 6] Tool descriptions: Read, Write, Edit, Grep, Glob
[tier 7] Memory recall: (empty — fresh session)
<<< cache_control boundary here (Anthropic) >>>
[tier 8] User: "expand model-routing.md into v1"
[tier 9] Tool outputs: Read results of the three stub files
```

Cache is written. First-turn cost is the prefix size plus the user turn.

**Turn 2 — write `degradation-modes.md`.** Tiers 1-6 are **byte-identical** to turn 1; tier 7 may still be empty or may now carry a short memory of "the previous spec you wrote". Tier 8 is the new user turn ("now do degradation-modes"). Tier 9 contains the new Read results.

If tiers 1-6 are identical, the Anthropic cache **reads** on turn 2. `cache_read_input_tokens` jumps from 0 on turn 1 to roughly the full tier-1-through-6 size on turn 2. That's the win.

**Turn 3 — write `prompt-caching.md`.** Same story as turn 2. Cache still warm because we haven't exceeded 5 minutes of idle and tiers 1-6 haven't changed.

**When `/compact` kicks in (~50% context reached).** The volatile cluster (tiers 7-9 across all prior turns) is rewritten to a compact summary. Tiers 1-6 are untouched. On the next turn, the cache prefix still matches, so the prefix remains hot. This is the mechanical payoff of universal principle #4.

**Anti-pattern that would break this session.** If on turn 2 the assembly inserted the turn-1 output (the full `model-routing.md` text) into tier 5 "for context", then:

- Tier 5 changes between turn 1 and turn 2.
- Every tier after tier 5 (including the cache boundary) is post-invalidation.
- Anthropic cache must rebuild from the earliest changed byte. `cache_read_input_tokens` collapses back to the stable prefix before tier 5 only.

Fix: leave prior outputs out of tier 5. If the agent genuinely needs them, put them in tier 8 or 9, where invalidation is expected.

## 5. Telemetry and targets

| Attribute | Source | Use |
|---|---|---|
| `gen_ai.usage.cache_read_input_tokens` | Provider response | Primary cache-hit signal. |
| `gen_ai.usage.input_tokens` | Provider response | Denominator for hit rate. |
| `ai_playbook.prompt_cache.hit_ratio` | Derived (`cache_read / input`) | Per-span; aggregate in the dashboard. |
| `ai_playbook.prompt_cache.boundary_tier` | Emitted by the router | Which tier the boundary was placed at for this call. |

**Target**: `cache_read_input_tokens / input_tokens ≥ 0.70` at the **95th percentile of a multi-turn dev session** (≥5 turns). Sessions below that on the P95 are flagged for retrospective review; the usual root cause is one of the anti-patterns in §3.

## 6. Config knob: `ANTHROPIC_CACHE_TOKENS_MIN`

Controls the minimum assembled tier-1-through-6 size below which the router will not emit a `cache_control` marker (pointless — the provider's own minimum would reject it anyway, and an attempted cache write costs the premium with no later read-hit benefit).

- **Namespace**: fits under `AIPLAYBOOK_` per `env-vars.md`; exposed as **`ANTHROPIC_CACHE_TOKENS_MIN`** for alignment with Anthropic terminology. Alias: `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN`.
- **Default**: not legislated here; `scripts/doctor.py` carries a sane default informed by the Anthropic minimum in effect at tooling time.
- **Check**: `scripts/doctor.py` reads the value on startup, measures a synthetic tier-1-through-6 for the current project, and warns if the measured prefix would fall below the configured floor ("your cache will never engage for this project as configured — consider pulling more stable context into the prefix").

## See also

- [model-routing.md](model-routing.md) — cache telemetry rides on the same `gen_ai.*` span attributes the router emits.
- [degradation-modes.md](degradation-modes.md) — a falling-back router changes the response model, which may also change the caching mechanics (Anthropic vs Gemini vs OpenAI-compat).
- [env-vars.md](env-vars.md) — `ANTHROPIC_CACHE_TOKENS_MIN` and the `AIPLAYBOOK_` namespace.
- [retrospective-cadence.md](retrospective-cadence.md) — sessions that miss the 70% P95 target feed the retro.
