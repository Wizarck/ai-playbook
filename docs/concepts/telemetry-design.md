---
schema: concept/v1
slug: telemetry-design
title: Telemetry pipeline design
summary: |
  Rule-event telemetry pipeline shipped in Slice 6 (v0.18.2): every L1
  hook fire writes a JSONL row, the report CLI aggregates them into
  obey-rate / cost / lifecycle metrics. Covers event schema, privacy
  guarantees, and the academic references that motivated the design.
last_validated: "2026-05-19"
---

# Telemetry pipeline design

## Why

The v0.20.0 "world reference" milestone needs evidence, not assertion. Three forces drove the Slice 6 design:

1. **Compliance is not measurable without telemetry.** arXiv 2310.13361 (Wei et al., 2023) and IFEval (Zhou et al., 2023) establish that LLMs drift on long instructions; the rate of drift is the metric a "world reference" needs to publish. Per-rule-fire event emission turns the L1 hook fleet into a measurement instrument.
2. **Cost is the production-grade lens.** Obey-rate without cost is academic; obey-rate × cost-per-rule-fire × cost-per-session is the differentiator. Pricing already lived in `configs/pricing.yaml`; only the event source was missing.
3. **Five standalone CLIs answered slices of one question.** `cost_report.py`, `lifecycle_check.py`, `budget_disable_check.py`, `deprecation_watcher.py`, and `simulate_model_migration.py` each reported on rules, costs, retirements, or staleness independently. Slice 6 absorbs them into one `scripts/telemetry/report.py` so the monthly report is single-call, single-view.

## What

### Event source

Every L1 hook fire goes through `scripts/hook_dispatcher.py::dispatch(...)`. After matching rules against the trigger, the dispatcher calls `scripts.telemetry.rule_event_logger.log_event(...)`, which appends one JSONL line to `<consumer>/.ai-playbook-state/rule-events.jsonl`. The path resolves via `AI_PLAYBOOK_STATE_DIR` env var (override) or `<cwd>/.ai-playbook-state/` (default). The directory is gitignored at the consumer.

### Event schema

The canonical schema lives at `schemas/schema-rule-event-v1.json`. Required fields:

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Literal `"rule-event/v1"`. |
| `timestamp` | string | ISO 8601 UTC. |
| `slug` | string | Rule slug (D3 regex). |
| `llm` | string | Model identifier. |
| `verdict` | enum | `allow` / `block` / `warn`. |
| `latency_ms` | number | Hook overhead. |
| `session_id_hash` | string | sha256(session_id)[:8] — one-way. |
| `trigger` | string | E.g. `PreToolUse:Edit`. |
| `self_check` | boolean | True when the LLM self-validated per `## Process supervision`. |

Optional fields: `tokens_in`, `tokens_out`, `cache_read_tokens`, `escape_hatch`, `model`.

### Privacy guarantees

The logger applies four layered protections:

1. **One-way session hashing.** `hash_session_id(session_id)` returns 8 hex chars of sha256. The raw session_id is never persisted.
2. **PII-key scrubbing.** `scrub_event(event)` strips any key matching the denylist (`file_path`, `path`, `directory`, `diff`, `content`, `body`, `message`, `user_message`, `raw_input`, `tool_input`, `session_id`).
3. **Schema-allow-list.** Only the 13 schema fields are written; arbitrary additions are silently dropped.
4. **Gitignored at consumer.** The state directory is conventionally gitignored, so accidental commits cannot leak the JSONL.

Privacy invariants verified by `tests/test_telemetry_privacy.py`.

### Cost methodology

Pricing rows live in `configs/pricing.yaml`:

```yaml
claude-opus-4-7:
  input_per_1k:      0.015
  output_per_1k:     0.075
  cache_read_per_1k: 0.0015
```

For each event carrying `tokens_in` / `tokens_out` / `cache_read_tokens`, the report computes `cost_usd = (tokens_in / 1000) * input_per_1k + (tokens_out / 1000) * output_per_1k + (cache_read_tokens / 1000) * cache_read_per_1k`. Events without token fields (typical for PreToolUse hooks) contribute to obey-rate counts but not to cost columns.

### Report sections

`python -m scripts.telemetry.report monthly` emits eight sections:

1. **Obey-rate per rule × LLM** — the headline compliance metric.
2. **Cost per rule-fire** — token spend by rule.
3. **Cost per session** — aggregated by hashed session.
4. **Total spend over time** — per-day buckets.
5. **Models nearing retirement** — pulled from `configs/anthropic-retirement-list.yaml`.
6. **Break-glass usage** — `escape_hatch` event counts; flags >20% as systemic.
7. **OpenSpec staleness** — proposals not advancing within 30 days.
8. **Memory decay** — stub; full implementation deferred to Slice 7.

All eight sections render even on zero data with explicit placeholder copy. Empty event log → exit 0.

## How it relates to other concepts

- [agent-telemetry](agent-telemetry.md) — distinct, complementary. `agent-telemetry` captures OTLP traces of agent tool calls into Langfuse for post-hoc inspection. `telemetry-design` (this doc) captures rule-fire events into JSONL for obey-rate compliance metrics. Both can be enabled simultaneously; they have non-overlapping concerns.
- [enforcement-layers](enforcement-layers.md) — L1 / L2 / L3 layered enforcement; this telemetry instruments L1.
- [data-retention](data-retention.md) — the 7-day in-place + archive-thereafter rotation matches the broader retention policy.
- [model-routing](model-routing.md) §Cost — the pricing catalog format originated here.
- [model-migration](model-migration.md) — `_simulate_model_migration()` is now a subroutine of `report.py`, not a standalone CLI.

## Concrete example

A typical Edit on a project file emits this event:

```json
{
  "schema": "rule-event/v1",
  "timestamp": "2026-05-19T14:23:55Z",
  "slug": "english-only-docs",
  "llm": "claude-opus-4-7",
  "verdict": "allow",
  "latency_ms": 12.7,
  "session_id_hash": "a3f81c92",
  "trigger": "PreToolUse:Edit",
  "self_check": false
}
```

A monthly aggregation over a 30-day window with 12,400 events might produce:

```
| slug                  | llm              | total | allow | block | warn | obey_rate |
|-----------------------|------------------|-------|-------|-------|------|-----------|
| english-only-docs     | claude-opus-4-7  | 1240  | 1199  | 41    | 0    | 96.69%    |
| verdict-contract      | claude-opus-4-7  | 87    | 81    | 4     | 2    | 93.10%    |
| output-completeness   | claude-opus-4-7  | 312   | 311   | 0     | 1    | 99.68%    |
```

## Academic foundations

The design reuses methodology from five primary sources:

1. **arXiv 2310.13361** — "Evaluating LLM Rule Compliance under Prompt Injection" (Wei, Haghtalab, Steinhardt, 2023). Establishes the obey-rate metric as the central compliance lens.
2. **IFEval** — Zhou, Lu, Mishra et al., 2023. Instruction-following benchmark on Google's evaluation harness; the 60-line rule cap (D7) traces here.
3. **OWASP LLM Top 10 (2025)** — LLM01 prompt injection. The telemetry is the detection layer for prompt-injection-driven rule bypass.
4. **OpenTelemetry GenAI semantic conventions v1.36** — `gen_ai.usage.input_tokens` field naming aligned with the catalog. Cross-compatibility with existing OTLP exporters (Langfuse via `agent-telemetry.md`).
5. **Honeycomb 2024 "Observability for AI"** — privacy patterns (one-way session hashing, key denylist) for JSONL-first event shapes.

## Further reading

- [arXiv 2310.13361](https://arxiv.org/abs/2310.13361) — Rule compliance under prompt injection.
- [IFEval paper](https://arxiv.org/abs/2311.07911) — Instruction-following evaluation.
- [OWASP LLM Top 10 (2025)](https://owasp.org/www-project-top-10-for-large-language-model-applications/).
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).
- [run-telemetry-report runbook](../runbooks/run-telemetry-report.md) — how to generate the weekly / monthly report.
