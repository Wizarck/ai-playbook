# runbook-bmad-openspec.md

> **Status**: v1.1.0. Section 3.6 added in v0.8.0-rc1 — explicit branch + PR + merge contract pointing at [release-management.md](release-management.md).

The canonical flow for any consumer project that adopts the playbook: BMAD for Discovery, OpenSpec for Implementation, worker→QA pairing per artefact, max-2-rework, with human-in-the-loop (HITL) gates at each phase transition.

Project-specific deviations live in `<consumer>/docs/runbook.md`. This file is the source of truth; consumer runbooks **extend**, never duplicate, the universal flow below.

---

## 1 Phase map

```
Discovery (BMAD)                    Implementation (OpenSpec)
────────────────                    ─────────────────────────
PRD → Personas → ADRs → ERD     ──┐ propose → specs || design → tasks → apply → archive
       │              │           │      │
       ▼ Gate A       │           │      ▼ per-artefact: worker → QA → verdict
       │              ├── Gate B ─┤      max 2 rework cycles; iter 3 ⇒ blocked-by-spec
       └─► UX Track ──┘           │
           (parallel)              │
                              Gate C
```

BMAD produces **what** and **why**. OpenSpec produces **how**. The boundary is non-negotiable: an agent that writes tasks.md without an approved proposal + specs/design is `goal_drift`.

The **UX Track** runs in parallel with `bmad-create-architecture` between Gate A and Gate B; see [ux-track.md](ux-track.md) for the full spec. Headless/API-only consumers skip it via a one-line `docs/ux/README.md` declaration.

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
- **Gate B** — after ADRs + data-model **and UX Track** (per §2.3): "Are these the right irreversible bets? Is the UX coherent across journeys?" Verify: (a) DESIGN.md tokens consistent with ADR data shapes, (b) every PRD journey has a mock or design-intent doc, (c) components catalogue matches journey usage, (d) no engine references leaked into canonical artefacts after Phase A scrub. If no → rework the failing track; do not start slicing.
- **Gate C** — after slicing (§2.4): "Do the proposed OpenSpec changes match the PRD boundary?" If no → re-slice; do not create change folders.

An agent that advances past a gate without recorded human approval is `goal_drift` per `agentic-failures.md`.

### 2.3 UX Track (parallel with Architecture)

For consumers that ship a UI, the UX Track runs in parallel with `bmad-create-architecture` after Gate A. **Gate B waits on both Architecture and UX.**

The track follows a mandatory **three-step order** (visual artefact at every step; never substitute by text descriptions):

1. **Inspiration** — references in / themes out (`docs/ux/inspiration.md`).
2. **Palette validation** — 3-5 palettes as visual swatches + mini-previews (`docs/ux/variants/palette-options.html`); user picks.
3. **Variant generation** — one agent per creative engine in parallel on the locked palette (`docs/ux/variants/mock-*.html` + `index.html` comparison page).

After the user picks, **Phase A scrub** (archive rejected, strip engine references from the canonical) and **Phase B consolidation** (write `docs/ux/DESIGN.md` 9-section, then per-journey `jN.md` docs + companion mocks where warranted, then `components.md` Storybook-style with stewardship clause). Iteration uses a bones+layer remix pattern (`mock-X<N>-<descriptor>.html`).

Colour discipline is **OKLCH-canonical** — every token declared in `oklch(L% C H)`, hex as derivation comment only. WCAG-AA verified on every text pair and recorded in the head-comment audit.

See [ux-track.md](ux-track.md) for the full spec (artefacts, agent prompt template, component curation pattern, anti-patterns checklist, QA discipline). Copyable templates live in [`templates/ux/`](../templates/ux/).

Headless / API-only consumers declare `no-ui-consumer` in a one-line `docs/ux/README.md` and Gate B passes on Architecture alone.

### 2.4 Slicing (human-led, agent-assisted)

Break the PRD into OpenSpec-shaped changes. One change = one bounded context or one feature in a bounded context. Heuristics:

- If the change touches >1 bounded context in a modular monolith → split.
- If the change has >10 acceptance scenarios → split.
- If the change's write_paths exceed ~2 directories → split.
- If you cannot name the change in ≤6 words → split.

**Output: a single canonical artefact** at `docs/openspec-slice.md` (per [bmad-openspec-bridge.md](bmad-openspec-bridge.md)). The file is the contract between Phase 2 (BMAD slicing) and Phase 3 (OpenSpec implementation). It contains a table of change IDs with bounded context, FR coverage, journey usage (if UI), components touched (if UI), and dependencies — plus a one-paragraph scope note per change.

Humans approve the artefact at Gate C before any `/opsx:propose` runs. A change-ID not present in `docs/openspec-slice.md` cannot enter Phase 3 without re-slicing (or `--no-slice` for ad-hoc changes that bypass the contract).

**Path canon** (per the bridge spec):
- `docs/` = canonical durable artefacts (PRD, ADRs, data model, UX docs, slicing).
- `_bmad-output/planning-artifacts/` = workflow trail / step-by-step audit. Not gate-relevant; consumer-gitignore-able.

## 3 OpenSpec Implementation (Phase 3)

### 3.1 Per-change artefact sequence

Strict order. Each artefact runs through worker → QA → verdict before the next starts.

`/opsx:propose <change-id>` reads the slicing artefact at `docs/openspec-slice.md` (per [bmad-openspec-bridge.md](bmad-openspec-bridge.md)) to scaffold the change folder pre-populated with FR coverage, dependencies, and (for UI changes) component contracts from `docs/ux/components.md`. A change-id not in the slicing file is rejected unless `--no-slice` is passed.

For modules with many changes, batch mode is supported: `/opsx:propose --batch` iterates every row in dependency order. Idempotent — already-scaffolded folders are skipped.

1. `proposal.md` — problem statement + approach. QA: Blind Hunter + Acceptance Auditor (no Edge Case at proposal stage).
2. `specs/*.md` (|| concurrent with `design.md`) — `## Scenario: WHEN/THEN` acceptance criteria. QA: Edge Case Hunter + Acceptance Auditor.
3. `design.md` (|| concurrent with `specs/`) — architecture notes, alternatives considered, invariants. QA: Blind Hunter.
4. `tasks.md` — TDD-ordered implementation steps. QA: Acceptance Auditor (does every AC map to a task?).
5. `openspec apply` — implementation + tests. Workers emit `✅ APPROVED` only with verification output in the same message (per [verification-before-completion.md](verification-before-completion.md)). Deliverables comply with the no-skeleton rule (per [output-completeness.md](output-completeness.md)).
6. `openspec archive` — promotes `specs/*.md` to `openspec/specs/` (hand-edits blocked by `scripts/block_manual_spec_edit.py`). Chain a retro write to `retros/<change-id>.md` automatically (Gate F deliverable).

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

### 3.6 Branch, PR + merge contract

The source-control side of OpenSpec implementation is normatively defined in [release-management.md](release-management.md). The contract in one paragraph:

**1 branch = 1 OpenSpec change = 1 PR.** Each change owns one feature branch named `slice/<change-id>` (the kebab-case folder name under `openspec/changes/`); each branch targets `main` via exactly one pull request. Tasks within `tasks.md` are tracked as a markdown checklist in the PR description (NOT split into separate branches). The PR moves to project Status `Review` only when CI is green; Gate F approval gates the squash-merge. The dependency graph in `docs/openspec-slice.md` (per [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3.1) governs the merge order — Wave N changes squash-merge before Wave N+1 begins.

Project board schema (Status options + custom fields) is canonical per [release-management.md](release-management.md) §5; consumer projects bootstrap their board with `python .ai-playbook/scripts/bootstrap_gh_project.py` before `/opsx:propose` runs (see §7 of that spec).

### 3.7 On-disk layout for concurrent slices

When a module ships in waves of 5–10 concurrent OpenSpec changes (the consumer-c-legacy Module 2 cohort, for example), single-working-tree workflow saturates: one local checkout cannot service multiple in-flight slices without context-switching cost (stash thrash, dependency reinstalls per branch swap, build-cache contamination).

The canonical layout for that case is **bare repo + per-branch worktrees** per [git-worktree-bare-layout.md](git-worktree-bare-layout.md). Each OpenSpec change-id becomes a peer subdirectory of the project root, sharing one `.bare/` git database:

```
<project-root>/
├── .bare/                       # single shared git database
├── .git                         # pointer file
├── master/                      # default-branch worktree
└── <change-id>/                 # one worktree per slice in flight
```

Use [scripts/wt_add.py](../scripts/wt_add.py) for the daily flow:

```bash
cd <project-root>/.bare
python /c/Projects/ai-playbook/scripts/wt_add.py <change-id>
# creates <project-root>/<change-id>/ on branch slice/<change-id>
```

The worktree directory name **equals** the OpenSpec change-id (the same folder name under `openspec/changes/<id>/`); this satisfies traceability principle 7 from the global CLAUDE.md by making cwd self-documenting. `wt_add.py` enforces the match unless `--no-slice-check` is passed (analogous to `/opsx:propose --no-slice`).

Greenfield consumer projects adopt this layout from day one via [runbooks/git-worktree-bare-setup.md](../runbooks/git-worktree-bare-setup.md) §1. Existing consumers on the legacy single-tree layout keep working — migration is opt-in per §3 of that runbook.

### 3.8 Intra-slice parallelism (orthogonal to wave-level)

When a single slice covers multiple disjoint bounded contexts (e.g. M1 implementation slices that scaffold IAM + Ingredients + Suppliers + UoM in one OpenSpec change), the main agent MAY spawn subagents in parallel — one per bounded context — provided every group declares write-path ownership in `tasks.md` and shared files are reserved for serial recombination by the main agent. The full contract is in [release-management.md](release-management.md) §6.6.

This is **orthogonal** to the wave-level parallelism of §6.4 (which is about multiple slices in flight at the same wave, each on its own branch + worktree). Intra-slice parallelism happens **inside** one slice's branch, with subagents using ephemeral side-branches that the main agent recombines via cherry-pick before the slice's first push.

## 4 Retro cadence

Post-archive retro is mandatory; weekly and monthly retros cover accumulation.

| Trigger | Scope | Output |
|---|---|---|
| `openspec archive` | That change. | `retros/<change-id>.md` with lessons. |
| Weekly | All archives + `FEEDBACK.md` gripes + break-glass usages. | `retros/weekly-<YYYY-WW>.md`. |
| Monthly | Lifecycle check — stale changes, outdated memories, drift findings. | `retros/monthly-<YYYY-MM>.md`. |

Full cadence in [`specs/retrospective-cadence.md`](retrospective-cadence.md).

## 5 HITL summary

| Gate | Who | What they approve | Agent blocked without approval |
|---|---|---|---|
| A — Post-PRD | Human (role: PM) | Problem + outcome + KPIs. | Cannot start ADRs. |
| B — Post-ADRs + Post-UX | Human (role: Architect or PM) | Tech bets + data model + UX coherence (mocks per journey + DESIGN.md). Headless consumers skip UX gate via `docs/ux/README.md` no-ui declaration. | Cannot slice. |
| C — Post-slice | Human (role: PM) | Change list + scope notes. | Cannot `/opsx:propose`. |
| D — Per artefact | QA subagent (auto) + human override | Verdict `✅`. | Next artefact cannot start. |
| E — Pre-apply | Human (role: Eng lead) | Tasks approved + readiness check `✅`. | Cannot `openspec apply`. |
| F — Pre-archive | Human + QA | Implementation diff + CI green on slice branch + retro notes drafted. Squash-merge to main happens after this gate. | Cannot `openspec archive`. |

Humans may delegate D/E/F to a designated reviewer, but the gate must be **recorded** in the retro. An archived change whose gates have no recorded approver is an audit-fail in the monthly lifecycle check.

## 6 Cross-references

- [verdict-contract.md](verdict-contract.md) — ✅/⚠️/❓ literals and S1–S4 rubric.
- [parallel-review.md](parallel-review.md) — QA subagent discipline.
- [agent-contract.md](agent-contract.md) — spawn envelope every worker/QA uses.
- [agentic-failures.md](agentic-failures.md) — `goal_drift`, `over_confidence`, `premature_completion` all target the gates above.
- [error-message-standard.md](error-message-standard.md) — how block-state errors are phrased.
- [break-glass.md](break-glass.md) — overrides are permitted on some gates (A/B/C) with `--force-with-reason`; **D verdicts are never overridable**.
- [release-management.md](release-management.md) — branch model, PR shape, CI gates, project board schema, dependency-driven merge order.
- [issue-tracking.md](issue-tracking.md) — ticket↔proposal automation per surface (Jira / GH).
