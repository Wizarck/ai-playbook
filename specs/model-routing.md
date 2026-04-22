# model-routing.md

> **Status**: stub, v0.1.0. Populated in **T04a**. v0.1.0 carries a directional matrix; T04 finalizes providers, IDs, and fallback chains with cost/latency numbers.

## Directional matrix (v0)

| Task class | Primary | Fallback chain | Rationale |
|---|---|---|---|
| Classification / triage (<500 tok) | `claude-haiku-4-5` | `gemini-2.5-flash` → `openrouter/llama-4-70b` | Cheap, fast, high-availability. |
| Code review (3 parallel layers) | `claude-sonnet-4-6` ×3 | `gemini-2.5-pro` ×3 → mixed provider | Per-layer reasoning at accessible price. |
| Daily dev / story implementation | `claude-sonnet-4-6` | `gemini-2.5-pro` → degraded to `haiku` | Balance cost and quality. |
| Architecture decisions / proposal | `claude-opus-4-7` | `gemini-2.5-pro-thinking` → `claude-sonnet-4-6` | Reasoning heavy. |
| Retrospective / reflection | `claude-opus-4-7` | `gemini-2.5-pro-thinking` | Wide-context synthesis. |
| Embeddings / rerank | LiteLLM routes internally | N/A | Domain-specific. |

## See also

- [degradation-modes.md](degradation-modes.md) — how we transition when a primary is out.
- [prompt-caching.md](prompt-caching.md) — cache ordering (stable → volatile) applies regardless of provider.

## Populated in T04

Provider-specific rate limits, pricing snapshots, cache-prefix strategy per provider, and the linkage to `lib/advisor.py` (consumer-d) that does multi-provider review.
