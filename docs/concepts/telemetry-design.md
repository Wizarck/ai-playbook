---
schema: concept/v1
slug: telemetry-design
title: Telemetry pipeline design
summary: |
  Rule-event telemetry pipeline shipped in Slice 6 (v0.18.2): every L1
  hook fire writes a JSONL row, the report CLI aggregates them into
  obey-rate / cost / lifecycle metrics. Covers event schema, privacy
  guarantees, and the academic references that motivated the design.
last_validated: "2026-05-25"
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

The canonical schema lives at `schemas/schema-rule-event-v2.json` (v0.20.0+; v1 is the previous frozen revision at `schemas/schema-rule-event-v1.json`).

**Required fields (unchanged across v1 → v2):**

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Literal `"rule-event/v2"`. |
| `timestamp` | string | ISO 8601 UTC. |
| `slug` | string | Rule slug (D3 regex). |
| `llm` | string | Model identifier. |
| `verdict` | enum | `allow` / `block` / `warn`. |
| `latency_ms` | number | Hook overhead. |
| `session_id_hash` | string | sha256(session_id)[:8] — one-way. |
| `trigger` | string | E.g. `PreToolUse:Edit`, `PreToolUse:Bash`. |
| `self_check` | boolean | True when the LLM self-validated per `## Process supervision`. |

**Optional fields (v1):** `tokens_in`, `tokens_out`, `cache_read_tokens`, `escape_hatch`, `model`.

**Optional fields added in v2** (consumed by `report.py compute_block_breakdown` / `compute_top_blocked_paths` / `compute_override_ratio`):

| Field | Type | Meaning |
|---|---|---|
| `block_class` | enum | Decision classification: `none` / `apply_phase_bypass` / `outside_project` / `change_own_folder` / `flag_disabled` / `helper_missing` / `rule_disabled`. `rule_disabled` is emitted by the L1 hook + `cli_emit` wrapper when the consumer's `.ai-playbook/rules-toggle.json` says the rule is OFF (see [ai-playbook-config.md](ai-playbook-config.md)). |
| `block_tool` | enum | `Edit` / `Write` / `MultiEdit` / `Bash` — typed mirror of trigger suffix. |
| `toggle_layer` | enum | Present when `block_class=rule_disabled`. One of `L1` / `L2` / `L3` — identifies which layer of the rules-toggle short-circuited the decision. Only `L1` is observable in runtime telemetry today (the L3 short-circuit lives in workflow YAML, not the event stream). |
| `change_id` | string | OpenSpec change slug whose write_paths matched. |
| `matched_pattern` | string | Literal/glob from `tasks.md` that matched (debugging FP/FN). |
| `target_rel` | string | Project-relative path the tool tried to mutate. **No PII** — see "Privacy guarantees" below. |
| `bash_pattern_kind` | enum | Heuristic that fired on a Bash command. Closed set (15 values); see [apply-skill-enforcement.rule.md](../rules/apply-skill-enforcement.rule.md) "Bash heuristics". |
| `marker_present` | boolean | True when a `start` record was found for the matched change. |
| `override_reason` | string | Provided via `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` (≥10 chars). |
| `feature_flag` | object | Snapshot of feature-flag env vars (e.g. `{bash_inspection: "0"}`). |

Forward-compatibility: schema v2 retains `additionalProperties: false`. Future additions land as `rule-event/v3`. Consumers running strict validators against the JSONL log are expected to upgrade to the v2 schema when bumping the playbook submodule past v0.20.0.

### Privacy guarantees

The logger applies four layered protections:

1. **One-way session hashing.** `hash_session_id(session_id)` returns 8 hex chars of sha256. The raw session_id is never persisted.
2. **PII-key scrubbing.** `scrub_event(event)` strips any key matching the denylist (`file_path`, `filepath`, `path`, `directory`, `dir`, `diff`, `content`, `body`, `message`, `messages`, `user_message`, `raw_input`, `tool_input`, `stdin`, `session_id`).
3. **Schema-allow-list.** Only the schema fields enumerated in v2 are written; arbitrary additions are silently dropped.
4. **Gitignored at consumer.** The state directory is conventionally gitignored, so accidental commits cannot leak the JSONL.

Privacy invariants verified by `tests/test_telemetry_privacy.py`.

#### Why `target_rel` and `matched_pattern` are not PII

Both fields contain **paths within the consumer repo** (e.g. `backend/foo.py`, `backend/services/*.py`). These are:
- Already committed under the consumer's `tasks.md` (`## Owns (write_paths)`).
- Not user data, customer data, or external secrets.
- Necessary for `report.py` to produce useful "Top blocked paths" / "Block reasons" aggregations.

Field names deliberately avoid the literal substring `path` (denylisted by `scrub_event` as an exact key match — `target_rel`/`matched_pattern` instead of `target_path`/`matched_write_path`) so that future hardening of the denylist (e.g. a substring match) does not silently filter them. If the denylist is ever extended to substring matching, these field names remain safe.

The **raw Bash command is NEVER logged.** Only the matched `bash_pattern_kind` (a closed-set enum value) is recorded. This means a command containing tokens, paths to user files, or arbitrary literals never enters the JSONL.

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

A typical allow on an unrelated path emits a minimal v2 event:

```json
{
  "schema": "rule-event/v2",
  "timestamp": "2026-05-25T14:23:55Z",
  "slug": "english-only-docs",
  "llm": "claude-opus-4-7",
  "verdict": "allow",
  "latency_ms": 12.7,
  "session_id_hash": "a3f81c92",
  "trigger": "PreToolUse:Edit",
  "self_check": false
}
```

A Bash block on a write_path bypass emits the enriched fields:

```json
{
  "schema": "rule-event/v2",
  "timestamp": "2026-05-25T14:24:10Z",
  "slug": "apply-skill-enforcement",
  "llm": "claude-opus-4-7",
  "verdict": "block",
  "latency_ms": 8.2,
  "session_id_hash": "a3f81c92",
  "trigger": "PreToolUse:Bash",
  "self_check": false,
  "block_class": "apply_phase_bypass",
  "block_tool": "Bash",
  "change_id": "transfer-tech-debt-sweep",
  "matched_pattern": "backend/**/*.py",
  "target_rel": "backend/app/blueprints/transfer/router.py",
  "bash_pattern_kind": "sed-i",
  "marker_present": false,
  "feature_flag": {"bash_inspection": "1"}
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
