# ux-track.md

> **Status**: v1.0.0. Formalises a UX design phase that runs in parallel with `bmad-create-architecture`, between Gate A and Gate C of the BMAD+OpenSpec workflow ([runbook-bmad-openspec.md](runbook-bmad-openspec.md)).

## 1 Purpose

The canonical workflow ([runbook-bmad-openspec.md](runbook-bmad-openspec.md)) used to be silent on UX. PRDs declared capabilities; OpenSpec changes implemented them; mocks and component decisions happened ad-hoc inside individual `design.md` files per change. That fragmentation produced two recurring failures:

1. **No coherent UX vision across changes.** Each change had its own micro-design; the product looked like a quilt of disconnected screens.
2. **Component sprawl during `/opsx:apply`.** Every change reinvented its own button / picker / badge — no library, no shared discipline, no design review.

The UX Track is the named place where mocks-per-journey are produced and the component library is curated. It is **mandatory** for any consumer that ships a UI; it is **trivially skippable** for headless / API-only consumers (see §6).

## 2 Position in the workflow

```
PRD → Personas → ADRs       ──┐
       │                      │
       ▼ Gate A               ├──► Slicing → Gate C → /opsx:propose → ...
       │                      │
       ├──► UX Track ─────────┤   (parallel with Architecture)
       │   (mocks per journey)│
       │                      │
       └──► bmad-create-architecture ──┘
                              ▲
                              │
                          Gate B
                  (Architecture + UX both done)
```

Two parallel tracks open at Gate A and converge at Gate B:

- **Architecture track** — `bmad-create-architecture` produces ADRs + data-model extension.
- **UX track** — `bmad-create-ux-design` (or equivalent skill) produces mocks-per-journey + a project-level DESIGN.md + component candidates.

**Gate B now waits on both.** Until UX is done, slicing cannot start (Architecture alone is not enough — the slice boundaries depend on which screens exist).

For headless / API-only consumers, the UX track produces a one-line "no UI in this consumer" notice in `docs/ux/README.md` and Gate B passes on Architecture alone.

## 3 Artefacts produced

| Artefact | Path | Purpose |
|---|---|---|
| `docs/ux/DESIGN.md` | project-level | Design system: principles, colors, typography, components, spacing, depth, guidelines, responsive patterns, agent prompts (9-section format inspired by [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)). One per consumer. |
| `docs/ux/{journey-id}.md` | per user journey | Mock + interaction notes for a specific JTBD/journey identified in the PRD. One file per journey; cross-referenced from the PRD's Journey Requirements Summary. |
| `docs/ux/components.md` | project-level | Component candidate list: name, source PRD references, complexity tier (trivial / non-trivial), expected base (shadcn/ui / custom). Becomes the input for the curation pattern in §5. |

Each per-journey file MUST cross-reference the PRD journey + the FRs it satisfies. A journey doc with no FR back-references is `goal_drift` per [agentic-failures.md](agentic-failures.md).

## 4 Output format guidance

The recommended `DESIGN.md` format is the 9-section structure from [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md):

1. **Principles** — design philosophy, brand voice
2. **Colors** — palette + semantic roles
3. **Typography** — font stack + scale
4. **Components** — primitives (buttons, fields, badges) + composites (recipe-picker, allergen-badge)
5. **Spacing** — grid + rhythm
6. **Depth** — elevation, shadow, layering
7. **Guidelines** — do/don't patterns, motion language
8. **Responsive patterns** — breakpoints + adaptation rules
9. **Agent prompts** — how an LLM should describe a screen using this DESIGN.md

This format is normative for new consumers. Existing consumers may keep their own layout if it covers the same surface area; deviations require an entry in the consumer's `AGENTS.md` §7 (per [contributing.md](../docs/contributing.md) §6 backwards compatibility).

## 5 Component library curation pattern

The pattern fires during `/opsx:apply` (Phase 3 of [runbook-bmad-openspec.md](runbook-bmad-openspec.md)) — every time a change touches the UI.

### 5.1 Storybook-first development

Components are developed in **Storybook with stories** before they appear on a screen. Stories cover:

- Default state
- Loading state
- Error state
- Empty state
- Edge state (long text, large numbers, missing data)

A component without ≥3 of the above states is non-trivial and triggers design review (§5.2).

### 5.2 Design review trigger

A component is **non-trivial** if any of:

- It composes ≥2 primitives (e.g. `MacroPanel` composes table + badge + tooltip)
- It renders externally-sourced data (e.g. OFF macros, AI-suggested yields)
- It carries regulatory weight (e.g. allergen badges, EU 1169/2011 label preview)
- It is invoked by an agent flow (e.g. `AgentChatWidget`)

Non-trivial components require a **design review** before promotion: ≥1 alternative explored, decision documented in `docs/ux/components.md` with reviewer name + date.

Trivial components (single-primitive, decorative, no external data) skip review and promote directly.

### 5.3 Promotion to `packages/ui-kit/`

Components live in Storybook (in-PR) until reviewed. After approval they promote to the consumer's `packages/ui-kit/` (or equivalent shared package). Base layer is **shadcn/ui + Tailwind CSS** by convention; consumers may swap if their stack differs (Vue, Svelte, Web Components) but must document the swap in their `AGENTS.md`.

Storybook is **published in CI** for static review on every PR. Reviewers click through Storybook stories before approving the change.

## 6 Curated external skills

The playbook does **not** vendor external skills (per [skills-distribution.md](skills-distribution.md) and RFC-0001: skills distribute via separate semver-pinned source repos). The table below recommends third-party skills that augment the UX track. Consumers opt in; the playbook neither requires nor bundles them.

| Skill | Stars | License | Recommendation | Use as |
|---|---|---|---|---|
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 22,098 | Apache-2.0 | **Drop-in** | UX track + Storybook iteration. 23 slash commands + 7 reference guides. Apache-2.0 is AGPL-compatible. |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | 13,207 | unspecified | **Drop-in (with caveat)** | Image-to-code variants for mocks; design rigor for component generation. License unspecified — see §6.1. |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 70,916 | MIT | **Adapt** | Strong design-system generator (161 rules, 67 styles, 161 palettes). Needs a wrapper to ingest a PRD and emit per-journey mocks aligned with §3. |
| [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) | 66,088 | MIT | **Inspire-from** | Source of the 9-section DESIGN.md format pattern adopted in §4. The repo's 69+ DESIGN.md examples are useful as templates; we do not vendor them. |
| [modstart-lib/skillui](https://github.com/modstart-lib/skillui) | 7 | Apache-2.0 | **Skip** | Skill distribution platform — orthogonal to UX. Listed for completeness; not relevant to the UX track. |

Star counts and license fields verified via `gh api repos/{owner}/{repo}` on 2026-04-27.

### 6.1 License compliance

The playbook is **AGPL-3.0**. License compatibility for each curated skill:

- **MIT, Apache-2.0**: one-way compatible — these skills can be referenced and integrated by AGPL projects without dual-licensing concerns. Consumers MUST preserve original copyright notices when copying skill files into their tree.
- **No-license** (taste-skill at the time of publication): default copyright law applies — *all rights reserved*. Direct integration requires the maintainer's explicit permission. The playbook documents the recommendation but does NOT vendor the code; consumers who integrate must obtain written permission and record it in their `LICENSES.md` or equivalent.
- **AGPL-3.0**: would require strong reciprocal licensing — not applicable in this curated list.

## 7 QA discipline

The UX track has its own QA pattern, distinct from the OpenSpec worker→QA flow:

1. **Author** (UX role; can be `bmad-agent-ux-designer` or a human) drafts the per-journey doc.
2. **Reviewer** (PM role + ≥1 design-aware peer) walks the journey from the PRD, against the mock, asking:
   - Does every named capability in the PRD's Journey Requirements Summary appear in the mock?
   - Are tone/voice/motion choices consistent with `DESIGN.md` §1 Principles?
   - Are non-trivial components flagged for §5.2 review?
3. **Verdict** uses the same literals as [verdict-contract.md](verdict-contract.md):
   - `✅ APPROVED` — UX doc lands; ready for Gate B.
   - `⚠️ ISSUES FOUND (iter N)` — author revises.
   - `❓ CLARIFICATION NEEDED` — escalates to PM; UX track moves to `blocked-by-prd` (a sibling of OpenSpec's `blocked-by-spec`).

Max 2 rework cycles per journey doc; iter 3 escalates per [verdict-contract.md](verdict-contract.md) §3.

## 8 HITL gate impact

The HITL gate sequence in [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §5 updates:

| Gate | Updated description |
|---|---|
| **B — Post-ADRs + Post-UX** (was: Post-ADRs only) | Architecture **and** UX both complete. PM/Architect approves: tech bets + data model + UX coherence. Cannot slice without both. |

For headless / API-only consumers, Gate B passes on Architecture alone (the consumer's `docs/ux/README.md` declares `no-ui-consumer`).

## 9 Cross-references

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) — canonical workflow this spec extends
- [skills-distribution.md](skills-distribution.md) + RFC-0001 — why we don't vendor third-party skills
- [verdict-contract.md](verdict-contract.md) — verdict literals reused for UX QA
- [parallel-review.md](parallel-review.md) — QA discipline this spec mirrors
- [agentic-failures.md](agentic-failures.md) — `goal_drift` if UX track produces journey docs without FR back-references
- [contributing.md](../docs/contributing.md) §6 — backwards compatibility for consumers that deviate from the recommended DESIGN.md format
