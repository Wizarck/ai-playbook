# Tasks — slice-5e-new-process-rules

## Step 0 — branch + scaffold

- [x] Branch `feat/slice-5e-new-process-rules` cut from `main` (post-5B).
- [x] `openspec/changes/slice-5e-new-process-rules/` created with `proposal.md`, `tasks.md`, `design.md`.

## Step 1 — write 10 new rules (docs/rules/)

Each rule follows the canonical v1 format from the plan §"Canonical rule format":
- frontmatter: `schema: rule/v1` + `slug` + `description` + `paired_hardrule` + `activation` + `status` (+ optional `applies_to`, `globs`, `triggers`, `break_glass`, `last_validated`)
- body ≤60 lines, ≤30 preferred (D7)
- sections: H1 title, META block, `## Trigger`, `## Binding clause`, optional `## Trust boundary`, optional `## Process supervision`, `## Examples`, optional `## Break-glass`, sandwich-defense FOOTER

- [ ] `docs/rules/install-playbook.rule.md`
- [ ] `docs/rules/update-playbook.rule.md`
- [ ] `docs/rules/cleanup-on-bump.rule.md`
- [ ] `docs/rules/update-documentation.rule.md`
- [ ] `docs/rules/openspec-apply-enforcement.rule.md`
- [ ] `docs/rules/gemini-session-start.rule.md`
- [ ] `docs/rules/data-handling.rule.md`
- [ ] `docs/rules/secrets-handling.rule.md`
- [ ] `docs/rules/english-only-docs.rule.md`
- [ ] `docs/rules/link-integrity.rule.md`

## Step 2 — stub paired hardrule scripts

For each rule with non-null `paired_hardrule`, create `scripts/rules/<slug>.rule.py` (≤50 LOC scaffold, `validate` subcommand, exit 0/1/2 policy).

- [ ] `scripts/rules/install-playbook.rule.py`
- [ ] `scripts/rules/update-playbook.rule.py`
- [ ] `scripts/rules/cleanup-on-bump.rule.py`
- [ ] `scripts/rules/update-documentation.rule.py`
- [ ] `scripts/rules/openspec-apply-enforcement.rule.py`
- [ ] `scripts/rules/gemini-session-start.rule.py`
- [ ] `scripts/rules/secrets-handling.rule.py`
- [ ] `scripts/rules/english-only-docs.rule.py`
- [ ] `scripts/rules/link-integrity.rule.py`

`data-handling` has `paired_hardrule: null` (advisory) — no script.

## Step 3 — integration tests

- [ ] `tests/integration/test_rule_interactions.py` authored with ≥5 scenarios:
  1. break-glass + verdict-contract interaction
  2. output-completeness + verification-before-completion interaction
  3. english-only-docs + link-integrity (joint docs/ lint)
  4. secrets-handling + data-handling (orthogonal privacy invariants)
  5. openspec-apply-enforcement + verdict-contract (apply marker absence)

## Step 4 — extend rules index

- [ ] `python scripts/gen_indexes.py --root docs/rules/` regenerates INDEX.md (or manual edit) with the 10 new entries.

## Step 5 — validation

- [ ] `python scripts/check_doc_language.py docs/rules/` → exit 0
- [ ] `python scripts/check_link_integrity.py docs/rules/` → exit 0
- [ ] Every new `docs/rules/*.rule.md` validates against `schemas/schema-rule-v1.json`
- [ ] `python scripts/validate_pairing.py` → exit 0 (default lenient)
- [ ] `pytest tests/integration/test_rule_interactions.py -v` → all green
- [ ] `pytest tests/` → no regressions
- [ ] `VERSION` unchanged, `CHANGELOG.md` unchanged

## Step 6 — PR

- [ ] Commit + push `feat/slice-5e-new-process-rules`
- [ ] `gh pr create --base main --title "docs(5e): 10 new process rules + integration tests [no-doc-impact]"`
- [ ] CI green expected
