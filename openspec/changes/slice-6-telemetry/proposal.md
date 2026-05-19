# slice-6-telemetry — Telemetry pipeline + 5-CLI absorption + 14 deferred hardrules

## Why

Five standalone CLIs (`cost_report.py`, `lifecycle_check.py`, `budget_disable_check.py`, `deprecation_watcher.py`, `simulate_model_migration.py`) each answer a slice of one larger question: "what is happening across this playbook and its consumers?" They share an event log shape (`events.jsonl`), a pricing catalog (`configs/pricing.yaml`), and a retirement catalog (`configs/anthropic-retirement-list.yaml`), but they were authored independently and never composed. The fragmentation prevents the playbook from answering the questions the v0.20.0 "world reference" milestone needs:

1. **Obey-rate per rule × LLM** — without per-rule-fire telemetry, we cannot prove rule compliance, only assert it. arXiv 2310.13361 and IFEval establish that LLMs drift on long instructions; the playbook needs measurement, not faith.
2. **Cost per rule-fire / per session** — token spend correlated with rule activity is the production-grade lens. Pricing is already in `configs/pricing.yaml`; the missing piece is the event source.
3. **Break-glass usage frequency** — `[no-doc-impact]` escape hatch from Slice 2 + `AIPLAYBOOK_*_SKIP` env-var bypasses are valuable, but their abuse signals systemic rule misfit. Slice 6 surfaces the rate.
4. **OpenSpec staleness, memory decay, model-retirement windows** — already implemented across `lifecycle_check.py` + `deprecation_watcher.py` + `simulate_model_migration.py`, but no consolidated monthly report.

Slice 5.F deferred 24 paired-hardrule implementations to Slices 6 + 7. Slice 6's target is the 14 hardrules tied to always-loaded rules (D16) and workflow/contract rules — both classes are telemetry-friendly: the value is "log the fire", not "block the action".

## What Changes

- **New `scripts/telemetry/` package** (3 modules):
  - `rule_event_logger.py` — emits one JSONL line per L1 hook fire to `<consumer>/.ai-playbook-state/rule-events.jsonl`. Fields per `schemas/schema-rule-event-v1.json`.
  - `anonymize.py` — hashes session_id (sha256, first 8 hex), scrubs file paths and diff bodies from any event payload (privacy invariant).
  - `report.py` — single CLI replacing the 5 standalone CLIs. Subcommands `weekly`, `monthly`, `custom --window-days N`. Emits markdown (default) or JSON (`--json`). Sections: obey-rate per rule × LLM, cost-per-rule-fire, cost-per-session, total spend over time, models nearing retirement, break-glass usage, openspec staleness, memory-decay marker.
- **New event schema** `schemas/schema-rule-event-v1.json` — JSON-Schema-validated rule-event shape; token fields optional.
- **New concept doc** `docs/concepts/telemetry-design.md` — event schema, privacy guarantees, cost methodology, academic references (arXiv 2310.13361, OWASP LLM Top 10, IFEval, etc.).
- **New runbook** `docs/runbooks/run-telemetry-report.md` — how to generate weekly/monthly reports.
- **Hook dispatcher integration** — `scripts/hook_dispatcher.py` now emits a `rule_event` on every L1 hook fire via `rule_event_logger.log_event(...)`. Latency budget: ≤5ms additional overhead (well under the D10 50ms SLA).
- **Escape-hatch tracking** — `_break_glass.py` and the doc-drift `[no-doc-impact]` path emit `escape_hatch_used` events.
- **14 deferred hardrules implemented** as paired `.rule.py` scripts (full implementation per spec, ≤100 LOC each):
  - Always-loaded (6): `verdict-contract`, `output-completeness`, `verification-before-completion`, `error-message-standard`, `apply-skill-enforcement`, `bootstrap-directive`.
  - Workflow/contract (8): `ai-reviewer-signoff`, `auto-merge-discipline`, `auto-pr-stream-closure`, `delegated-shipping-prompt`, `doc-drift-enforcement`, `github-project-board-schema`, `pr-tracker-reference`, `subagent-envelope-schema`.
- **5 standalone CLIs deleted** — `cost_report.py`, `lifecycle_check.py`, `budget_disable_check.py`, `deprecation_watcher.py`, `simulate_model_migration.py`. Their tests are deleted as well; their logic is absorbed into `report.py` as internal subroutines (`_compute_cost_per_rule`, `_check_retirement_window`, `_check_budget_breach`, `_check_openspec_staleness`, `_simulate_model_migration`).
- **Mkdocs Telemetry page** — `docs/telemetry.md` generated from `report.py --json`. Until consumers adopt v0.18.2 and produce real data, the page renders a "first data lands once consumers adopt v0.18.2" placeholder plus the metric definitions.
- **VERSION bump 0.18.1 → 0.18.2** + CHANGELOG entry.

## Impact

- **Consumers**: zero schema break. The event log writes to `<consumer>/.ai-playbook-state/rule-events.jsonl` (gitignored). No new mandatory frontmatter; nothing requires consumer migration.
- **CI behaviour**: `validate_pairing.py` (strict from 5.F) now sees 14 fewer deferred hardrules; the `deferred-hardrules.txt` allowlist shrinks from 24 to 10 slugs (Slice 7 absorbs the rest). Strict-mode exit 0 stays clean.
- **Deleted symbols**: `from scripts.cost_report import ...`, `from scripts.lifecycle_check import ...`, etc. — none have downstream consumers in the playbook itself; their CLIs were standalone. The new entry point is `python -m scripts.telemetry.report`.

## Versioning

VERSION bumps 0.18.1 → **0.18.2** per user-refined versioning 2026-05-19 (Slices 4–7 share the v0.18.x band; v0.19.x reserved for post-review fix iterations; v0.20.0 final cut on explicit user OK). Slice 6 = v0.18.2; Slice 7 (polish) bumps to v0.18.3 and then STOP for user review.
