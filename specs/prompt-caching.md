# prompt-caching.md

> **Status**: stub, v0.1.0. Populated in **T04b**.

## Core rule

Order content **stable → volatile** in every prompt so the cache prefix stays hot across turns:

1. System prompt / persona (stable).
2. Inherited specs from the playbook (stable).
3. Project `AGENTS.md` (stable per session).
4. MCP capability lists (stable).
5. Long-lived context: active OpenSpec change, architecture docs (stable per task).
6. Tool descriptions (stable unless tool set changes).
7. Memory recall results (semi-stable).
8. Most recent user turn (volatile).
9. Tool outputs (volatile).

## Provider notes (v0)

- Anthropic: explicit `cache_control` on the prefix boundary. 5-min TTL (see `/compact` preventivo rule in universal principles).
- Gemini: explicit cache via Context Caching API for tokens ≥32k.
- OpenAI compat layer: prefix caching is implicit; order-sensitivity still holds.

## Populated in T04b

Worked examples, `ANTHROPIC_CACHE_TOKENS_MIN` knob, and cache-hit telemetry via OTel `gen_ai.usage.cache_read_input_tokens`.
