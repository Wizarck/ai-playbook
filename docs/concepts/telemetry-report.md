# Telemetry report

> Rendered output of `python -m scripts.telemetry.report monthly`. Each section below is populated from `<consumer>/.ai-playbook-state/rule-events.jsonl` on every report generation.

## What this page reports

When real data lands, each of the eight sections below is populated from `<consumer>/.ai-playbook-state/rule-events.jsonl`:

### 1. Obey rate (per rule × LLM)

Headline compliance metric. For every (rule slug, LLM model) pair: how many fires resulted in `allow` vs `block` vs `warn`, with the obey rate (allow / total) shown as a percentage. Lower obey rate → rule under-spec'd or LLM drift. arXiv 2310.13361 establishes this as the central rule-compliance measurement.

### 2. Cost per rule-fire

For events carrying `tokens_in` / `tokens_out` / `cache_read_tokens`: cost-per-rule-fire in USD using `configs/pricing.yaml`. Identifies the rules whose fires dominate spend.

### 3. Cost per session

Aggregated by `session_id_hash` (one-way hash; the raw session_id is never persisted). Surfaces outlier sessions.

### 4. Total spend over time

Per-day buckets of total LLM spend. Trend line for the budgeting conversation.

### 5. Models nearing retirement

Models from `configs/anthropic-retirement-list.yaml` with `retirement_date - now <= 90 days`. Drives the `python -m scripts.telemetry.report` model-migration workflow.

### 6. Break-glass usage

Counts of `escape_hatch` events:

- `[no-doc-impact]` — doc-drift PR-title bypass.
- `AIPLAYBOOK_*_SKIP` — env-var bypass of an individual rule.
- `--force-with-reason` — formal break-glass via `scripts/_break_glass.py`.

Flagged as **systemic** when escape-hatch ratio exceeds 20% of all events in the window.

### 7. OpenSpec staleness

OpenSpec changes (`openspec/changes/<change-id>/`) without an `archive/` child whose oldest file mtime is >30 days old. Surfaces stale proposals so the maintainer can finalize or close them.

### 8. Memory decay

Counts `hindsight.retain` events older than 90 days.

## Architecture references

- [Concept: telemetry-design](telemetry-design.md) — event schema, privacy guarantees, cost methodology, academic references.
- [Runbook: run-telemetry-report](../runbooks/run-telemetry-report.md) — how to generate weekly / monthly / custom reports.
- [Schema: rule-event v1](../../schemas/schema-rule-event-v1.json) — JSON Schema for the event log.

## Privacy

- One-way session_id hashing (sha256, 8 hex chars).
- PII-key denylist (`file_path`, `path`, `diff`, `content`, `body`, `message`, ...).
- Schema-allow-list — only the 13 fields defined in `schema-rule-event-v1.json` survive.
- Gitignored at the consumer (`<consumer>/.ai-playbook-state/`).
