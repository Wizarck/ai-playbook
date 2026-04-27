# Create UX Design Workflow

**Goal:** Create comprehensive UX design specifications through collaborative visual exploration and informed decision-making, where the agent acts as a UX facilitator working with the product stakeholder. The workflow is **visual-first** at every step — text descriptions of design language never substitute for visual artefacts.

This skill implements the three-step order specified in [`specs/ux-track.md`](../../specs/ux-track.md) §3.

---

## WORKFLOW ARCHITECTURE

This uses **micro-file architecture** for disciplined execution:

- Each step is a self-contained file with embedded rules
- Sequential progression with user control at each step (light-ceremony pattern)
- Document state tracked in frontmatter
- Append-only document building through conversation
- **Visual artefact mandatory** at every step (steps 1, 2, 3 each produce one)

---

## Activation

1. Load config from `{project-root}/_bmad/bmm/config.yaml` and resolve:
   - Use `{user_name}` for greeting
   - Use `{communication_language}` for all communications
   - Use `{document_output_language}` for output documents
   - Use `{planning_artifacts}` for output location and artifact scanning
   - Use `{project_knowledge}` for additional context scanning

### Paths

- `default_output_file` = `{planning_artifacts}/ux-design-specification.md`
- `inspiration_doc` = `{project-root}/docs/ux/inspiration.md`
- `palette_options` = `{project-root}/docs/ux/variants/palette-options.html`
- `variants_dir` = `{project-root}/docs/ux/variants/`
- `design_canonical` = `{project-root}/docs/ux/DESIGN.md`
- `journey_docs` = `{project-root}/docs/ux/j1.md` … `jN.md`
- `components_catalogue` = `{project-root}/docs/ux/components.md`

### Templates

Copyable templates live in `{playbook}/templates/ux/`:

- `inspiration.md.template`
- `palette-options.html.template`
- `variants-index.html.template`
- `DESIGN.md.template` (9-section format)
- `journey.md.template`
- `components.md.template`

Copy on first use of the UX track in this project. Adapt freely.

## EXECUTION

- ✅ YOU MUST ALWAYS SPEAK OUTPUT in your Agent communication style with the config `{communication_language}`
- ✅ YOU MUST ALWAYS WRITE all artefact and document content in `{document_output_language}`
- ✅ YOU MUST PRODUCE A VISUAL HTML ARTEFACT at steps 2 and 3 — never substitute by markdown descriptions of design tokens
- ✅ AT STEP 3, run **one agent per creative engine in parallel** (the 5 from `ux-track.md` §5.1) — never hand-code variants and pass them as engine output
- ✅ AT PHASE A SCRUB (post-pick), strip every external repo path and engine name from the canonical mock; replace with self-referential `DESIGN.md §N` citations
- ✅ DECLARE COLOURS IN OKLCH (`ux-track.md` §10), never hex-only

### Three-step order (per `ux-track.md` §3)

**Step 1 — Inspiration.** Ask the user for reference images / URLs / vibe descriptions. Compile into `inspiration.md` (use the template). Extract themes (colour temperature, typographic weight, density, motion register). Do not propose design language as text.

**Step 2 — Palette validation.** Derive 3-5 palette options from the inspiration themes. Render as `palette-options.html` with real swatches + mini-previews of YOUR product's primary surface (one row, one button, one regulatory badge, one key number). User picks one (or a hybrid).

**Step 3 — Variant generation.** With palette locked, run **one agent per creative engine in parallel** (5 engines per `ux-track.md` §5.1). Each agent applies its engine's actual methodology to the same brief; only typography / spatial / motion vary. Each variant is self-documenting (banner + audit head comment per §6) and links from `variants/index.html` (the comparison page).

**Pick + Phase A scrub + Phase B consolidation** (per `ux-track.md` §9). After the user picks, archive rejected variants, scrub engine references from the canonical, write `DESIGN.md` (9-section per template), then write per-journey docs (`jN.md`) + companion mocks where surfaces meaningfully differ, then write `components.md`.

### Iteration: bones + layer remix (per `ux-track.md` §8)

If the user likes one variant's structure but wants a different colour layer: do not re-run all variants. Open a fresh palette-options round on the chosen bones; user picks; produce one new variant `mock-X<N>-<descriptor>.html` where X is the structural pick. Both files coexist; the original X is preserved as fallback.

### QA discipline (per `ux-track.md` §16)

Each per-journey doc + mock goes through Author → Reviewer (PM + 1 design-aware peer) → Verdict. Review checklist:

- Every named capability in the PRD's Journey Requirements Summary appears in the mock.
- Tone / voice / motion choices consistent with `DESIGN.md` §1 Principles.
- Non-trivial components flagged for catalogue review.
- Head-comment audit includes the WCAG-AA verification block.
- Audit cites `DESIGN.md §N`, not external repo paths.
- Colour block declares OKLCH, not hex-only.

Verdict literals from [`verdict-contract.md`](../../specs/verdict-contract.md). Max 2 rework cycles before escalation.

---

Read fully and follow: `./steps/step-01-init.md` to begin the UX design workflow.
