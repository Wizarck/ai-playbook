# tasks — slice-5a-rules-rewrite

Sole-consumer scope. Parallel with 5.C (runbooks), 5.D (tutorials), 5.E (new process rules). 5.F harmonises + bumps VERSION.

## 1 Audit current state

- [x] List all `docs/rules/*.rule.md` (14 files).
- [x] Confirm `scripts/rules/<slug>.rule.py` siblings (only `cleanup-zombies.rule.py` exists today; the other 13 will gain hardrules in later slices — frontmatter declares `paired_hardrule:` pointing at the canonical path even if the file does not exist yet — `scripts/validate_pairing.py` warns but does not fail in lenient mode; 5.F will tighten).
- [x] Read `openspec/changes/slice-5b-concepts-rewrite/flagged-for-rule-migration.md` (20 passages).
- [x] Read `docs/concepts/STYLE.md` (authoritative style exemplar from 5.B).
- [x] Read `schemas/schema-rule-v1.json` (disjoint frontmatter schema).

## 2 Rewrite existing rules to canonical format

For each of 14 existing rule docs:

- [x] `apply-fix-contract.rule.md`
- [x] `apply-skill-enforcement.rule.md`
- [x] `bootstrap-directive.rule.md`
- [x] `break-glass.rule.md`
- [x] `cleanup-zombies.rule.md`
- [x] `conflict-resolution-policy.rule.md`
- [x] `cross-slice-additive-extension.rule.md`
- [x] `doc-drift-enforcement.rule.md`
- [x] `error-message-standard.rule.md`
- [x] `hitl-approval-pattern.rule.md`
- [x] `migration-slot-reservation.rule.md`
- [x] `output-completeness.rule.md`
- [x] `verdict-contract.rule.md`
- [x] `verification-before-completion.rule.md`

Each rewrite adds:
- v1 frontmatter passing `schemas/schema-rule-v1.json`
- META instructional-defense prelude
- `## Trigger`, `## Binding clause`, `## Process supervision`, `## Examples`, optional `## Trust boundary`, optional `## Break-glass`
- Sandwich-defense FOOTER restating the binding clause in one line
- Body ≤60 lines (≤30 preferred per D7)
- Cross-references updated to post-Slice-4 paths (`<slug>.rule.md`, `../concepts/<slug>.md`)

## 3 Flagged-passage pickup

Triage the 20 entries in `flagged-for-rule-migration.md`:

- [x] Decide per entry: NEW rule doc / roll into existing / defer to 5.E / out-of-scope with rationale.
- [x] Author NEW rule docs for entries that belong here (advisory-only — `paired_hardrule: null` — for rules whose deterministic L1 hook ships in a later slice). Each new advisory rule is registered in `docs/concepts/enforcement-pairing-exceptions.md`.
- [x] Roll branch-passages into the host rule (e.g. flag #19 → `verdict-contract.rule.md` parallel-review branch).
- [x] Document the deferral pattern in the PR body's "Flagged-passage pickup" table.

## 4 Always-loaded rules verification (D16)

- [x] `verdict-contract.rule.md` — frontmatter `activation: always`
- [x] `output-completeness.rule.md` — frontmatter `activation: always`
- [x] `verification-before-completion.rule.md` — frontmatter `activation: always`
- [x] `error-message-standard.rule.md` — frontmatter `activation: always`
- [x] `apply-skill-enforcement.rule.md` — frontmatter `activation: always`
- [x] `bootstrap-directive.rule.md` — frontmatter `activation: always`

## 5 Cross-rule redundancy report

- [x] Author `openspec/changes/slice-5a-rules-rewrite/cross-rule-redundancies.md` listing overlapping rubrics across the rewritten corpus. 5.F dedupes.

## 6 Pairing-exceptions register update

- [x] For every NEW advisory-only rule (`paired_hardrule: null`), add an entry to the table in `docs/concepts/enforcement-pairing-exceptions.md` naming which of the three conditions applies (#1 non-deterministic / #2 informational / #3 false-positive storm).

## 7 Validate

- [x] `python scripts/check_doc_language.py docs/rules/` — exit 0
- [x] `python scripts/check_link_integrity.py docs/rules/ --strict` — exit 0
- [x] Each rule's frontmatter validates against `schemas/schema-rule-v1.json` (validated via `python -m scripts.validate_pairing --strict`)
- [x] `python scripts/validate_pairing.py` — exit 0 in default lenient mode (strict comes in 5.F)
- [x] `python -m pytest tests/` — green (918 baseline; 2 e2e env-gated skip)
- [x] `python scripts/gen_indexes.py --root docs/rules/` — regenerated INDEX.md

## 8 Commit + push + PR

- [x] Logical commits grouped by category (one for openspec scaffold, then rewrites in groups of 3-5, then flagged-passage pickup, then redundancy report, then INDEX regeneration).
- [x] Push branch `feat/slice-5a-rules-rewrite`.
- [x] Open PR with mandated body sections: Summary / Frontmatter compliance / Always-loaded rules / Flagged-passage pickup / Cross-rule redundancies / Test plan / File-ownership note.
