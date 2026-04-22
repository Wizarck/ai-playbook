# memory-hierarchy.md

> **Status**: v1.0.0. Supersedes T02-pre stub. Populated in T06.

Agents operate across four memory tiers with different read/write patterns, retention windows,
and failure modes. This spec defines the tiers, the `bank_id` convention for durable memory, the
read/write discipline, decay policy, retrieval thresholds, and the handoff to the spawn-time
envelope in [agent-contract.md](agent-contract.md).

---

## 1. Hierarchy

| Tier | Store | Typical entry | Scope | Read pattern | Write pattern |
|---|---|---|---|---|---|
| **Session** | In-process context window | Current files, partial outputs, conversation history | One session | Automatic by the LLM | Automatic — every tool call and reply |
| **Project** | `openspec/` + repo docs (`docs/`, `ADRs/`, `runbooks/`) | Active-change artefacts, decisions, PRDs | One project | On-task: read before deciding | Via OpenSpec CLI and PR only; never hand-edit `openspec/specs/*.md` |
| **Durable / personal** | Hindsight MCP, `bank_id=<project>` or `<project>-personal` | Prior decisions, gotchas, retros, lessons | Per-project, queryable by any agent authorised | `hindsight.recall` at bootstrap + on-demand | `hindsight.retain` after a meaningful lesson |
| **Durable / universal** | `ai-playbook/specs/` (this repo), consumed via git submodule | Norms, schemas, contracts (this file, for instance) | All projects | Automatic via submodule — read on demand | RFC + PR to this repo, semver-bumped |

## 2. `bank_id` conventions

One primary `bank_id` per project. Personal add-ons get a suffix when the content is
Arturo-private (per [dispatcher-chain.md](dispatcher-chain.md) level 3).

| Project | Primary bank | Personal add-on bank |
|---|---|---|
| `consumer-c-legacy` (public repo) | `consumer-c-legacy` | — (no personal layer; community repo) |
| `consumer-d` (personal infra) | `consumer-d` | `consumer-d-personal` (gotchas, ports, VPS-private knowledge) |
| `consumer-d-rag` | `consumer-d-rag` | `consumer-d-personal` (shared with consumer-d personal layer) |
| `consumer-b` | `consumer-b` | `consumer-b-personal` (tenant-private) |
| Cross-cutting personal knowledge (not tied to one project) | — | `hindsight-personal` |

Rules:

- `bank_id` is **lowercase kebab**, matches the project slug in `specs/projects-registry.md`.
- A child subagent inherits its parent's `memory.bank_id` unless it explicitly overrides in the
  spawn envelope.
- Writing to a `*-personal` bank from a non-personal session is forbidden — the harness checks
  the session's `personal` flag (see `consumer-d/AGENTS.md` frontmatter `personal: true`).

## 3. Retention windows

| Tier | Retention |
|---|---|
| Session | Infinite within the session; lost at session end. |
| Project | Until the OpenSpec change is archived. Archived changes stay in `openspec/changes/archive/` indefinitely. |
| Durable / personal | **90-day soft decay** by default; items tagged `type=lesson` are retained explicitly beyond decay. |
| Durable / universal | Immortal — this repo is versioned via git; deletions happen via RFC + PR + semver bump. |

"Soft decay" means an entry is deprioritised in retrieval after the window but not deleted. A
retro that surfaces a decayed-but-still-relevant entry can re-tag it as `type=lesson` to extend
its life.

## 4. Read rules

- **Bootstrap recall.** Every agent's bootstrap directive (see each consumer's `AGENTS.md` §0)
  includes step 2: `hindsight.recall(query="<project> <topic>")`. Default `top_k=5`.
- **On-demand during task.** If the agent encounters an unfamiliar term, a past-decision
  reference ("we already decided X"), or a gotcha-shaped hint, it MUST query Hindsight before
  proceeding — "read before decide".
- **Retrieval thresholds.**
  - Bootstrap: `top_k=5`, similarity ≥0.7.
  - Mid-task clarification: `top_k=3`, similarity ≥0.75.
  - Retro compilation: `top_k=20`, similarity ≥0.6 (broader sweep).
- **Never trust without verify.** A recalled lesson is a prior, not an authority. If the lesson
  contradicts observed state, decay policy (§6) kicks in.

## 5. Write rules

- **Retain on lesson, not on fact.** Facts live in the code and in `docs/`. `hindsight.retain`
  captures *why* a decision was made, what alternative was rejected, and what would invalidate
  the decision.
- **Every retain includes:**
  - `why` — the rationale, 1–2 sentences.
  - `trace_id` — the OTel trace that led to the lesson.
  - `tags` — at least `project`, `kind` (`lesson` | `gotcha` | `decision` | `failure`), and an
    optional `ttl_days` override.
- **Never retain a secret.** The same pattern-match that gates commits
  (`scripts/secrets_scan.py`) applies to the retain payload — the wrapper MUST sanitise before
  the MCP call.
- **Retain after significant events only.** Examples of qualifying events:
  - An ADR was chosen over a named alternative.
  - A gotcha was discovered (wrong port, wrong startup order, API quirk).
  - A failure mode in [agentic-failures.md](agentic-failures.md) fired and was resolved.
  - A retro extracted a pattern worth reusing next sprint.

## 6. Decay policy

A stored lesson that conflicts with observed current state is handled as follows:

1. **Observe the conflict.** Agent notices: recalled lesson says "Paperclip prod on port 3101",
   but current `docker-compose.yml` shows `3102`.
2. **Verify the current state.** Read authoritative source (the file, the running service).
3. **Resolve:**
   - If the lesson is simply stale → **delete** the entry or annotate it with
     `invalidated_on: <ISO date>` + new pointer.
   - If the lesson is still partially true (e.g. "used to be 3101; moved to 3102 on 2026-03-14")
     → **date-annotate** and add a successor entry.
4. **Retain the decay event itself** as a meta-lesson (`kind=failure`, subtype
   `memory_conflict`) so the retro cadence surfaces repeat offenders.

Never "argue with observed state from memory". Observed state wins; memory is updated.

## 7. Handoff to the spawn envelope

When a parent spawns a child, the `memory` block in the [agent-contract.md](agent-contract.md)
input envelope declares:

```json
"memory": {
  "bank_id": "consumer-c-legacy",
  "recall_depth": 5
}
```

- `recall_depth` is the `top_k` the child will use for its bootstrap recall.
- `recall_depth=0` disables recall — use for adversarial reviewers (Blind Hunter) where the
  point is to reason without prior bias.
- A child MAY extend its own recall mid-task, but its budget ceiling still applies.

## 8. Interaction with `scripts/inject_context.py`

`scripts/inject_context.py` (stub at v0.1.0, populated in T12) is the read-side pipeline that
composes a subagent's LEAN prompt from the four tiers: pulls the relevant slice of session
state, project artefacts, and a top-k recall from the right Hindsight bank. This spec defines
the **semantics** of what each tier contains; `inject_context.py` defines the **mechanics** of
assembling them into a brief. Consumers do not call Hindsight directly at spawn time — they go
through the injector.

## 9. Failure mode — `DEGRADED_CONTEXT`

If Hindsight is unreachable, the session enters `DEGRADED_CONTEXT` per
[degradation-modes.md](degradation-modes.md). Behaviour:

- Agent warns at session start: "Hindsight unreachable; retains queued locally at
  `.ai-playbook/hindsight-queue.jsonl`."
- Recall returns an empty result set; the agent proceeds without prior-decision context.
- Retains are written to the local queue and flushed on reconnection — the agent must not drop
  them silently. The queue file is gitignored.
- Any decision made in `DEGRADED_CONTEXT` MUST be tagged in its OTel span
  (`ai_playbook.memory.degraded=true`) so retros can re-audit after reconnection.

## 10. Worked example

**Scenario.** A reviewer subagent in consumer-c-legacy is spawned for a proposal review on
`module-1-ingredients-implementation`.

Spawn envelope's memory block:

```json
"memory": { "bank_id": "consumer-c-legacy", "recall_depth": 5 }
```

1. Child invokes `hindsight.recall(query="consumer-c-legacy ingredients categories", top_k=5)`.
2. Three lessons return (score ≥0.7):
   - "Categories use RESTRICT on delete; this bit us once in seed reload." (`kind=gotcha`)
   - "ADR-009 chose soft-delete with `isActive`; physical delete was rejected for audit." (`kind=decision`)
   - "Do NOT import `Category` entity directly from `Ingredient` module; use the port." (`kind=lesson`)
3. Reviewer cites lesson 3 when catching a diff that imports the entity directly — S2 finding.
4. After the review concludes, reviewer calls `hindsight.retain` with
   `why="import-via-port rule recurred; add to readiness checklist"`, `tags=["consumer-c-legacy", "lesson"]`,
   and the OTel `trace_id`.
5. Next sprint, the bootstrap recall surfaces the new lesson at the top of the retrieval for any
   reviewer touching cross-module imports.

## 11. See also

- [agent-contract.md](agent-contract.md) — `memory` field in the spawn envelope.
- [parallel-review.md](parallel-review.md) — each layer uses recall independently.
- [dispatcher-chain.md](dispatcher-chain.md) — `personal: true` flag gates personal banks.
- [degradation-modes.md](degradation-modes.md) — `DEGRADED_CONTEXT` when Hindsight is down.
- [agentic-failures.md](agentic-failures.md) — `context_collapse` and `hallucination` are the
  two failures memory-hierarchy is designed to mitigate.
