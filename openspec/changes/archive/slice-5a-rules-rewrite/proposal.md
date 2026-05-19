## Why

Slice 4 (v0.18.0) reorganised the filesystem and moved 14 rule docs into `docs/rules/` via `git mv` from the legacy `specs/` tree with no content rewrite. The migrated docs still carry their pre-Slice-4 headers (`# <slug>.md` + `> **Status**: v…`), miss the canonical `rule/v1` frontmatter, and lack the anti-injection sandwich (META prelude + binding clause + restate footer) defined in the Slice 5 plan §"Canonical rule format". Their cross-references point at bare `.md` names (`break-glass.md`, `verdict-contract.md`) that no longer resolve because every rule is now `<slug>.rule.md` and concept docs sit one folder over at `docs/concepts/<slug>.md`. `scripts/validate_pairing.py` runs in lenient mode (skips frontmatter checks), so the corpus passes today by accident.

Slice 5.B (just merged) authored `flagged-for-rule-migration.md` listing 20 passages it deliberately left soft in concept bodies because they belong as binding rules, not reference material. 5.A is the slice that picks them up.

Three concrete problems block downstream work:

1. **No `rule/v1` frontmatter** ⇒ `schemas/schema-rule-v1.json` cannot validate the rule corpus; the disjoint-schema discriminator (D9) is a no-op; `scripts/materialise_cursor_rules.py` (slated in Slice 4) cannot render `.cursor/rules/*.mdc` without the activation / globs / triggers fields.
2. **No anti-injection sandwich** ⇒ OWASP LLM01 + ChatInject countermeasures absent. A user message or tool output can paraphrase a rule as overridden and the LLM may comply. The META prelude + sandwich-defense footer is the explicit defence per Anthropic + IBM neuro-symbolic guidance cited in the plan.
3. **20 normative passages still live in concept bodies** ⇒ 5.B softened them in place (lowercased keywords) so 5.A could extract deterministically. Until 5.A picks them up, they sit in the wrong category.

Sub-slice 5.A runs in parallel with 5.C (runbooks), 5.D (tutorials), and 5.E (new process rules). It owns existing rules; 5.E owns 10 new process rules; 5.F harmonises and bumps VERSION to v0.18.1.

## What Changes

- **Rewrite 14 existing `docs/rules/*.rule.md` to canonical format**. Each gains:
  - `schema: rule/v1` frontmatter validating against `schemas/schema-rule-v1.json` (slug, description, paired_hardrule, activation, status, applies_to, optional break_glass / triggers / globs / last_validated).
  - `## Trigger` clause naming the explicit when-clause and the tools / paths / events it cares about.
  - `## Binding clause` — one RFC 2119 sentence (MUST / MUST NOT / SHOULD / MAY).
  - `## Process supervision` paragraph linking the paired `scripts/rules/<slug>.rule.py` hardrule (or naming the advisory-only condition when `paired_hardrule: null`).
  - `## Examples` with at least one preferred and one avoided concrete case.
  - `> **META**: …` prelude and `> **FOOTER (sandwich defense)**: …` restate-binding-clause line.
  - Body ≤60 lines (≤30 preferred per D7). Oversized legacy content is summarised; full prose moves to `docs/concepts/<slug>.md` companion (when the rule has a sibling concept) or to a `rule-bundle/` directory when the rule is inherently multi-step.
- **Pick up 20 flagged passages** from `openspec/changes/slice-5b-concepts-rewrite/flagged-for-rule-migration.md`. Each is either (a) extracted into a NEW rule doc owned by this slice, (b) rolled into an existing rule, or (c) explicitly deferred to 5.E with a one-line rationale (when the passage belongs to one of the 10 new-process-rule slugs that 5.E owns).
- **Confirm the 6 always-loaded rules** (D16) are present with `activation: always` frontmatter: `verdict-contract`, `output-completeness`, `verification-before-completion`, `error-message-standard`, `apply-skill-enforcement`, `bootstrap-directive`. Gap = author the new rule (most exist already as paired docs).
- **Author `cross-rule-redundancies.md`** in this openspec change folder. Lists every cross-rule overlap (e.g. two rules both invoke "validate exit code 0" on the same artefact, or two rules covering the same paired hardrule from different angles). 5.F dedupes — this slice only flags.
- **Fix broken cross-references**. Today every rule body cites siblings as bare `.md` (`break-glass.md`); the corpus is `<slug>.rule.md` and concepts live one folder over. Each rewrite updates the links to the post-Slice-4 layout: rules cite `[<slug>](<slug>.rule.md)` and concepts as `[<slug>](../concepts/<slug>.md)`.
- **No VERSION bump, no CHANGELOG entry.** Both land in Sub-slice 5.F per user direction 2026-05-19 (target final v0.18.1).

## Impact

- **Consumers**: zero. Rule docs are read by LLMs at session start (when `activation: always`) and by tooling (`validate_pairing.py`, `materialise_cursor_rules.py`). No consumer hooks or CI invoke rule docs by path beyond the `docs/rules/` prefix locked in Slice 4.
- **Schema compliance**: every `docs/rules/*.rule.md` validates against `schemas/schema-rule-v1.json` after this slice. `scripts/validate_pairing.py` continues running in lenient mode (Slice 5.F flips to strict).
- **Anti-injection posture**: every rule carries META prelude + sandwich-defense footer + RFC 2119 binding clause. OWASP LLM01 + ChatInject countermeasures are now in the rule corpus rather than only in the plan.
- **Cross-slice contract**: anchor slugs cited from rule bodies match the locked concept anchors from 5.B. The 5.E new-process-rules slice references this slice's frontmatter shape as the canonical exemplar.
- **Deferred work**: `cross-rule-redundancies.md` lists overlaps; 5.F dedupes after all sub-slices land.

## Versioning

No VERSION bump. CHANGELOG unchanged. Sub-slice 5.F is the harmonisation pass that bumps to v0.18.1 and writes the unified CHANGELOG entry covering 5.A through 5.F.
