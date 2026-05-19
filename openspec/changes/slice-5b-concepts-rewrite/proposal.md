## Why

Slice 4 (v0.18.0) reorganised the filesystem and authored 4 stub concept docs (`enforcement-layers.md`, `cross-llm-activation.md`, `enforcement-pairing-exceptions.md`, `taxonomy.md`) plus an authoritative `STYLE.md` placeholder. The remaining ~53 concept docs were migrated under `docs/concepts/` via `git mv` from the legacy `specs/` tree with no content rewrite — they still carry their pre-Slice-4 headers (`# filename.md` + `> **Status**: v1.0.0`) and lack the canonical `concept/v1` frontmatter that `schemas/schema-concept-v1.json` defines.

Three concrete problems block the next slices:

1. **No frontmatter** ⇒ `schemas/schema-concept-v1.json` cannot validate the corpus; `scripts/validate_pairing.py` cannot distinguish concept docs from rule docs by schema (only by path); `gen_indexes.py` cannot enumerate titles or summaries.
2. **Mixed RFC 2119 vocabulary** ⇒ Decision D4 mandates the rules/concepts discriminator: rules use `MUST`/`SHOULD`/`MAY`; concepts use declarative voice. 36 of 57 concept docs carry stray RFC 2119 keywords inherited from their old spec contracts. Some genuinely belong as rules (`docs/rules/<slug>.rule.md`) and need to be flagged for Slice 5.A pickup.
3. **Anchor names not locked** ⇒ Sub-slices 5.A (rules), 5.C (runbooks), 5.D (tutorials), 5.E (process rules) will cross-reference concept docs via `#<slug>` anchors. Until those slugs are fixed in frontmatter, the parallel rewrites cannot cite them deterministically.

Sub-slice 5.B runs **first** in the Slice 5 fan-out so its anchor lock and discriminator decisions are inputs to 5.A/C/D/E. Sub-slice 5.F (sequential harmonisation, runs last) bumps VERSION to v0.18.1 and composes the unified CHANGELOG entry covering all 6 sub-slices.

## What Changes

- **Refine `docs/concepts/STYLE.md`** from Slice-4 placeholder to the authoritative writing-style exemplar (≤30 lines) that 5.A/C/D/E read. Adds the anchor convention, the RFC-2119 ban for concept-doc bodies, the canonical section structure (`## Why`, `## What`, `## How it relates to other concepts`, `## Concrete example`).
- **Replace placeholder bodies** in 4 Slice-4 stubs with real content:
  - `enforcement-layers.md` — L1/L2/L3 architecture, paired enforcement, D8 tie-break protocol
  - `cross-llm-activation.md` — Cursor 4-mode mapping per LLM, D11 + D20 degradation matrix
  - `enforcement-pairing-exceptions.md` — when `paired_hardrule: null` is allowed, audit-trail conventions
  - `taxonomy.md` — alphabetical glossary refactor (existing content was a numbered category list, rewritten as flat alphabetical ≤80 entries)
- **Inject v1 frontmatter** into all remaining 53 concept docs (currently bare `# filename.md` headings). Frontmatter validates against `schemas/schema-concept-v1.json`: `schema: concept/v1`, `slug:` matches filename stem, `title:` extracted from H1 or first sentence, optional `summary:`.
- **Soften RFC 2119 vocabulary** in concept-doc bodies. `MUST` → `must`/`is required to`/`requires`; `SHOULD` → `should`/`is recommended`; `MAY` → `may`/`can`. Code fences and quoted spec excerpts are preserved verbatim.
- **Author `flagged-for-rule-migration.md`** in this openspec change folder. Lists every passage where the normative intent genuinely belongs as a `docs/rules/<slug>.rule.md` rule (not just RFC-2119 vocabulary noise). Slice 5.A consumes this list. Format: source path + section + 1-line rationale + suggested target rule filename.
- **No VERSION bump, no CHANGELOG entry.** Both land in Sub-slice 5.F per user direction 2026-05-19 (target final v0.18.1).

## Impact

- **Consumers**: zero — concept docs are reference material; no consumer hooks or CI invoke them by path other than via the `docs/` prefix already locked in Slice 4.
- **Schema compliance**: every `docs/concepts/*.md` validates against `schemas/schema-concept-v1.json` after this slice. `scripts/validate_pairing.py` can now use the schema as the rule-vs-concept discriminator (D4 + D9), not just folder path.
- **Cross-slice contract**: anchor slugs locked in this PR are stable inputs for 5.A/C/D/E. Renames after this slice merges break those parallel branches.
- **Rule corpus seed**: `flagged-for-rule-migration.md` becomes 5.A's input queue. Net effect: concept docs slim down (normative passages move out); rule docs gain real content (instead of being authored from scratch).

## Versioning

No VERSION bump. CHANGELOG unchanged. Sub-slice 5.F is the harmonisation pass that bumps to v0.18.1 and writes the unified CHANGELOG entry covering 5.A through 5.F.
