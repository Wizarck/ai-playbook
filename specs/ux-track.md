# ux-track.md

> **Status**: v2.0.0. Substantially expanded from v1.0.0 based on consumer learnings (nexandro M2). Codifies the three-step order (inspiration → palette → variants), self-documenting deliverables, palette decoupling as an intermediate visual step, bones+layer remix iteration, OKLCH-canonical colour rule, per-journey docs format, Storybook-style components catalogue with a stewardship clause, an anti-patterns checklist baked into the audit, and a WCAG-AA verification ritual. Removed the v1.0.0 license-attribution section as unnecessary scaffolding — the curated engines are now listed plainly with a one-line "check the licenses for your use case" reminder. Additive against v1.0.0; existing consumers may migrate at their own pace.

## 1 Purpose

The canonical workflow ([runbook-bmad-openspec.md](runbook-bmad-openspec.md)) was silent on UX before v0.5.0. PRDs declared capabilities; OpenSpec changes implemented them; mocks and component decisions happened ad-hoc. v0.5.0 introduced the UX Track. v2.0.0 of this spec lands the **operational rules** that make the track produce coherent UX without re-inventing process every project.

Two recurring failures motivate the rules:

1. **Text descriptions of design language do not produce design decisions.** Consumers who tried to discuss "brand voice" in markdown without visual artefacts converged on no decision and burned a round of work. The spec now mandates a visual artefact at every step.
2. **Mixing palette + typography + spatial in one big variant set produces noise.** When the only thing changing between variants is everything, the user can't isolate what they like. The spec now decouples palette validation as its own step, then runs typography/spatial variants on the locked palette.

The UX Track is **mandatory** for any consumer that ships a UI; it is **trivially skippable** for headless / API-only consumers (see §16).

## 2 Position in the workflow

```
PRD → Personas → ADRs       ──┐
       │                      │
       ▼ Gate A               ├──► Slicing → Gate C → /opsx:propose → ...
       │                      │
       ├──► UX Track ─────────┤   (parallel with Architecture)
       │   (3 steps + mocks)  │
       │                      │
       └──► bmad-create-architecture ──┘
                              ▲
                              │
                          Gate B
                  (Architecture + UX both done)
```

UX runs in parallel with Architecture between Gate A and Gate B. **Gate B waits on both.** Until UX is done, slicing cannot start — the slice boundaries depend on which screens exist.

For headless / API-only consumers, the UX Track produces a one-line "no UI in this consumer" notice in `docs/ux/README.md` and Gate B passes on Architecture alone.

## 3 The three-step order

The order is **mandatory**. Each step produces a visual HTML deliverable before the next. Never substitute text descriptions for visual artefacts.

### Step 1 — Inspiration

The user provides reference images, URLs, or vibe descriptions — anything visual or specific enough to anchor design decisions. The skill compiles them into a quick gallery (or an inline reference list) and extracts recurring themes (colour temperature, typographic weight, density, motion register).

**Deliverable.** A short doc or gallery in `_bmad-output/research/inspiration.md` listing what was seen and what themes emerged. Optional `docs/ux/inspiration.html` if the references warrant a contact-sheet.

**Anti-pattern.** Skipping inspiration and proposing "brand voice" options as text. Consumers who do this consistently fail step 2.

### Step 2 — Palette validation

The skill derives 3-5 palette options from the inspiration themes and presents them as a single HTML page with **real colour swatches** plus **mini-previews** of the actual product surface (one ingredient row, one accent button, one allergen badge, one margin number — whatever the product has that is colour-load-bearing).

**Deliverable.** `docs/ux/variants/palette-options.html`. The user picks one palette (or a hybrid like *"P3 accent + P1 ink"*).

**Why a separate step.** Decoupling palette from typography/spatial reduces the decision surface. The user can look at 4 palettes side-by-side without having to mentally compose typography or layout — those are still TBD. When the chosen palette is locked, step 3 only varies what is left.

### Step 3 — Variant generation

With palette locked, the skill runs **one creative-engine per variant, in parallel** (§5). Each agent interprets the locked palette through its own typography / spatial / motion lens, producing a self-documenting mock per variant (§6). All variants are linked from a comparison index page (§7).

The user picks one variant — or asks for a bones+layer remix where the structure of one variant carries the typography/atmosphere of another (§8).

**Deliverable.** N mocks at `docs/ux/variants/mock-*.html` plus `docs/ux/variants/index.html` as the comparison page.

After picking, Phase A (scrub) and Phase B (consolidation) run (§9) to produce the canonical `docs/ux/DESIGN.md`.

## 4 Artefacts produced

| Artefact | Path | Purpose |
|---|---|---|
| `docs/ux/inspiration.md` | project-level | Step 1: themes extracted from user's references. |
| `docs/ux/variants/palette-options.html` | project-level | Step 2: visual palette comparison. |
| `docs/ux/variants/mock-*.html` | per variant | Step 3: variants with locked palette. |
| `docs/ux/variants/index.html` | project-level | Step 3 / pick: navigation across variants with attribution to nothing — see §6 self-documenting rule. |
| `docs/ux/DESIGN.md` | project-level | Canonical 9-section design system, written after the user picks a variant. |
| `docs/ux/{journey-id}.md` | per user journey | Mock + interaction notes for a specific JTBD/journey from the PRD. One per journey. |
| `docs/ux/variants/mock-j{N}-*.html` | per journey (when warranted) | Companion mock for journeys whose surface meaningfully differs from J1's. |
| `docs/ux/components.md` | project-level | Storybook-style catalogue of named components, written **after** the journey mocks (not before — see §12). |
| `docs/ux/variants/_archive/` | project-level | Rejected variants and earlier-round artefacts retired here. Internal reference only. |

Each per-journey doc MUST cross-reference the PRD journey + the FRs it satisfies. A journey doc with no FR back-references is `goal_drift` per [agentic-failures.md](agentic-failures.md).

## 5 Variant generation: one agent per engine

Step 3 of §3 fans out: **one agent per creative-engine, in parallel.** Each agent applies one engine's actual methodology to the same brief (the locked palette, the same recipe / surface content, the same persona + device). The result is N variants where the only axes that vary are typography, spatial, and motion — palette is identical across all.

### 5.1 The starter set (5 engines)

The following engines are the recommended starter set. Use them; if the consumer wants a new engine added, raise a PR against this section.

| Engine | Stars | License | What it brings |
|---|---|---|---|
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 22.1k | Apache-2.0 | 7 reference guides (typography, color, spatial, motion, interaction, responsive, UX writing) + ~25 anti-pattern detectors. Strong for disciplined, restrained surfaces. |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | 13.2k | unspecified | Anti-slop instruction files; variants for minimalist, brutalist, soft, image-to-code. Strong for distinct aesthetic registers. |
| [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design) | 7.8k | unspecified (personal-use) | 20 design philosophies × 5 aesthetic traditions; brand-asset protocols. Strong for high-fidelity static surfaces with explicit philosophy. |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 70.9k | MIT | 161 industry-specific rules, 67 styles, 161 palettes, 57 font pairings, 99 UX guidelines. Strong when the product maps cleanly to one of its verticals. |
| [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) | 66.1k | MIT | 69+ DESIGN.md files extracted from real brands. Source of the 9-section format adopted in §12. |

**Star counts and license fields verified via `gh api repos/{owner}/{repo}` on 2026-04-27.** Refresh annually; flag stale rows.

Consumers must check each engine's licence against their own project's licensing constraints. The playbook references these engines; it does not vendor them.

### 5.2 Agent prompt template

Each agent gets a self-contained brief with:

- **Path to the engine source** (cloned to `_bmad-output/research/skills/<engine>/`, gitignored).
- **The locked palette** (CSS variable block, OKLCH form per §10).
- **The brief content** — the recipe / data / persona / device that will appear on the variant. All agents render the same content; only their interpretation differs.
- **Constraints** — single self-contained HTML, embedded CSS, no JS frameworks, allergen icon+text+border, tablet-first responsive, ≥48px touch targets, prefers-reduced-motion, WCAG-AA verified.
- **Banner + head-comment audit format** (per §6).
- **Output path** for the variant HTML.
- **Reporting back format** (≤200 words: which philosophy/variant chosen, design tokens extracted, specific anti-patterns avoided, contrast ratios verified, deviations declared).

Run the N agents in parallel (background tasks). When all return, assemble the index page (§7).

### 5.3 Research scratch directory

Engines are cloned to `_bmad-output/research/skills/<engine-name>/` for the agents to read. Add `_bmad-output/research/skills/` to the consumer's `.gitignore` — these clones are research scratch, not vendored code. They never get committed.

## 6 Self-documenting deliverables

Each variant mock is **self-documenting**. Two parts:

### 6.1 Banner inside `<body>`

A short `<div class="provenance">` at the top of the body stating what surface this is:

```html
<div class="provenance" role="note" aria-label="Screen context">
  <b>nexandro · Recipe edit · Module 2 / Journey 1</b>
  <span class="note">Tablet-first kitchen surface. AA-verified contrast on every text pair, ≥48px touch targets, prefers-reduced-motion respected, no hover-only affordances on pointer:coarse.</span>
</div>
```

The banner does **not** name the engine that produced the variant. The design speaks for itself; engines are silent infrastructure.

### 6.2 HTML head comment with the audit

A structured comment immediately after `<!doctype html>` records the per-dimension audit. The format:

```html
<!--
  <Project> · <Surface name> · <Module / Journey>
  <One-line summary of the surface and its primary device>

  Per-dimension audit — each note records the WHY of the choice, the contrast
  verified, and the anti-patterns explicitly avoided. All references point inward,
  to the project's own design system at docs/ux/DESIGN.md.

  typography:
    - <choice + WHY, citing DESIGN.md §N>
    - <antipatterns avoided>
  color:
    - <token list + WHY>
    - <WCAG-AA ratios on every new pair>
    - <antipatterns avoided>
  spatial: ...
  motion: ...
  interaction: ...
  responsive: ...
  ux-writing: ...

  Anti-patterns explicitly avoided (per §13 checklist):
    <list>
-->
```

**Citations point inward.** Audit references to design rules cite the project's own `docs/ux/DESIGN.md §N` — never paths into a cloned engine repo (`reference/typography.md §"…" (L13-23)` is forbidden because those paths break when the engine clone is gone). Self-referential audit content survives the engine being uninstalled.

## 7 Index / compare page

`docs/ux/variants/index.html` is a mandatory deliverable. It links every variant produced in step 3 with a short description of its visual fingerprint (what makes it different) — colour temperature, typographic stack, density, motion language. Each card states the surface (J1 recipe edit, J2 cost spike, etc.) and the device (tablet, mobile, desktop).

The index is the artefact the user opens to decide. After the decision, the index is updated to mark the canonical pick (e.g. `★ user pick`) and the rejected variants are archived (§8).

## 8 Iteration loop

After the user picks, two patterns emerge.

### 8.1 Palette decoupling (the M2 G→G' pattern)

If the user likes the structure of one variant but wants a different colour layer, do **not** re-run all N variants. Instead:

1. Confirm the structural pick (the "bones").
2. Open a fresh palette-options round (§3 step 2) on top of the bones — show the user 3-5 palette candidates rendered against the chosen variant's structure.
3. User picks the palette.
4. Produce one new variant: `mock-X2-<palette-name>.html` where X is the structural variant the user picked. The naming records the lineage: bones X + new layer.

This pattern fired in the nexandro M2 work: the user picked Mock G's discipline but wanted the Pulcinella palette over G's clay/terracotta. Result was `mock-G2-trattoria.html`. Both files coexist; the original G is preserved as a fallback.

### 8.2 Layer-only iteration (smaller drift)

If the user wants a small change (typography weight, one token swap, one specific component visual), edit the canonical mock in place. Do not start a new variant. Document the change in the head-comment audit.

### 8.3 Naming convention

- `mock-<letter>-<theme>.html` — first-round variants from step 3 (e.g. `mock-G-impeccable.html` … but the engine name in the filename is the only place an engine name surfaces, and it stays even after scrub because it's the structural identifier).
- `mock-<letter><N>-<descriptor>.html` — bones-of-letter + Nth iteration layer (e.g. `mock-G2-trattoria.html`).

## 9 Phase A scrub + Phase B consolidation

After the user picks a variant, run two phases mechanically.

### Phase A — Scrub

1. Move every rejected variant to `docs/ux/variants/_archive/`. They stay as historical record but disappear from the index.
2. Move stale earlier-round artefacts to `_archive/` (e.g. text-only DESIGN-*.md files from a pre-visual round, comparison docs from an earlier audit).
3. Open the canonical pick file (the chosen variant). Strip every reference to the underlying engine: the banner, the head comment, CSS comments, anywhere. Replace external citations (`reference/typography.md §X`) with self-referential ones (`DESIGN.md §3 Typography`). The audit *substance* — the WHY of design choices, the contrast ratios, the anti-patterns avoided — stays. The engine *attribution* goes away.
4. If a fallback variant is preserved (per §8.1), scrub it the same way and add an explicit note that it is a fallback ("Mock G — earlier variant kept as fallback. See G' for canonical and DESIGN.md for the design system.").
5. Rewrite `docs/ux/variants/index.html` to be minimal: canonical pick, fallback (if any), palette-options as decision rationale, plus a link to `_archive/` for historical reference.

### Phase B — Consolidation

Write `docs/ux/DESIGN.md` (canonical, 9 sections per §12) derived from the canonical pick's tokens + audit content. The DESIGN.md becomes the single source of truth; the variant mock continues to exist as a visual reference but is no longer authoritative — when DESIGN.md and the mock disagree, the mock is updated to match DESIGN.md.

After Phase B, the mocks become **derived artefacts**. Edits to design rules land in DESIGN.md; mocks regenerate to match.

## 10 OKLCH-canonical colour rule

Every colour token in `DESIGN.md`, in mocks, in components, declared in **OKLCH**. Hex is allowed only as a derivation comment.

```css
:root {
  --bg: oklch(94.5% 0.012 70);    /* derivation: ~#F4EFE6 */
}
```

**Why.** OKLCH is perceptually uniform: a 5% L step looks like a 5% L step everywhere on the colour wheel. Hex is clamped to sRGB; on wide-gamut (P3 / Rec.2020) displays the OKLCH form preserves saturation while hex renders flatter. Mixing the two across surfaces produces visible drift even when the values look "equivalent" on paper.

**The rule.** Mocks must declare colours in OKLCH. The `:root { ... }` block opens with `oklch(...)`, never `#......`. That's the litmus test during scrub (§9 Phase A).

**For SVG fills or other contexts that don't accept oklch().** Use a hex fallback alongside, with an inline comment explaining why. Or use `color-mix()` to derive.

**Dual representation when DESIGN.md has machine-readable token YAML** (see §11). The CSS surfaces (mocks, runtime components) declare OKLCH canonical. The YAML frontmatter of `DESIGN.md` (and any `tokens.json` exports) declare hex computed equivalents alongside, so external tooling that doesn't parse OKLCH can still consume the design system. The OKLCH form remains source-of-truth; the hex form is a derivation snapshot regenerated whenever OKLCH changes. Tooling consumers must NOT round-trip hex → OKLCH — that path is one-way and lossy. See §11.7 for full discipline.

## 11 DESIGN.md format spec

`docs/ux/DESIGN.md` is the canonical durable artefact for a project's design system. It informs Gate B approval (per [`runbook-bmad-openspec.md`](runbook-bmad-openspec.md) §2.3) and is read by every downstream artefact (per-journey `jN.md` docs, `components.md` catalogue, OpenSpec proposals, implementation code). The spec below extends ai-playbook's existing 9-section format with **tier 1 adoptions from [google-labs-code/design.md](https://github.com/google-labs-code/design.md)** (Apache-2.0, alpha): YAML frontmatter for machine-readable tokens, token reference syntax, component variants pattern, and consumer behavior table.

ai-playbook keeps unique value: OKLCH-canonical (§10), visual-first 3-step (§3), 5 creative engines starter set (§5), per-journey `jN.md` + companion mocks (§12), Phase A scrub + Phase B consolidation (§9), audit head-comment WCAG verification block (§6.2), Storybook-style components catalogue (§13).

### 11.1 Hybrid format (YAML frontmatter + Markdown body)

Every `DESIGN.md` has two layers:

1. **YAML frontmatter** — machine-readable design tokens, delimited by `---` fences at the top of the file. Tokens are normative.
2. **Markdown body** — human-readable design rationale organized into `##` sections. Prose explains *why* the tokens exist and how to apply them.

The tokens are the source of truth for values. The prose is the source of truth for context, anchor culturals, anti-patterns, and rationale. Linters and codegen consume the YAML; humans and downstream agents consume both.

### 11.2 Token schema

The YAML frontmatter follows this schema (all fields optional, but order recommended):

```yaml
---
version: alpha                # current; bump when schema breaks
name: <string>                # display name
description: <string>         # one-paragraph mission
colors:
  <token-name>: "<hex>"       # hex computed equivalent (canonical OKLCH lives in CSS — see §11.7)
typography:
  <token-name>:
    fontFamily: <string>
    fontSize: <Dimension>
    fontWeight: <number>
    lineHeight: <Dimension | number>
    letterSpacing: <Dimension>
spacing:
  <scale-level>: <Dimension>
rounded:
  <scale-level>: <Dimension>
components:
  <component-name>:
    <property>: <string | token reference>
---
```

**Token types**:

| Type | Format | Example |
|:---|:---|:---|
| Color | hex sRGB string (computed equivalent of OKLCH per §11.7) | `"#1A1C1E"` |
| Dimension | number + unit (`px`, `em`, `rem`) | `48px`, `-0.02em` |
| Token Reference | `{path.to.token}` | `{colors.primary}` |
| Typography | object with `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing` | see schema |

**Component property whitelist**: `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, `width`. Custom properties accepted with warning per §11.6 consumer behavior.

### 11.3 Token reference syntax

Cross-references between tokens use curly-brace path notation: `{colors.primary}`, `{rounded.md}`, `{typography.body-md}`. References resolve from root of YAML.

```yaml
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-fg}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: "10px 20px"
```

For most token groups, references must point to a primitive value (e.g. `colors.accent`), not a group (`colors`). Within `components`, references to composite values (e.g. `{typography.body-md}`) are permitted.

A reference that doesn't resolve to a defined token MUST trigger an error in any linter consuming the file (see §11.8 tooling).

### 11.4 Section order

Sections use `##` headings. The 8 canonical sections (Google design.md compatible) plus ai-playbook extensions appear in this order. Sections may be omitted; those present must follow this order:

| # | Section | Source | Notes |
|:---|:---|:---|:---|
| 1 | Overview | Google canonical | Also: "Brand & Style" |
| 2 | Colors | Google canonical | Palette + rationale |
| 3 | Typography | Google canonical | Type roles + scale |
| 4 | Layout | Google canonical | Also: "Layout & Spacing" |
| 5 | Elevation & Depth | Google canonical | Or alternative hierarchy strategy if flat |
| 6 | Shapes | Google canonical | Rounded discipline |
| 6.5 | **Iconography** | **ai-playbook extension** | Library + stroke + size + whitelist. Preserved as unknown section per §11.6 defensive parsing. |
| 7 | Components | Google canonical | Atomic component contracts |
| 8 | Do's and Don'ts | Google canonical | Practical guardrails |

**Iconography** is an ai-playbook extension beyond Google's canonical 8 because icon library discipline (lucide cherry-picked vs Heroicons full vs Tabler) is a frequent leakage point and merits explicit section. Per §11.6 consumer behavior, unknown sections are preserved without error — Google CLI tools accept ai-playbook files without modification.

### 11.5 Component variants pattern

Components map a name to a group of sub-token properties. **Variants** (hover, active, pressed, disabled, locked, etc.) are expressed as **separate component entries with related key names**, not as nested fields:

```yaml
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-fg}"
    rounded: "{rounded.sm}"
    padding: "10px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.fg}"
  button-primary-locked:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.fg}"
```

Variant entries inherit nothing implicit — declare only the properties that change. The downstream consumer (CSS generator, codegen) merges variant entries onto the base by name match (`button-primary` → `button-primary-*`).

This pattern aligns with Tailwind utility variants and CSS state pseudo-classes, and is interoperable with W3C Design Tokens Format Module composite tokens.

### 11.6 Consumer behavior for unknown content

Any consumer (linter, codegen, downstream agent) reading a `DESIGN.md` MUST follow this behavior table:

| Scenario | Behavior | Example |
|:---|:---|:---|
| Unknown section heading | Preserve; do not error | `## Iconography`, `## Motion`, `## Voice` |
| Unknown color token name | Accept if value is valid | `surface-container-high: '#ede7dd'` |
| Unknown typography token name | Accept as valid typography | `telemetry-data` |
| Unknown spacing value | Accept; store as string if not a valid Dimension | `grid-columns: '5'` |
| Unknown component property | Accept with warning | `borderColor` |
| Duplicate section heading | Error; reject the file | Two `## Colors` headings |
| Broken token reference | Error; emit `broken-ref` finding | `{colors.tertiary}` when no `tertiary` defined |

This permissive defensive parsing lets ai-playbook ship extensions (Iconography, future custom sections) without breaking external tooling. The cost is shifted to upstream authors: if you misspell a section name, it's silently preserved as unknown — review your sections.

### 11.7 Dual color representation

ai-playbook keeps OKLCH-canonical (§10) for runtime CSS, and emits hex computed equivalents in `DESIGN.md` YAML frontmatter for external tooling compatibility (Google CLI, DTCG export, Tailwind theme.json, Figma variables import).

```yaml
---
colors:
  bg: "#141618"   # OKLCH oklch(0.20 0.005 250) — page surface, neutral grey-blue
  accent: "#e49000"   # OKLCH oklch(0.72 0.18 75) — interactive primary, warm ámbar
---
```

```css
/* Runtime CSS in mocks + DESIGN.md prose + components */
:root {
  --bg: oklch(0.20 0.005 250);     /* derivation: #141618 */
  --accent: oklch(0.72 0.18 75);   /* derivation: #e49000 */
}
```

**Source of truth**: the OKLCH value. Whenever OKLCH changes, regenerate hex via the conversion formula (OKLCH → OKLab → linear sRGB → sRGB → hex). The Python snippet in `scripts/oklch-to-hex.py` (or equivalent) automates this; YAML hex SHOULD be updated atomically with CSS OKLCH commits.

**One-way only**: never round-trip hex → OKLCH to update the canonical. That path is lossy (hex is sRGB-clamped, OKLCH spans wider gamut). Tooling consumers MUST treat YAML hex as a snapshot, not a primary input.

**WCAG-AA contrast verification** (§15) uses OKLCH luminance arithmetic, not hex. The verification block in the audit head-comment cites OKLCH luminance values. Hex values inline serve only humans skimming and external tools.

### 11.8 Tooling integration

**Optional**: `npx @google/design.md lint docs/ux/DESIGN.md` validates structural correctness, broken references, contrast ratios, orphaned tokens. Run as advisory cross-check, NOT as ai-playbook gate. The tool consumes hex YAML; OKLCH discipline (§10) lives outside its scope.

**Optional**: `npx @google/design.md export --format dtcg docs/ux/DESIGN.md > tokens.json` exports to W3C Design Tokens Format Module for Figma / Style Dictionary integration.

**Optional**: `npx @google/design.md export --format tailwind docs/ux/DESIGN.md > tailwind.theme.json`. Note: Tailwind v4 uses `@theme { ... }` directly in CSS; this export is mainly relevant for Tailwind v3 projects.

**Future**: ai-playbook custom validator (`scripts/ux-design-lint.py`) supports OKLCH-canonical natively, enforces ai-playbook-specific rules (Iconography section presence in UI consumers, audit head-comment format, hand-coded-mocks anti-pattern §16). Lands in v0.9.x.

### 11.9 Reference

Format derived from:

- ai-playbook 9-section format (originated from `awesome-design-md` engine §5.1, retained as primary structure)
- [google-labs-code/design.md](https://github.com/google-labs-code/design.md) (Apache-2.0, alpha) — YAML frontmatter schema, token reference syntax, component variants pattern, consumer behavior table, 8-section canonical order

Pilot validation: `eligia-core/docs/ux/DESIGN.md` (Z.2 Phase 2 ELIGIA dashboard, 2026-05-01). Format verified production-ready with palette D Things 3 Night tokens + variant D Structured timeline lock.

## 12 Per-journey docs format

For every user journey identified in the PRD:

### Frontmatter

```markdown
---
journey: J<N> — <one-line title>
status: canonical (M<N> MVP) | design intent (M<N+>.x deferred) | edge case
persona: <persona name from personas-jtbd.md>
device: <primary device, locked>
mock: variants/mock-j<N>-<descriptor>.html | inline (single error state) | deferred to <next milestone>
last-updated: YYYY-MM-DD
parent: docs/ux/
related:
  - DESIGN.md
  - <other journey files>
  - ../prd-<module>.md §User Journeys §J<N>
  - ../architecture-decisions.md (relevant ADRs)
---
```

### Sections (in order)

1. **Goal** — one paragraph naming the JTBD.
2. **Trigger** — when the user enters this journey.
3. **Walkthrough** — numbered steps. Each step states what the user does and what the system does. Cite the FR satisfied at each step. Use code-fence references to specific component names from `components.md` and to DESIGN.md sections.
4. **Components used** — comma-separated list with links to `components.md` entries.
5. **Capabilities satisfied** — FR list, cross-referenced to the PRD.
6. **Edge cases** — one-line summary of each + link to the journey doc that covers it (often a sibling J<M>.md).
7. **Decisions specific to <journey>** — design choices unique to this journey, with brief rationale.
8. **Notes for implementation** — the things the implementer needs to know that aren't obvious from the mock or DESIGN.md.

### When a separate mock is warranted

If the surface meaningfully differs from another journey's surface (different layout, different device, different persona, different interaction pattern), produce `docs/ux/variants/mock-j<N>-<descriptor>.html` as a companion. If the surface is identical to another journey's (or the journey is an inline error state on an existing surface), inline a CSS sketch or an annotated paragraph in the journey doc itself.

The MVP heuristic: if the implementation team needs a separate Storybook story to render this journey's surface, they need a separate mock. Otherwise, the existing mock + journey doc is enough.

## 13 Components catalogue (Storybook-style)

`docs/ux/components.md` is written **after** the journey mocks, not before. The journey mocks reveal which components are actually in use; writing the catalogue before risks listing components that won't appear (and skipping components that will).

### Per-component entry

For each named component:

- **Purpose** — one sentence.
- **Status** — canonical (current MVP) / deferred (a future milestone) / feature-flagged.
- **Used by** — list of journey docs that consume it.
- **Capability** — FRs the component implements.
- **Data shape** — TypeScript-ish interface, key props only.
- **Component-specific states** — beyond the universal 8 (default / hover / focus / active / disabled / loading / error / success per DESIGN.md §4).
- **Tokens used** — the specific DESIGN.md tokens this component reads.
- **Behaviour** — interactions, keyboard model, screen reader treatment.
- **Edge cases** — the gotchas, with degradation strategy.
- **Storybook stories** — list of variants worth seeing (default, loading, error, empty, edge state, RTL where relevant).

### Stewardship clause

The catalogue ends with a short stewardship clause:

> The components catalogue is the contract between design and engineering. If a Storybook story does not match the doc here, the doc is wrong — fix it.

Or the inverse, depending on which is the canonical source for a given consumer (DESIGN.md is canonical for tokens; Storybook is canonical for component visuals once mounted). The clause exists to break ties.

### Storybook-first development

Components are developed in **Storybook with stories** before they appear on a screen. Stories cover at minimum: default, loading, error, empty, edge (long text / large numbers / missing data). A component without ≥3 of these states is non-trivial and triggers design review (see §12 of v1.0.0, retained):

A component is **non-trivial** if any of:

- It composes ≥2 primitives.
- It renders externally-sourced data.
- It carries regulatory weight (e.g. allergen badge, EU 1169/2011 label).
- It is invoked by an agent flow.

Non-trivial components require ≥1 alternative explored, decision documented in `components.md`. Trivial components skip review.

After review, components promote to the consumer's `packages/ui-kit/` (or equivalent shared package). Base layer is **shadcn/ui + Tailwind CSS** by convention; consumers may swap if their stack differs (Vue / Svelte / Web Components) — document the swap in `AGENTS.md`.

Storybook is **published in CI** for static review on every PR.

## 14 Anti-patterns checklist (baked into the audit)

The head-comment audit (§6.2) ends with an explicit "anti-patterns avoided" list. The canonical checklist (≈25 items, drawn from the curated engines):

`side-tab` (border-accent-on-rounded), `nested-cards`, `monotonous-spacing`, `everything-centered`, `bounce-easing`, `dark-glow`, `icon-tile-stack` (rounded-square icon tiles above headings), `pure-black-white`, `gray-on-color`, `ai-color-palette` (tech-blue / teal / purple reflex), `glassmorphism`, `gradient-text`, `flat-type-hierarchy`, `tiny-text` (< 13 px), `all-caps-body`, `wide-tracking` on body, `justified-text`, `tight-leading`, `cramped-padding`, `layout-transition` (animating `width` / `height`), `hero-metric` template, `identical card grids`, `modal-as-first-thought`, `em dashes`.

Plus absolute bans for nexandro-style products (food / regulated / professional surfaces): emoji icons in critical paths, decorative gradients, illustrative SVG imagery in non-marketing surfaces.

The audit lists which of these were considered and avoided; if a variant uses one of these patterns deliberately, the comment must justify the exception with a project-specific rationale.

## 15 WCAG-AA verification ritual

Every text pair introduced by a mock or component must be WCAG-AA verified, with the ratio recorded in the head-comment audit. Format:

```
WCAG-AA verified on every text pair:
  --ink on --bg                → ~14:1   (AA+ body)
  --mute on --bg               → ~5.0:1  (AA body)
  --mute on --surface          → ~4.6:1  (AA body)
  --accent-fg on --accent      → ~5.1:1  (AA button)
  --success on --bg            → ~4.6:1  (AA semantic)
  --destructive on --bg        → ~5.6:1  (AA badge)
  --destructive on --warn-bg   → ~5.4:1  (AA badge on tinted)
```

Body text needs ≥ 4.5:1; large text and UI components ≥ 3:1; allergen / regulatory labels typically ≥ 5:1 with extra emphasis.

The agent prompt template (§5.2) requires the verification block in the audit. Mocks that ship without it are non-compliant and get rejected at QA (§17).

## 16 Anti-pattern: hand-coded mocks pretending to be design

Hand-coded mocks (HTML / CSS produced without invoking a creative engine) are **baseline reference only**. They are not deliverable variants. The temptation to ship a quick hand-coded mock as "variant X" exists; the spec forbids it.

**Why.** Hand-coded mocks default to whatever is in the writer's head — usually a Notion / Linear pastiche, occasionally a shadcn-defaults pastiche. They lack design fingerprint and converge on generic. Visually, you can't tell three hand-coded mocks apart.

**When hand-coded is acceptable.** As a baseline for "what would a generic implementation look like" — useful for setting a floor against which the engine-driven variants are compared. Mark them clearly as `baseline` in the index, never as `variant`.

## 17 QA discipline

The UX track has its own QA pattern, distinct from the OpenSpec worker→QA flow:

1. **Author** (UX role; can be `bmad-agent-ux-designer` or a human) drafts the per-journey doc + the mock.
2. **Reviewer** (PM role + ≥1 design-aware peer) walks the journey from the PRD against the mock, asking:
   - Does every named capability in the PRD's Journey Requirements Summary appear in the mock?
   - Are tone/voice/motion choices consistent with `DESIGN.md` §1 Principles?
   - Are non-trivial components flagged for §13 review?
   - Does the head-comment audit include the WCAG-AA verification block (§15)?
   - Does the audit cite DESIGN.md sections (and not external repo paths — §6.2)?
   - Does the colour block declare in OKLCH (§10)?
3. **Verdict** uses the same literals as [verdict-contract.md](verdict-contract.md):
   - `✅ APPROVED` — UX doc lands; ready for Gate B.
   - `⚠️ ISSUES FOUND (iter N)` — author revises.
   - `❓ CLARIFICATION NEEDED` — escalates to PM; UX track moves to `blocked-by-prd`.

Max 2 rework cycles per journey doc; iter 3 escalates per [verdict-contract.md](verdict-contract.md) §3.

## 18 HITL gate impact

The HITL gate sequence in [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §5 updates:

| Gate | Updated description |
|---|---|
| **B — Post-ADRs + Post-UX** (was: Post-ADRs only) | Architecture **and** UX both complete. PM/Architect approves: tech bets + data model + UX coherence (DESIGN.md tokens consistent with ADRs, every journey covered, components catalogue matches journey usage). Cannot slice without both. |

For headless / API-only consumers, Gate B passes on Architecture alone (the consumer's `docs/ux/README.md` declares `no-ui-consumer`).

## 19 Templates

Copyable templates ship in `templates/ux/`:

- `palette-options.html.template` — N palettes as visual rows + mini-previews.
- `variants-index.html.template` — comparison index page (canonical + fallback + archive).
- `DESIGN.md.template` — 9-section skeleton with OKLCH-first CSS block.
- `journey.md.template` — frontmatter + section skeleton.
- `components.md.template` — Storybook-style entry skeleton.

Consumers copy these on first use of the UX track. They are starting points, not specs — adapt freely.

## 20 Cross-references

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) — canonical workflow this spec extends
- [skills-distribution.md](skills-distribution.md) + RFC-0001 — why we don't vendor third-party engines
- [verdict-contract.md](verdict-contract.md) — verdict literals reused for UX QA
- [parallel-review.md](parallel-review.md) — QA discipline this spec mirrors
- [agentic-failures.md](agentic-failures.md) — `goal_drift` if UX track produces journey docs without FR back-references
- [contributing.md](../docs/contributing.md) §6 — backwards compatibility for consumers that deviate from §12's recommended DESIGN.md format
