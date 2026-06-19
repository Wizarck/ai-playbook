---
schema: runbook/v1
slug: run-telemetry-report
description: Generate the weekly or monthly telemetry report (obey-rate, cost, lifecycle) from the consumer's rule-events.jsonl log.
audience: developer
estimated_time: 1-3 min
last_validated: "2026-06-19"
---

# Generate the telemetry report

## Outcome

A markdown (or JSON) report summarising the playbook's behaviour over the last 7, 30, or N days, covering obey-rate per rule × LLM, cost per rule-fire / session / day, model-retirement windows, break-glass usage, and OpenSpec staleness. Empty event log → graceful "no events" placeholder, exit 0.

## When to use this

- **Weekly cadence** — Monday morning quick pulse on rule compliance and spend.
- **Monthly cadence** — full lifecycle review (retirements + staleness + decay).
- **Custom window** — investigating a specific incident; pass `--window-days N`.
- **CI integration** — the v0.18.3 Telemetry mkdocs page is generated from `report.py --json` output.

Skip when the consumer has not yet adopted v0.18.2; the report will exit 0 with an empty body until the hook dispatcher starts writing events.

## Prerequisites

- `python` (3.11+) in PATH.
- The playbook submoduled at `<consumer>/.ai-playbook/` OR the report invoked from the playbook root.
- `configs/pricing.yaml` present (ships in the playbook) for cost columns.
- `configs/anthropic-retirement-list.yaml` present for the retirement section.
- For cost data: events must carry `tokens_in` / `tokens_out`. PreToolUse-only events still contribute to obey-rate but not to cost columns.

## Steps

### 1. Confirm the event log exists

```bash
cd C:/Projects/<consumer>
ls .ai-playbook-state/rule-events.jsonl
```

If the file is missing, the dispatcher has not fired yet — invoke any tool that triggers a hook (e.g., open a file with `Edit`) and re-check. If the directory is gitignored (the canonical setup), this is expected for fresh checkouts.

### 2. Run the report (weekly)

```bash
python -m scripts.telemetry.report weekly
```

Markdown output streams to stdout. Pipe into a file or paste into the PR:

```bash
python -m scripts.telemetry.report weekly > weekly-telemetry-$(date +%Y-%m-%d).md
```

### 3. Run the report (monthly)

```bash
python -m scripts.telemetry.report monthly
```

The monthly variant produces the same eight sections but over a 30-day window. Use this for retros and for the v0.18.3 Telemetry mkdocs page.

### 4. Run the report (custom window)

```bash
python -m scripts.telemetry.report custom --window-days 14
```

Useful for incident-bracketed reports — pick the window that aligns with the incident timeline.

### 5. JSON output for downstream tooling

```bash
python -m scripts.telemetry.report monthly --json > telemetry.json
```

The JSON shape mirrors the markdown layout one-to-one (one key per section). Downstream consumers (dashboards, the mkdocs page generator) parse this directly.

### 6. Override state directory (testing only)

```bash
AI_PLAYBOOK_STATE_DIR=/tmp/synthetic-state python -m scripts.telemetry.report weekly
```

Useful for regression testing the report against curated synthetic event logs.

## Verification

- Exit code is `0` on any well-formed invocation, including empty event logs.
- Markdown output has all eight section headers (`## 1.` through `## 8.`).
- JSON output passes `python -m json.tool`.
- Cost columns are non-empty when `configs/pricing.yaml` is present AND at least one event in the window carries token fields.

## Troubleshooting

### Symptom: `❌ custom subcommand requires --window-days N`
**Cause**: `report.py custom` invoked without `--window-days`.
**Fix**: pass `--window-days 14` (or another positive integer).

### Symptom: all cost columns show `_No cost-bearing events_`
**Cause**: events in the log only have PreToolUse fields (no token counts).
**Fix**: this is expected for pure-hook telemetry. Token-bearing events land when `scripts/log_event.py` is integrated with the LLM call sites (per [agent-telemetry](../concepts/agent-telemetry.md)). No action needed.

### Symptom: `## 5. Models nearing retirement` is empty
**Cause**: `configs/anthropic-retirement-list.yaml` `retirements:` list is empty (the default until a real retirement is announced).
**Fix**: not a bug. The section will populate when an entry is added to the catalog.

### Symptom: `_No stale OpenSpec changes_` but an OpenSpec change is clearly stale
**Cause**: the report walks `openspec/changes/` relative to the playbook root; the consumer's own `openspec/changes/` is not the default target.
**Fix**: pass `--openspec-dir <path-to-consumer-openspec>` to override.

### Symptom: malformed JSONL line warning
**Cause**: a partial write (typically from a crashed process). The line is skipped silently; the report is still valid.
**Fix**: optionally truncate the corrupt line:
```bash
grep -v '<corrupted-fragment>' .ai-playbook-state/rule-events.jsonl > .tmp && mv .tmp .ai-playbook-state/rule-events.jsonl
```

## Automate it as a GitHub issue (opt-in, v0.19.24+)

Instead of running the report by hand, the weekly digest can be posted to a
GitHub issue (label `telemetry-report`, updated in place) on a Monday cron. It is
**opt-in and OFF by default** — enable the `telemetry_weekly_issue` global flag
(config UI → Global flags, or `bundle.global_flags.telemetry_weekly_issue: true`),
then re-apply / re-bootstrap:

- `apply_config` seeds `.github/workflows/rule-event-report-weekly.yml` (seed-only
  — it never clobbers your edits; delete the file to turn it off or to re-seed).
- `bootstrap` creates the `telemetry-report` label (best-effort `gh`; prints the
  manual command if `gh` is unavailable).
- A window with **0 events is skipped**, so an idle repo never gets an empty
  issue.

Details: [Concept: telemetry-design → Weekly digest issue (opt-in)](../concepts/telemetry-design.md).

## Related

- [Concept: telemetry-design](../concepts/telemetry-design.md) — event schema, privacy guarantees, cost methodology, academic references.
- [Concept: agent-telemetry](../concepts/agent-telemetry.md) — OTLP-based tracing for agent tool calls (Langfuse). Complementary to rule-event telemetry.
- [Rule: break-glass](../rules/break-glass.rule.md) — `escape_hatch` events feed the §6 monthly report column.
- [Schema: rule-event v1](../../schemas/schema-rule-event-v1.json) — JSON Schema for events.
