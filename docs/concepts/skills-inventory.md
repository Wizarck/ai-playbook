---
schema: concept/v1
slug: skills-inventory
title: Skills Inventory
summary: |
  Curated map of the 61 bmad-* and openspec-* skills shipped with the playbook,
  classified by their role in the canonical BMAD+OpenSpec hybrid flow. ACTIVE
  skills are invoked during the documented phases (see runbook-bmad-openspec).
  DORMANT skills ship in the repo as optional surface but are not part of the
  canonical flow — they remain available for ad-hoc invocation or future use.
last_validated: "2026-09-04"
---

# Skills Inventory

## Why

The playbook imports skills from two upstreams (BMAD module + OpenSpec methodology) and adds a small number of native skills (`dev-flow`, `ai-playbook-check`). Total in scope: **61 skills** (56 `bmad-*` + 5 `openspec-*`), distributed to every consumer repo via `scripts/materialise_skills.py`.

Not every imported skill participates in the canonical hybrid flow defined in [runbook-bmad-openspec.md](runbook-bmad-openspec.md). Some are coaches or tooling that may be useful occasionally but are not invoked by any documented phase.

Skills do not consume context until invoked — only frontmatter (`name` + `description`) is exposed to the model for discovery. The cost of dormant skills is therefore discovery noise, not memory or context budget. A skill is kept when the recovery cost of deleting it and later needing it is higher than that noise; it is cut when it contradicts the hybrid flow rather than merely sitting outside it.

This document is the authoritative map. When a contributor wonders "is `bmad-correct-course` part of the flow?", the answer is here.

## What

Two status values:

- **ACTIVE** — referenced by [AGENTS.md](../../AGENTS.md), [runbook-bmad-openspec.md](runbook-bmad-openspec.md), [development-flow.md](development-flow.md), [parallel-review.md](parallel-review.md), [bmad-openspec-bridge.md](bmad-openspec-bridge.md), or another concept doc in this directory as part of a documented workflow.
- **DORMANT** — shipped in `skills/` and materialised to consumer repos, but not invoked by any canonical phase. Available for ad-hoc use; not part of any required gate.

### ACTIVE — Discovery (BMAD, Phase 1–2)

#### Core artefact production

| Skill | Purpose | Trigger phrase |
|---|---|---|
| [bmad-create-prd](../../skills/bmad-create-prd/SKILL.md) | Create PRD from scratch | "create PRD" |
| [bmad-create-architecture](../../skills/bmad-create-architecture/SKILL.md) | Architecture solution design + ADRs | "create architecture" |
| [bmad-create-ux-design](../../skills/bmad-create-ux-design/SKILL.md) | UX patterns + design specifications | "create UX design" |
| [bmad-document-project](../../skills/bmad-document-project/SKILL.md) | Document brownfield projects for AI context | "document this project" |

#### Personas (hubs that route to sub-skills)

| Skill | Persona | Sub-skills |
|---|---|---|
| [bmad-agent-pm](../../skills/bmad-agent-pm/SKILL.md) | John (PM) | edit-prd, validate-prd, check-implementation-readiness |
| [bmad-agent-ux-designer](../../skills/bmad-agent-ux-designer/SKILL.md) | Sally (UX) | create-ux-design |
| [bmad-agent-analyst](../../skills/bmad-agent-analyst/SKILL.md) | Mary (Analyst) | brainstorming, domain-research, market-research, technical-research |

#### PRD lifecycle

| Skill | Purpose | Trigger phrase |
|---|---|---|
| [bmad-edit-prd](../../skills/bmad-edit-prd/SKILL.md) | Edit existing PRD | "edit this PRD" |
| [bmad-validate-prd](../../skills/bmad-validate-prd/SKILL.md) | Validate PRD against standards | "validate this PRD" |
| [bmad-check-implementation-readiness](../../skills/bmad-check-implementation-readiness/SKILL.md) | Validate PRD + UX + Architecture + Epics complete | "check implementation readiness" |

#### Research (invoked via `bmad-agent-analyst` or directly)

| Skill | Purpose |
|---|---|
| [bmad-brainstorming](../../skills/bmad-brainstorming/SKILL.md) | Facilitated brainstorming sessions with creative techniques |
| [bmad-domain-research](../../skills/bmad-domain-research/SKILL.md) | Domain and industry research |
| [bmad-market-research](../../skills/bmad-market-research/SKILL.md) | Market research on competition and customers |
| [bmad-technical-research](../../skills/bmad-technical-research/SKILL.md) | Research on technologies and architecture |

#### Discovery facilitation

| Skill | Purpose | Trigger phrase |
|---|---|---|
| [bmad-party-mode](../../skills/bmad-party-mode/SKILL.md) | Multi-agent group discussion (each persona as subagent) | "party mode" / "roundtable" |
| [bmad-prfaq](../../skills/bmad-prfaq/SKILL.md) | Amazon Working Backwards PRFAQ challenge | "create a PRFAQ" / "work backwards" |
| [bmad-product-brief](../../skills/bmad-product-brief/SKILL.md) | Guided product brief creation | "create product brief" |
| [bmad-advanced-elicitation](../../skills/bmad-advanced-elicitation/SKILL.md) | Push LLM to reconsider/refine output (socratic, first-principles, pre-mortem, red-team) | "deeper critique" |
| [bmad-checkpoint-preview](../../skills/bmad-checkpoint-preview/SKILL.md) | HITL-assisted change review | "checkpoint" / "walk me through this" |
| [bmad-help](../../skills/bmad-help/SKILL.md) | BMAD navigation — recommends next skill | "bmad help" / "what's next" |

#### Methodology

| Skill | Purpose |
|---|---|
| [bmad-cis-design-thinking](../../skills/bmad-cis-design-thinking/SKILL.md) | Empathy-driven design thinking process (alt to `bmad-agent-pm` for persona/JTBD; see [runbook §2.1](runbook-bmad-openspec.md)) |

#### CIS coaches (innovation + creativity workshops)

Available for early-Discovery ideation. Not invoked by canonical gates; opt-in by name.

| Skill | Persona / Workflow |
|---|---|
| [bmad-cis-agent-brainstorming-coach](../../skills/bmad-cis-agent-brainstorming-coach/SKILL.md) | Carson — elite ideation facilitator |
| [bmad-cis-agent-creative-problem-solver](../../skills/bmad-cis-agent-creative-problem-solver/SKILL.md) | Dr. Quinn — systematic problem solving |
| [bmad-cis-agent-design-thinking-coach](../../skills/bmad-cis-agent-design-thinking-coach/SKILL.md) | Maya — design thinking maestro |
| [bmad-cis-agent-innovation-strategist](../../skills/bmad-cis-agent-innovation-strategist/SKILL.md) | Victor — disruptive innovation oracle |
| [bmad-cis-agent-presentation-master](../../skills/bmad-cis-agent-presentation-master/SKILL.md) | Caravaggio — visual communication / decks |
| [bmad-cis-agent-storyteller](../../skills/bmad-cis-agent-storyteller/SKILL.md) | Sophia — narrative frameworks |
| [bmad-cis-innovation-strategy](../../skills/bmad-cis-innovation-strategy/SKILL.md) | Workflow: identify disruption opportunities + business model innovation |
| [bmad-cis-problem-solving](../../skills/bmad-cis-problem-solving/SKILL.md) | Workflow: structured problem-solving methodologies |
| [bmad-cis-storytelling](../../skills/bmad-cis-storytelling/SKILL.md) | Workflow: narrative construction via story frameworks |

#### Brownfield / knowledge mining

| Skill | Purpose |
|---|---|
| [bmad-extract-lessons-from-adrs](../../skills/bmad-extract-lessons-from-adrs/SKILL.md) | Mine ADRs, gotcha files, runbooks for cross-project lessons that warrant playbook canonical specs |

#### Teaching

| Skill | Purpose |
|---|---|
| [bmad-teach-me-testing](../../skills/bmad-teach-me-testing/SKILL.md) | Progressive teaching of testing practices |

### ACTIVE — Implementation (OpenSpec, Phase 3)

| Skill | Purpose | Triggered by |
|---|---|---|
| [openspec-propose](../../skills/openspec-propose/SKILL.md) | Scaffold a change with proposal + design + specs + tasks | `/opsx:propose <change-id>` |
| [openspec-apply-change](../../skills/openspec-apply-change/SKILL.md) | Sequential worker→QA implementation of a change | `/opsx:apply` |
| [openspec-apply-parallel](../../skills/openspec-apply-parallel/SKILL.md) | Parallel implementation across ≥2 disjoint task groups | `/opsx:apply --parallel` |
| [openspec-archive-change](../../skills/openspec-archive-change/SKILL.md) | Archive change post-merge + chain retro | `/opsx:archive` |
| [openspec-explore](../../skills/openspec-explore/SKILL.md) | Thinking-partner mode pre/during change | `/opsx:explore` |

### ACTIVE — Code Review (cross-phase)

3-layer parallel review pattern per [parallel-review.md](parallel-review.md).

| Skill | Layer |
|---|---|
| [bmad-code-review](../../skills/bmad-code-review/SKILL.md) | Orchestrator (Blind Hunter + Edge Case Hunter + Acceptance Auditor with triage) |
| [bmad-review-edge-case-hunter](../../skills/bmad-review-edge-case-hunter/SKILL.md) | Edge-case sub-layer (branching paths + boundary conditions) |
| [bmad-review-adversarial-general](../../skills/bmad-review-adversarial-general/SKILL.md) | Adversarial Cynical Review sub-layer |

### ACTIVE — Testing

| Skill | Purpose |
|---|---|
| [bmad-qa-generate-e2e-tests](../../skills/bmad-qa-generate-e2e-tests/SKILL.md) | Generate end-to-end automated tests for existing features |

### ACTIVE — Retro

| Skill | Purpose |
|---|---|
| [bmad-retrospective](../../skills/bmad-retrospective/SKILL.md) | Post-epic / post-archive retrospective (lessons + success assessment) |

### DORMANT — BMAD bucle (replaced by OpenSpec changes)

The original BMAD methodology runs a `PM → Architect → PO → SM → Dev → QA` loop with stories and sprints. The hybrid flow replaces "story → sprint" with "OpenSpec change → propose/apply/archive". The skills that produced or consumed the story and sprint artefacts were removed (see **Removed** below); what remains here sits outside the loop rather than inside it.

| Skill | Original role |
|---|---|
| [bmad-agent-dev](../../skills/bmad-agent-dev/SKILL.md) | Amelia — developer persona hub, rebased on the OpenSpec change |
| [bmad-agent-architect](../../skills/bmad-agent-architect/SKILL.md) | Winston — architect persona hub (its sub-skill `bmad-create-architecture` is active) |
| [bmad-correct-course](../../skills/bmad-correct-course/SKILL.md) | Manage significant changes during sprint execution |
| [bmad-create-epics-and-stories](../../skills/bmad-create-epics-and-stories/SKILL.md) | Break requirements into epics + user stories |

### DORMANT — Test Architect track (`tea` + `testarch-*`)

The Test Architect (Murat) persona with its 8 testarch workflows is a parallel testing methodology not wired into the hybrid flow. Real testing in the flow is covered by `bmad-qa-generate-e2e-tests` plus the hardrules under `scripts/rules/`. Kept available if a project decides to adopt the testarch methodology.

| Skill | Role |
|---|---|
| [bmad-tea](../../skills/bmad-tea/SKILL.md) | Master Test Architect (Murat) — hub |
| [bmad-testarch-atdd](../../skills/bmad-testarch-atdd/SKILL.md) | Acceptance Test-Driven Development scaffolds |
| [bmad-testarch-automate](../../skills/bmad-testarch-automate/SKILL.md) | Expand test automation coverage |
| [bmad-testarch-ci](../../skills/bmad-testarch-ci/SKILL.md) | Scaffold CI/CD test pipeline |
| [bmad-testarch-framework](../../skills/bmad-testarch-framework/SKILL.md) | Initialise Playwright/Cypress test framework |
| [bmad-testarch-nfr](../../skills/bmad-testarch-nfr/SKILL.md) | Assess non-functional requirements (perf/security/reliability) |
| [bmad-testarch-test-design](../../skills/bmad-testarch-test-design/SKILL.md) | Plan tests at epic/system level |
| [bmad-testarch-test-review](../../skills/bmad-testarch-test-review/SKILL.md) | Review test quality |
| [bmad-testarch-trace](../../skills/bmad-testarch-trace/SKILL.md) | Traceability matrix |

### DORMANT — Document utilities

Generic markdown utilities not wired into any canonical phase.

| Skill | Role |
|---|---|
| [bmad-distillator](../../skills/bmad-distillator/SKILL.md) | Lossless LLM-optimised compression of source documents |
| [bmad-shard-doc](../../skills/bmad-shard-doc/SKILL.md) | Split large markdown documents by L2 headings |
| [bmad-index-docs](../../skills/bmad-index-docs/SKILL.md) | Generate / update `index.md` referencing all docs in a folder |
| [bmad-editorial-review-prose](../../skills/bmad-editorial-review-prose/SKILL.md) | Clinical copy-editor for prose communication issues |
| [bmad-editorial-review-structure](../../skills/bmad-editorial-review-structure/SKILL.md) | Structural editor — proposes cuts and reorganisation |

### Removed

Eleven skills were deleted rather than left dormant, because each one either
contradicted a rule the fork adopted or produced an artefact the hybrid flow no
longer has. The reasoning and the byte counts are in
`openspec/changes/skills-cut-builder-story-loop/proposal.md`; the consumer
migration step a removal requires is step 0 of
[upgrade-playbook-pin.md](../runbooks/upgrade-playbook-pin.md).

| Skill | Replaced by |
|---|---|
| `bmad-agent-builder`, `bmad-workflow-builder`, `bmad-module-builder`, `bmad-bmb-setup` | Nothing — the fork does not build new BMad modules, and these carried the tree's only `uv run` dependency and its only installer |
| `bmad-create-story`, `bmad-dev-story` | `openspec-propose` → `openspec-apply-change` |
| `bmad-sprint-planning`, `bmad-sprint-status` | The change list under `openspec/changes/` |
| `bmad-quick-dev` | `dev-flow` + `openspec-apply-change` |
| `bmad-generate-project-context` | `AGENTS.md` + the `.ai-playbook/` submodule |
| `bmad-agent-tech-writer` | `bmad-agent-analyst`, which reaches the same `bmad-document-project` |

## How it relates to other concepts

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) is the authoritative flow that determines which skills are ACTIVE. When that runbook changes (a new gate adds a skill, a phase deprecates one), this inventory is updated in the same commit.
- [skills-registry.md](skills-registry.md) defines the HTTP discovery service. This inventory document is orthogonal — it covers the on-disk skill set shipped with the playbook submodule, not the live catalog service.
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) defines the Gate C seam between Discovery and Implementation; the ACTIVE skills on each side of the seam mirror that bridge.
- [parallel-review.md](parallel-review.md) names the three review subagents that `bmad-code-review` orchestrates.
- [development-flow.md](development-flow.md) describes how `dev-flow` wraps the OpenSpec implementation skills into a branch↔PR↔release cycle.

## Concrete example

A typical greenfield feature delivery in a consumer project touches **9 ACTIVE skills**:

1. `bmad-create-prd` → produces `docs/prd.md`. Gate A.
2. `bmad-create-architecture` → produces `docs/architecture-decisions.md` + `docs/data-model.md`.
3. `bmad-create-ux-design` (in parallel with #2 if the feature has UI) → produces `docs/ux/DESIGN.md`. Gate B.
4. Slicing (human-led, agent-assisted) → produces `docs/openspec-slice.md`. Gate C.
5. `openspec-propose <change-id>` → scaffolds `openspec/changes/<id>/`.
6. `openspec-apply-change` (or `openspec-apply-parallel` if multi-group) → implements.
7. `bmad-code-review` → 3-layer review on the diff. Spawns `bmad-review-edge-case-hunter` and `bmad-review-adversarial-general` internally.
8. `openspec-archive-change` → archives + chains retro.
9. `bmad-retrospective` → post-archive lessons capture.

A brownfield feature in an existing project adds `bmad-document-project` at the start. A feature whose PRD is in flux invokes `bmad-edit-prd` / `bmad-validate-prd` / `bmad-check-implementation-readiness` between Gate A and Gate B. A feature needing pre-PRD research invokes the `bmad-agent-analyst` hub (which routes to `bmad-domain-research` / `bmad-market-research` / `bmad-technical-research` / `bmad-brainstorming`).

DORMANT skills are never invoked by the canonical flow. A contributor who wants to use one (e.g. `bmad-distillator` to compress a vendor's docs before feeding them to the agent) invokes it ad-hoc and is responsible for the outcome — no gate references the output.

## Further reading

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §2.1 — artefact-to-skill mapping for the Discovery phase.
- [agent-contract.md](agent-contract.md) — every skill invocation is a Task-spawned subagent with the contract defined there.
- [agentic-failures.md](agentic-failures.md) §2.13 — `apply_phase_bypass` failure mode covers the `openspec-apply-change` skill marker.
