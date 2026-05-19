## Why

Slice 4 (v0.18.0) reorganised the filesystem and moved ~17 runbooks under `docs/runbooks/` via `git mv`. The bodies still carry their pre-reorg shape — bilingual prose (Spanish + English), `> **Status**: vX.Y.Z` quoted-header metadata in place of YAML frontmatter, ad-hoc section ordering (some have "Steps", others "The walk-through", others "Quick diagnosis flow"), and inconsistent troubleshooting conventions. Three concrete problems block the slice-5 harmonisation pass (5.F):

1. **No frontmatter** ⇒ runbooks cannot be enumerated by `gen_indexes.py`, validated against a schema, or discovered by mkdocs nav consistently. INDEX.md is partially auto-generated but partially stale.
2. **Bilingual prose** violates D6 (ENGLISH mandate) and triggers `check_doc_language.py` heuristic warnings (`onboard-new-project.md` already flagged).
3. **No canonical procedural shape** ⇒ Diátaxis "how-to" expects an outcome-driven, step-by-step structure. Existing runbooks mix tutorial-style narrative ("Qué hace este runbook") with reference-style tables and ad-hoc troubleshooting. Operator cognitive load is uneven across the corpus.

Sub-slice 5.C runs in parallel with 5.A (rules), 5.D (tutorials), 5.E (process rules) after 5.B (concepts) merges. 5.B locked the anchor names this slice cross-references. 5.F (sequential harmonisation, runs last) bumps VERSION to v0.18.1 and composes the unified CHANGELOG entry.

## What Changes

- **Inject `runbook/v1` frontmatter** into every `docs/runbooks/*.md`. Required: `schema`, `slug`, `description`, `audience`, `estimated_time`. Optional: `prerequisite_runbooks`, `last_validated`.
- **Add `schemas/schema-runbook-v1.json`** so the frontmatter is validatable (parallel to `schema-rule-v1.json` and `schema-concept-v1.json`). Disjoint with both — no `paired_hardrule`, no `title`. Required fields enforced.
- **Rewrite bodies to canonical procedural format** (Diátaxis how-to). Each runbook now has:
  - `## Outcome` — one-paragraph statement of the post-runbook system state.
  - `## When to use this` — explicit trigger conditions.
  - `## Prerequisites` — bullet list, each with a verification command.
  - `## Steps` — numbered, each step naming the command + expected output + a Troubleshooting link if the step has known failure modes.
  - `## Verification` — final-state command + expected output.
  - `## Troubleshooting` — symptom/cause/fix tuples. Folds in any prior "Rollback" or "Anti-patterns" content as troubleshooting entries.
  - `## Related` — cross-refs to runbooks, concepts, rules.
- **Translate bilingual prose to English** (D6). Code samples and command snippets preserved verbatim. Spanish-only proper nouns and identifiers (`Wizarck`, `consumer-d`) remain.
- **Fix legacy dead-link patterns** introduced by Slice 4's `git mv`. Most common: `../docs/concepts/<slug>.md` (legacy path) → `../concepts/<slug>.md` (current path from `docs/runbooks/`). Also drops references to deleted `rfcs/` content.
- **Refresh INDEX.md** to reflect frontmatter-derived summaries (regenerated, not hand-edited; the existing `gen_indexes.py` already drives it).
- **No VERSION bump, no CHANGELOG entry.** Both land in Sub-slice 5.F per user direction 2026-05-19 (target final v0.18.1).

## Impact

- **Consumers**: zero — runbooks are operator-facing reference; no consumer hooks or CI invoke them by path.
- **Schema compliance**: every `docs/runbooks/*.md` validates against `schemas/schema-runbook-v1.json` after this slice. Parallel sub-slices 5.A/5.D/5.E gain a model for their own schema work if needed.
- **Cross-slice contract**: anchor slugs cross-referenced into `docs/concepts/*.md` use the locked 5.B anchors. 5.A and 5.E may cross-link to runbooks via `[Runbook: <slug>](../runbooks/<slug>.md)` — that path shape is stable from this slice forward.
- **Operator cognitive load**: uniform Outcome/Prerequisites/Steps/Verification/Troubleshooting shape means the operator finds the right section in any runbook by name, not by reading.

## Versioning

No VERSION bump. CHANGELOG unchanged. Sub-slice 5.F is the harmonisation pass that bumps to v0.18.1 and writes the unified CHANGELOG entry covering 5.A through 5.F.
