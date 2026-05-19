# Tasks — slice-5f-harmonization

## 1. Cross-reference dedupe

- [x] 1.1 R1 break-glass restatement: keep canonical clause in `break-glass.rule.md`; replace contract restatement in `cleanup-zombies.rule.md`, `apply-skill-enforcement.rule.md`, `apply-fix-contract.rule.md`, `doc-drift-enforcement.rule.md` with a one-line pointer.
- [x] 1.2 R2 verdict literal: cross-reference `verdict-contract.rule.md` from `output-completeness.rule.md` and `verification-before-completion.rule.md` (preconditions for `✅ APPROVED`).
- [x] 1.3 R3 error-shape: keep per-rule canonical block messages verbatim (load-bearing literal); confirm each cites `error-message-standard.rule.md` once.
- [x] 1.4 R4/R6/R7/R8 acknowledged complementary, no edits required.
- [x] 1.5 R5/R9 add cross-reference where appropriate.
- [x] 1.6 R10 confirm parallel-review branch in `verdict-contract.rule.md` references the locked anchor names from 5.B.
- [x] 1.7 Audit dead anchors against `flagged-for-rule-migration.md` (5.B output).

## 2. Tone normalisation

- [x] 2.1 Skim each `docs/concepts/*.md` for stray RFC 2119 keywords missed by 5.B's softening script.
- [x] 2.2 Skim each `docs/rules/*.rule.md` for declarative voice in non-binding-clause prose.
- [x] 2.3 Skim each `docs/runbooks/*.md` for imperative voice (Diátaxis how-to).
- [x] 2.4 Skim each `docs/tutorials/*.md` for learning-oriented voice (Diátaxis tutorial).
- [x] 2.5 Spot-check terminology against `taxonomy.md`.

## 3. Strict-by-default validators

- [x] 3.1 `scripts/validate_pairing.py`: flip default; add `--lenient` flag.
- [x] 3.2 `scripts/check_link_integrity.py`: flip default; add `--warn-only` flag.
- [x] 3.3 `.github/workflows/validate-pairing.rule.yml`: confirm strict invocation.
- [x] 3.4 `.github/workflows/check-link-integrity.rule.yml`: confirm strict invocation.
- [x] 3.5 `.github/workflows/check-rule-schemas.rule.yml`: confirm strict invocation.
- [x] 3.6 Update `tests/test_validate_pairing.py` for new default.
- [x] 3.7 Update `tests/test_check_link_integrity.py` for new default.

## 4. Hardrule deferral / stub authorship

- [x] 4.1 Enumerate rules whose `paired_hardrule:` points to a `.py` not yet on disk.
- [x] 4.2 For each: mark `paired_hardrule: null` + `status: advisory`, OR author a ≤50-LOC stub.
- [x] 4.3 Register every advisory rule in `docs/concepts/enforcement-pairing-exceptions.md` table.
- [x] 4.4 Author `openspec/changes/slice-5f-harmonization/deferred-strict-failures.md` listing every deferral and the future slice expected to ship the hardrule.

## 5. AGENTS.md Rule Map

- [x] 5.1 Add a `## Rule Map` section listing every `docs/rules/<slug>.rule.md` slug, grouped by status (enforced / advisory).
- [x] 5.2 Verify line count ≤500.

## 6. Dead-link fixes

- [x] 6.1 Fix `docs/index.md` references to legacy paths (development-flow, start-here, quickstart, etc.) to point at the new `docs/concepts/` and `docs/tutorials/` locations.
- [x] 6.2 Fix concept docs referencing pre-rename tutorial paths (`04-quickstart-lessons.md`, `07-fork-inventory.md`).

## 7. Compliance lints

- [x] 7.1 `python -m scripts.check_doc_language docs/` → exit 0.
- [x] 7.2 `python -m scripts.check_link_integrity docs/` (new strict default) → exit 0.
- [x] 7.3 `python -m scripts.check_agents_md_size` → exit 0.
- [x] 7.4 `python -m scripts.validate_pairing` (new strict default) → exit 0.
- [x] 7.5 `python scripts/rules/cleanup-zombies.rule.py validate` → exit 0.

## 8. Release

- [x] 8.1 Bump `VERSION` to 0.18.1.
- [x] 8.2 Compose comprehensive CHANGELOG entry covering 5.B/5.A/5.C/5.D/5.E/5.F with PR refs.
- [x] 8.3 `pytest tests/` → green (≥925 baseline + new tests).
- [x] 8.4 Open PR with full body per acceptance criteria.
