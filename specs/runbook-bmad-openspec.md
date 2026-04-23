# runbook-bmad-openspec.md

> **Status**: v1.0.0. Populated in T11.

The canonical flow for any consumer project that adopts the playbook: BMAD for Discovery, OpenSpec for Implementation, worker→QA pairing per artefact, max-2-rework, with human-in-the-loop (HITL) gates at each phase transition.

Project-specific deviations live in `<consumer>/docs/runbook.md`. This file is the source of truth; consumer runbooks **extend**, never duplicate, the universal flow below.

---

## 1 Phase map

```
Discovery (BMAD)             Implementation (OpenSpec)
────────────────             ─────────────────────────
PRD → Personas → ADRs → ERD  propose → specs || design → tasks → apply → archive
       │                      │
       ▼ HITL gate            ▼ per-artefact: worker → QA → verdict
  Human approves         max 2 rework cycles; iter 3 ⇒ SYSTEMIC ⇒ blocked-by-spec
```

BMAD produces **what** and **why**. OpenSpec produces **how**. The boundary is non-negotiable: an agent that writes tasks.md without an approved proposal + specs/design is `goal_drift`.

## 2 BMAD Discovery (Phase 1–2)

### 2.1 Artefacts produced

| Artefact | Skill | Purpose |
|---|---|---|
| `docs/prd.md` | `bmad-create-prd` | Problem, personas, outcome, KPIs, FRs. |
| `docs/architecture-decisions.md` | `bmad-create-architecture` | ADRs — irreversible tech bets. |
| `docs/data-model.md` | `bmad-create-architecture` (data track) | ERD + cascade rules. |
| `docs/personas-jtbd.md` | `bmad-agent-pm` / `bmad-cis-design-thinking` | Roles + JTBD + RBAC matrix. |
| `docs/project-structure.md` | `bmad-document-project` | Directory map. |

### 2.2 HITL gates

Human MUST approve before the next phase starts:

- **Gate A** — after PRD: "Is the problem correctly framed? Are the KPIs the right ones?" If no → rework PRD; do not start ADRs.
- **Gate B** — after ADRs + data-model: "Are these the right irreversible bets?" If no → rework ADRs; do not start slicing.
- **Gate C** — after slicing (§3): "Do the proposed OpenSpec changes match the PRD boundary?" If no → re-slice; do not create change folders.

An agent that advances past a gate without recorded human approval is `goal_drift` per `agentic-failures.md`.

### 2.3 Slicing (human-led, agent-assisted)

Break the PRD into OpenSpec-shaped changes. One change = one bounded context or one feature in a bounded context. Heuristics:

- If the change touches >1 bounded context in a modular monolith → split.
- If the change has >10 acceptance scenarios → split.
- If the change's write_paths exceed ~2 directories → split.
- If you cannot name the change in ≤6 words → split.

The output of slicing is a list of proposed change IDs, each with a 1-paragraph scope note. Humans approve the list before any `/opsx:propose` runs.

## 3 OpenSpec Implementation (Phase 3)

### 3.1 Per-change artefact sequence

Strict order. Each artefact runs through worker → QA → verdict before the next starts.

1. `proposal.md` — problem statement + approach. QA: Blind Hunter + Acceptance Auditor (no Edge Case at proposal stage).
2. `specs/*.md` (|| concurrent with `design.md`) — `## Scenario: WHEN/THEN` acceptance criteria. QA: Edge Case Hunter + Acceptance Auditor.
3. `design.md` (|| concurrent with `specs/`) — architecture notes, alternatives considered, invariants. QA: Blind Hunter.
4. `tasks.md` — TDD-ordered implementation steps. QA: Acceptance Auditor (does every AC map to a task?).
5. `openspec apply` — implementation + tests.
6. `openspec archive` — promotes `specs/*.md` to `openspec/specs/` (hand-edits blocked by `scripts/block_manual_spec_edit.py`).

Commands in [capability map](../AGENTS.md) reference `/opsx:propose`, `/opsx:apply`, `/opsx:archive`, `/opsx:explore`.

### 3.2 Worker → QA pairing

Each artefact has a worker subagent and a QA subagent. They share no context beyond what `agent-contract.md` §2 defines. The QA subagent uses parallel review per `parallel-review.md` when the artefact warrants (≥2 layers per §2 of that spec).

QA verdicts per `verdict-contract.md`:
- `✅ APPROVED` → worker hands off to next artefact.
- `⚠️ ISSUES FOUND (iter N)` → worker fixes, re-submits.
- `❓ CLARIFICATION NEEDED` → OpenSpec change moves to state `blocked-by-spec`; human must disambiguate.

### 3.3 Max 2 rework cycles

After iter 2, if QA still finds the same S1/S2 finding, the rule in `verdict-contract.md` §3 fires: flip to `❓ CLARIFICATION NEEDED` with `detail: "same finding recurred twice; spec or rule is ambiguous"`. **Never** attempt iter 3 on the same finding.

### 3.4 Self-validation gates (silent, before invoking QA)

The worker runs these 5 gates on its own output first:

1. **Scope** — does the artefact do only what the proposal approved?
2. **Anti-duplication** — does a sibling artefact (other `specs/*.md`, archived `openspec/specs/`, `docs/`) already cover this concern?
3. **Traceability** — every decision cites its source (`ADR-N`, PRD section, Jira key, ticket URL) — NOT a summary.
4. **TDD compliance** — every `Scenario: WHEN/THEN` has ≥1 test path in `tasks.md`. Layer discipline per project hard rules (see `AGENTS.md` §4 of consumer).
5. **Naming** — canonical terms per `taxonomy.md`; no new terms without RFC.

A worker that skips these gates is in `over_confidence` territory and will typically fail QA iter 1.

### 3.5 Lifecycle states (authoritative)

```
proposal-drafted ──► proposal-approved
                         │
                         ▼
                    specs-drafted ∥ design-drafted
                         │             │
                         └──►   approved   ◄──┘
                                   │
                                   ▼
                              tasks-drafted ──► approved ──► applying ──► applied ──► archived
                                   ▲
                                   └── blocked-by-spec (from `❓` verdict; human unblocks)
```

## 4 Retro cadence

Post-archive retro is mandatory; weekly and monthly retros cover accumulation.

| Trigger | Scope | Output |
|---|---|---|
| `openspec archive` | That change. | `retros/<change-id>.md` with lessons. |
| Weekly | All archives + `FEEDBACK.md` gripes + break-glass usages. | `retros/weekly-<YYYY-WW>.md`. |
| Monthly | Lifecycle check — stale changes, outdated memories, drift findings. | `retros/monthly-<YYYY-MM>.md`. |

Full cadence in `specs/retrospective-cadence.md` (stub at v0.1.0; filled in T14i).

## 5 HITL summary

| Gate | Who | What they approve | Agent blocked without approval |
|---|---|---|---|
| A — Post-PRD | Human (role: PM) | Problem + outcome + KPIs. | Cannot start ADRs. |
| B — Post-ADRs | Human (role: Architect or PM) | Tech bets + data model. | Cannot slice. |
| C — Post-slice | Human (role: PM) | Change list + scope notes. | Cannot `/opsx:propose`. |
| D — Per artefact | QA subagent (auto) + human override | Verdict `✅`. | Next artefact cannot start. |
| E — Pre-apply | Human (role: Eng lead) | Tasks approved + readiness check `✅`. | Cannot `openspec apply`. |
| F — Pre-archive | Human + QA | Implementation diff + tests pass + retro notes drafted. | Cannot `openspec archive`. |

Humans may delegate D/E/F to a designated reviewer, but the gate must be **recorded** in the retro. An archived change whose gates have no recorded approver is an audit-fail in the monthly lifecycle check.

## 6 Cross-references

- [verdict-contract.md](verdict-contract.md) — ✅/⚠️/❓ literals and S1–S4 rubric.
- [parallel-review.md](parallel-review.md) — QA subagent discipline.
- [agent-contract.md](agent-contract.md) — spawn envelope every worker/QA uses.
- [agentic-failures.md](agentic-failures.md) — `goal_drift`, `over_confidence`, `premature_completion` all target the gates above.
- [error-message-standard.md](error-message-standard.md) — how block-state errors are phrased.
- [break-glass.md](break-glass.md) — overrides are permitted on some gates (A/B/C) with `--force-with-reason`; **D verdicts are never overridable**.
