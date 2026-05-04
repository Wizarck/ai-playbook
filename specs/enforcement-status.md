# enforcement-status.md

> **Status**: v1.0.0. Companion to every spec in this repo. The matrix below
> distinguishes **wired** (enforced by code or harness today) from
> **aspirational** (specified contract, no enforcement code yet).

The playbook is part framework, part documented protocol. This file makes
explicit which is which. A future contributor adding enforcement to a row
flips it from "spec-only" to "wired" + ships the test.

---

## Status legend

| Symbol | Meaning |
|---|---|
| ✅ wired | Enforcement code exists; tests cover it; pre-commit/CI fires it |
| 🟡 partial | Some enforcement exists but coverage incomplete; gaps named |
| 📋 spec-only | Contract documented; humans + agents commit to it; no automated enforcement today |
| 📌 deferred | Activates on a documented trigger (e.g. first paying client, first model retirement) |
| 🟠 wired-pending-trigger | Spec is v1.0.0 (runnable + simulators + detector wired); flips to ✅ when a real activation event fires |

---

## Per-spec enforcement status

| Spec | Status | Enforcement detail |
|---|---|---|
| [agent-contract.md](agent-contract.md) | 📋 spec-only | JSON Schema published at [`agent-contract.schema.json`](agent-contract.schema.json). No harness validates spawn envelopes today; agents that spawn subagents follow the shape by convention. Activation: when a real `Task`-tool harness ships, wire `jsonschema.validate` at spawn time. |
| [agentic-failures.md](agentic-failures.md) | 📋 spec-only | 12 failure-mode taxonomy. Active detectors: `prompt_injection_filter.py` (mode 2.3 partial), `secrets_scan.py` (mode 2.11 wired). Modes 2.1, 2.2, 2.4–2.10, 2.12 are documented but no automated detector runs. Retros surface failures retrospectively, not in real time. |
| [agents-md-v1.schema.json](agents-md-v1.schema.json) | ✅ wired | `schema_validate.py` enforces every consumer's `AGENTS.md` frontmatter. Pre-commit hook, CI, and `bootstrap.py` all run it. Tests cover happy + every failure shape. |
| [auto-managed-sections.md](auto-managed-sections.md) | 🟡 partial | `auto_managed.py` regenerates marked sections; tests cover the script. CI lacks a "all auto-managed sections are fresh" check — easy to add but not wired. |
| [bootstrap-directive.md](bootstrap-directive.md) | ✅ wired | `schema_validate.py` requires §0 in every `AGENTS.md`. SessionStart hooks fire `inject_context.py` to deliver the data the directive references. Both consumer-side hooks tested manually 2026-04-25; e2e test on the integration harness lands in v0.3.x. |
| [break-glass.md](break-glass.md) | ✅ wired | Every blocking script imports `_break_glass.py`; canonical error format enforced; `overrides.log` is the audit trail; OTel span `ai_playbook.override.*` emitted (no-op when tracing disabled). 13 tests. |
| [channels.md](channels.md) | 📋 spec-only | Solo-state inventory; no automated channel-routing today. |
| [data-retention.md](data-retention.md) | 🟡 partial | Hindsight enforces its own decay (90-day soft); `lifecycle_check.py` flags stale OpenSpec changes. PII deletion path is documented; no automated `forget` script today. |
| [degradation-modes.md](degradation-modes.md) | ✅ wired | `inject_context.py` writes `DEGRADED_CONTEXT` banners; `retain_memory.py` queues to `hindsight-queue.jsonl`; `_hindsight.py::HttpResult.reason` discriminates `degraded:*` vs `error:*`. Tests cover all paths. |
| [dispatcher-chain.md](dispatcher-chain.md) | ✅ wired | 3-level chain enforced by `schema_validate.py` (level 2 frontmatter), `discover_projects.py` (level 3 personal flag), and `~/.claude/CLAUDE.md` resolver (registry lookup). |
| [env-vars.md](env-vars.md) | 🟡 partial | Documented authoritatively; consumers grep'd against this file in retros. No CI check that `os.environ.get(...)` calls in `scripts/` only reference vars listed here. |
| [error-message-standard.md](error-message-standard.md) | ✅ wired | `verdict_lint.py --shape error` enforces the ❌/FIX/OVERRIDE shape. Every blocking script in `scripts/` follows it. |
| [incident-response.md](incident-response.md) | 🟠 wired-pending-trigger | Promoted from 📌 → 🟠 on 2026-05-01 by OpenSpec change [`complete-ir-and-model-migration-specs`](../../openspec/changes/complete-ir-and-model-migration-specs/proposal.md) (Phase 5 P5.6). v1.0.0 ships with: 8 S1–S4 scenario rows + on-call ladder (solo / family-of-3 / team-of-N) + 7-day post-mortem trigger detector + comm templates + 4 stub recovery runbooks (`runbook-vps-down`, `runbook-db-corruption`, `runbook-key-rotation-emergency`, `runbook-secrets-leak-containment`). Activation trigger detector `first_paying_client_detected` lives in [`scripts/lifecycle_check.py`](../scripts/lifecycle_check.py). Simulator: [`scripts/simulate_incident_response.py`](../scripts/simulate_incident_response.py). Status flips 🟠 → ✅ when a `consumers.yaml` entry has `paying_tier` + `sla_signed` (within 30 days) OR a non-Arturo `oncall_eligible: true` entry lands. |
| [model-migration.md](../docs/model-migration.md) | 🟠 wired-pending-trigger | New row — added on 2026-05-01 by OpenSpec change [`complete-ir-and-model-migration-specs`](../../openspec/changes/complete-ir-and-model-migration-specs/proposal.md) (Phase 5 P5.7). v1.0.0 ships with: trigger taxonomy (curated YAML at [`configs/anthropic-retirement-list.yaml`](../configs/anthropic-retirement-list.yaml) + `MODEL_MIGRATION_REQUESTED` env var) + 6-step playbook + canary thresholds (≤2× cost, ≤1.5× p95) + rollback path. Activation trigger detector `model_retirement_detected` lives in [`scripts/lifecycle_check.py`](../scripts/lifecycle_check.py). Simulator: [`scripts/simulate_model_migration.py`](../scripts/simulate_model_migration.py); integrates with [`scripts/verify_llm_routing.py`](../scripts/verify_llm_routing.py) when present. Status flips 🟠 → ✅ when an entry in the retirement YAML reaches `retirement_date - now ≤ 90 days` and Arturo runs the playbook end-to-end. |
| [issue-tracking.md](issue-tracking.md) | 🟡 partial | Jira sync via `issue_sync.py` wired; GitHub issue creation works. The dual-flow (community vs enterprise) decision rule is documented but not enforced — humans place issues in the right tracker by convention. |
| [mcp-servers-schema.md](mcp-servers-schema.md) | ✅ wired | `scripts/mcp/validate.py` validates every layer; `scripts/mcp/render.py` produces `.mcp.json` + `.gemini/settings.json`; `scripts/check_mcp_drift.py` (v0.3.0+) detects drift between legacy and v1 yamls. |
| [memory-hierarchy.md](memory-hierarchy.md) | ✅ wired | Tier 3 (Hindsight) wired end-to-end via `_hindsight.py` + `inject_context.py` + `retain_memory.py` + SessionStart hooks. Tier 1 (session) is implicit. Tier 2 (project) and Tier 4 (universal/git) rely on git itself. Decay policy §6 is documented; Hindsight's server-side TTL enforces it. |
| [migration-guide.md](migration-guide.md) | ✅ wired | `schema_validate.py --autofix` honours the contract verbatim. v0 → v1 migration tested. |
| [model-routing.md](model-routing.md) | ✅ wired | Routing matrix in [`configs/litellm-router.yaml`](../configs/litellm-router.yaml) consumed by the LiteLLM proxy (port 4000). Every call goes through [`scripts/_llm.py`](../scripts/_llm.py); drift detector [`scripts/verify_llm_routing.py`](../scripts/verify_llm_routing.py) catches direct-SDK callers — wired into [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) on 2026-05-05 (warn-only per D3.5; strict-mode promotion target 2026-06-05 after 30 green-build days). Wired 2026-05-01 by OpenSpec change [`add-litellm-enforcement`](../../openspec/changes/add-litellm-enforcement/proposal.md), Phase 5 P5.4. Historical call-site migrations: [`scripts/prompt_injection_filter.py`](../scripts/prompt_injection_filter.py) migrated 2026-05-05; `consumer-d/lib/advisor.py` migration in flight (manual 2-call paths to `_llm.call`; native Anthropic advisor-tool beta retains `# llm-routing-allow: native-advisor-beta` since LiteLLM cannot tunnel the `advisor_20260301` tool block). No "Hermes adapter" Python module exists — Hermes is a separate container that consumes the LiteLLM proxy directly via OpenAI-compatible API; no in-tree migration required. |
| [notification-policy.md](notification-policy.md) | ✅ wired | `scripts/notify.py` enforces the 4 levels + per-event policy + rate limit. SMTP fan-out + JSONL queue verified end-to-end. |
| [notification-queue.md](notification-queue.md) | 🟡 partial | JSONL append + dedup wired. T25+ (Phase 5) adds the durable-queue + retry-with-backoff layer. |
| [parallel-review.md](parallel-review.md) | 📋 spec-only | 3-layer pattern documented. Skills exist (`bmad-code-review`, `bmad-review-edge-case-hunter`, `bmad-review-adversarial-general`) and humans / agents invoke them. No coordinator script verifies all 3 ran on a given artefact. |
| [post-mortem.md](post-mortem.md) | 📋 spec-only | Template ships at [`../templates/post-mortem.md.tmpl`](../templates/post-mortem.md.tmpl). No automation that detects "S1 incident → 7-day post-mortem due"; humans drive the cadence. |
| [projects-registry.md](projects-registry.md) | ✅ wired | `discover_projects.py` reads + writes `~/.ai-playbook/projects.yaml`; the registry is consumed by `bump_consumers.py` and `~/.claude/CLAUDE.md` for path resolution. |
| [prompt-caching.md](prompt-caching.md) | 📋 spec-only | Order matrix documented. Anthropic SDK callers reference `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN`. No CI check that prompts are constructed in stable→volatile order. |
| [retrospective-cadence.md](retrospective-cadence.md) | 🟡 partial | `lifecycle_check.py` generates the monthly retro skeleton + flags stale changes/overrides/notification anomalies. Post-archive + weekly retros are human-driven. |
| [role-matrix.md](role-matrix.md) | 📋 spec-only | 4 people-roles + 5 ServiceAccount RBAC rows documented. Solo-state today (Arturo only); GitHub branch protections are configured per repo. No code enforces "Reviewer cannot merge to master" beyond GitHub's own permissions. |
| [rollout-strategy.md](rollout-strategy.md) | 🟡 partial | Breaking-change protocol documented. `propagate-playbook-bump.yml` opens PRs across consumers (wired). The `MigrationPRBot` that auto-applies v1→v2 migration is Phase 5. |
| [runbook-bmad-openspec.md](runbook-bmad-openspec.md) | 🟡 partial | `openspec` CLI is wired; verdict + severity rubric is wired (linter); HITL gates are documented but humans drive them. The full BMAD Discovery → OpenSpec Implementation flow is documented + skills are present, no end-to-end test of the loop yet. |
| [skills-registry.md](skills-registry.md) | ✅ wired | `consumer-d-skills` service runs in production at port 9020; `scripts/skills_registry.py` client validates the response envelope; `mcp-servers-base.yaml` declares the server. |
| [slos.md](slos.md) | 📋 spec-only | 8 SLOs documented + monthly review cadence. No automated SLO measurement today; manual sweep at retro time. |
| [taxonomy.md](taxonomy.md) | 🟡 partial | Canonical glossary used in spec writing. `drift_check.py` flags new terms appearing in consumer dispatchers without entry here. |
| [upstream-sync.md](upstream-sync.md) | 🟡 partial | `scripts/upstream_sync.py` + `langgraph-aiops/workflows/upstream_refresher.py` wired for fork rebase. The propose-only HITL is enforced by code (no auto-merge). PATCHES.md inventory enforced per fork. |
| [verdict-contract.md](verdict-contract.md) | ✅ wired | `verdict_lint.py --shape artifact` enforces the ✅/⚠️/❓ + S1–S4 rubric on QA artefacts. Pre-commit + CI run it. |

---

## How to flip a row from spec-only to wired

1. Identify the gate: what action by whom must trigger which check?
2. Add a script under `scripts/` (or extend an existing one) implementing the check.
3. Add tests under `tests/` covering happy + failure paths.
4. Wire it in: pre-commit hook (`.pre-commit-config.yaml`), CI workflow (`.github/workflows/`), or harness invocation.
5. Update this file's row from 📋 → ✅ in the same PR.
6. Bump CHANGELOG with the new enforcement.

If a check is intrinsically human-only (judgement calls, code review tone), keep it 📋 spec-only and document the convention in the spec itself.

## See also

- [contributing.md](../docs/contributing.md) — RFC process for spec changes.
- [rollout-strategy.md](rollout-strategy.md) — breaking-change protocol when flipping a row's status changes the contract shape.
