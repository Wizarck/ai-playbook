# model-migration.md

> **Status**: v1.0.0 — wired-pending-trigger. `activated_at: pending-event`. Authored under OpenSpec change `complete-ir-and-model-migration-specs` (Phase 5 P5.7) on 2026-05-01. Sibling to [`docs/concepts/model-routing.md`](../docs/concepts/model-routing.md) v2.0.0 and [`docs/concepts/incident-response.md`](../docs/concepts/incident-response.md) v1.0.0.
>
> v1.0.0 means: the trigger is detectable, the playbook is runnable, the simulator validates a synthetic substitution, but no real Anthropic deprecation has executed it. The first entry in [`configs/anthropic-retirement-list.yaml`](../configs/anthropic-retirement-list.yaml) with `retirement_date` ≤ 90 days out OR an explicit `MODEL_MIGRATION_REQUESTED=<from>:<to>` env var flips this to `active`.

A pinned model retiring is **not** an incident — it is a planned, telegraphed event. This runbook turns it from "Anthropic emails Arturo on a Tuesday" into a mechanical procedure: detector fires → call sites enumerated → substitute proposed → CI canary → human review → merge. No improvisation.

---

## 1. When to use this runbook

A provider (Anthropic, Google, OpenAI, future others) deprecates a model ID that is pinned in [`configs/litellm-router.yaml`](../configs/litellm-router.yaml) OR appears as a literal in code reachable through `scripts/_llm.py`. Example today: `claude-haiku-4-5` retired for `claude-haiku-5-0`.

**Out of scope:**
- A new model ships and is *better*: that is a routing-matrix update, not a migration. Lands in `model-routing.md` via standard PR.
- A provider goes fully offline: that is an S2 incident (scenario #6 in [incident-response.md](../docs/concepts/incident-response.md) §4), not a migration.

---

## 2. Trigger event definition (machine-checkable)

Two paths, **either** activates:

### 2.1 Curated retirement list (primary)

Entry appears in [`configs/anthropic-retirement-list.yaml`](../configs/anthropic-retirement-list.yaml) with:

```yaml
- model_id: claude-haiku-4-5
  provider: anthropic
  announced_date: 2026-09-01
  retirement_date: 2026-12-01
  successor: claude-haiku-5-0
  deprecation_url: https://docs.anthropic.com/en/docs/about-claude/model-deprecations
```

Detector [`scripts/lifecycle_check.py`](../scripts/lifecycle_check.py) check `model_retirement_detected` fires when `retirement_date - now ≤ 90 days`. Per D4.3, this YAML is **manually curated** — no RSS scraping. Anthropic publishes deprecations ~2× per year and announcements go to the API account email; missing one is recoverable as long as fallback in [model-routing.md](../docs/concepts/model-routing.md) §3 works.

### 2.2 Manual override (escape hatch)

Operator sets:

```bash
MODEL_MIGRATION_REQUESTED=<from-model-id>:<to-model-id>
```

Used when (a) provider sent direct email outside the retirement list, (b) Arturo wants to migrate proactively for cost or quality reasons, (c) testing the playbook before a real retirement lands. The simulator (`scripts/simulate_model_migration.py`) accepts this env var and runs the full procedure dry.

State stored in `~/.ai-playbook/state/triggers.json` to avoid double-fire. Idempotent across runs in the same window.

---

## 3. Migration playbook (per pinned model)

Sequence is **strictly ordered** — skipping a step is a `--force-with-reason` event under [break-glass.md](../docs/rules/break-glass.rule.md).

### Step 1 — Detector fires

`model_retirement_detected` surfaces in:

- Monthly markdown report at `<consumer>/reports/lifecycle/<YYYY-MM>.md` under "Activation triggers".
- `warn`-level notification per [notification-policy.md](../docs/concepts/notification-policy.md) (Telegram + JSONL queue if available, else direct JSONL append).

Output payload:

```
model_id: claude-haiku-4-5
retirement_date: 2026-12-01
days_remaining: 73
successor: claude-haiku-5-0
call_sites_count: <N>
suggested_env_var: MODEL_MIGRATION_REQUESTED=claude-haiku-4-5:claude-haiku-5-0
```

### Step 2 — Identify call sites

Two sources, in order:

1. **`verify_llm_routing.py`** (Change C). Greps every consumer for the deprecated model ID across `scripts/`, `langgraph-aiops/`, `consumer-d_ops/`, `configs/`. Output: file + line number per occurrence, plus task class context where derivable.
2. **Fallback regex sweep** (when `verify_llm_routing.py` is absent). Pattern: `(claude|gemini|gpt-)[a-z0-9.-]+` scoped to the same paths. Manual triage required to filter out doc references.

Both produce the same shape: `(path, line, model_id, suggested_substitute)` rows.

### Step 3 — Look up substitute

Read [`docs/concepts/model-routing.md`](../docs/concepts/model-routing.md) §1 decision matrix (task class → tier → model). For each call site:

- Identify the task class (from `_llm.call(task_class, ...)` argument or context).
- Look up the substitute in the same tier as the deprecated model.
- One substitute per task class — do **not** mix substitutes across the same task class within a single migration PR.

If a call site's task class cannot be inferred (e.g. a literal model ID in a config without context), the migration PR for that site is split out and assigned `❓ CLARIFICATION NEEDED` per [agentic-failures.md](../docs/concepts/agentic-failures.md).

### Step 4 — Open auto-PRs

One PR per consumer per substitution. PR body must include:

- Detector report (Step 1 payload).
- Substitute reasoning (which row of `model-routing.md` decision matrix justifies the swap).
- Rollback steps (revert PR pin + revert config diff).
- CI canary plan (Step 5).

Body header is generated by `scripts/simulate_model_migration.py --emit-pr-body`. PR labels: `model-migration`, `auto-pr`. Auto-PR uses the `MigrationPRBot` GitHub App when available, else falls back to manual `gh pr create`.

### Step 5 — CI canary

Synthetic prompt set runs against the substitute. Comparison against baseline:

- **Cost** — substitute total tokens ≤ 2× baseline. Hard block if > 2×.
- **Latency** — substitute p95 ≤ 1.5× baseline. Hard block if > 1.5×.
- **Trace structure** — Langfuse trace shape (span count, tool-call sequence) within ±1 span of baseline. Soft warn if ±2.

Canary prompts live in `tests/fixtures/model-migration-canary/<task-class>.json`. Each PR runs the canary in CI; results posted as a PR comment. Hard block fails CI.

### Step 6 — Human review + merge

Arturo (or successor) reviews. Approval criteria:

- Canary passed (no hard block, soft warns annotated).
- Rollback procedure makes sense.
- Substitute model is the same generation tier (e.g. don't substitute Haiku for Sonnet without a routing-matrix change first).

On merge, the consumer's `events.jsonl` gets a `model_migration.applied` event with `from`, `to`, `pr_url`, `merged_at`.

---

## 4. Fallback behavior during transition

Until the migration PR merges, callers continue to hit the deprecated model. Two safeguards prevent breakage:

- **LiteLLM proxy fallback chain** (per [model-routing.md](../docs/concepts/model-routing.md) §3). If the deprecated model 5xx's during the transition window, the proxy auto-fails over to the next-best-equivalent in the same task class. Emits `gen_ai.routing.fallback_depth > 0` event.
- **Degradation banner** (per [degradation-modes.md](../docs/concepts/degradation-modes.md)). When `MODEL_MIGRATION_IN_PROGRESS=<from>:<to>` env var is set on the consumer, `inject_context.py` injects a `DEGRADED_CONTEXT` banner into agent system prompts: "Model migration in progress: substituting X with Y. Trace context preserved." Helps debug any quality regression visible to end users.

---

## 5. Rollback path

If the substitute misbehaves in prod (latency spike, accuracy drop visible in Langfuse, customer complaint):

1. Revert the migration PR. Pinned model returns to deprecated value (still works during the deprecation window — Anthropic typically allows ≥ 30 days post-retirement-date for stragglers, but verify per `deprecation_url`).
2. File an incident per [incident-response.md](../docs/concepts/incident-response.md) — typically S2 (degradation, fallbacks holding) unless the substitute completely broke a customer-visible flow (then S1).
3. Add a row to `tests/fixtures/model-migration-canary/<task-class>.json` capturing the regression case so the next attempt's canary catches it.
4. Open an `❓ CLARIFICATION NEEDED` issue: which model in the routing matrix should replace the failed substitute? Answer feeds the next migration attempt.

If the deprecated model is fully retired and the substitute is broken, the only path is **forward** — a different substitute, not rollback. That branch lives in incident-response.md scenario #6 territory.

---

## 6. Communication contract

Migrations are user-visible only when something regresses. The contract:

- **Pre-migration** (PR opened): no customer comm. Internal Telegram notice via `notify.py warn`.
- **During canary** (CI running): no comm.
- **Post-merge, normal**: no comm. Just an `events.jsonl model_migration.applied` event.
- **Post-merge with regression**: file incident per §5 step 2; comm follows [incident-response.md](../docs/concepts/incident-response.md) §7 templates.

While the migration PR is open, dashboards + retain entries are tagged with `MODEL_MIGRATION_IN_PROGRESS=<from>:<to>` so debugging context is preserved across the transition. Tag is removed when the PR merges (or is closed without merge).

---

## 7. Cross-references

- [`docs/concepts/model-routing.md`](../docs/concepts/model-routing.md) v2.0.0 — substitution matrix; primary input to Step 3.
- [`configs/litellm-router.yaml`](../configs/litellm-router.yaml) — runtime routing config; output of Step 4 PRs.
- [`configs/anthropic-retirement-list.yaml`](../configs/anthropic-retirement-list.yaml) — curated retirement list; primary trigger source.
- [`scripts/_llm.py`](../scripts/_llm.py) — canonical helper; every migrated call site uses this.
- [`scripts/verify_llm_routing.py`](../scripts/verify_llm_routing.py) — drift detector reused for Step 2 enumeration.
- [`scripts/lifecycle_check.py`](../scripts/lifecycle_check.py) — host of the `model_retirement_detected` check.
- [`scripts/simulate_model_migration.py`](../scripts/simulate_model_migration.py) — dry-run validator + PR-body generator.
- [`docs/concepts/incident-response.md`](../docs/concepts/incident-response.md) §4 scenario #6 — provider outage path (different from migration).
- [`docs/concepts/degradation-modes.md`](../docs/concepts/degradation-modes.md) — banner contract during in-flight migrations.
- [`docs/rules/break-glass.rule.md`](../docs/rules/break-glass.rule.md) — `--force-with-reason` for skipping a step.

---

## 8. What does NOT live here

- **The substitution table itself.** That is `model-routing.md`. This file describes the procedure to apply substitutions; the substitutions are data.
- **Cost optimisation guidance.** Cost-driven model swaps are not migrations; they're routing decisions.
- **Provider onboarding.** Adding OpenAI / Mistral / Cohere as a new provider is a separate spec change, not a migration.

---

## Decisions

- **D4.3** Curated `anthropic-retirement-list.yaml`, not RSS scraping. Rationale: cadence is low (~2×/year), scrapers are brittle, manual update is a 1-line PR.
- **D4.7** YAML lives in `ai-playbook` (shared), not per-consumer. Rationale: a model retirement is universal across consumers; per-consumer copies would drift.
- **D4.8** One PR per consumer per substitution. Rationale: revertibility is per-consumer; a regression at one consumer should not require reverting elsewhere.
- **D4.9** Hard CI block on > 2× cost or > 1.5× p95 latency. Rationale: a substitute that costs 3× or runs 2× slower is functionally a different model; treat it as a routing decision (re-tier in `model-routing.md`), not a drop-in migration.
- **D4.10** Rollback path uses the deprecated model itself, not a fallback. Rationale: during the deprecation window the deprecated model still works; using it for rollback is faster than rolling forward to a third model.
