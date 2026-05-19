## Why

Slice 4 (v0.18.0) reorganised the filesystem and Slice 5.B (sequential, runs first) locked concept-doc anchors. The 10 process invariants enumerated in the v9 plan §"Slice 5.E" are NOT yet authored — they only existed as future-work entries. Without them, consumers cannot bootstrap the playbook submodule deterministically, post-bump cleanup has no rule citing it, ENGLISH-only docs and link-integrity lints have no normative anchor, and `secrets-handling` / `data-handling` have no canonical reference.

Three concrete problems block downstream work:

1. **No canonical bootstrap path** — consumers wire the submodule by reading scattered prose in `bootstrap-directive.rule.md`. No standalone rule covers `install-playbook` (initial wire) or `update-playbook` (pin bump) as discrete operations with their own paired hardrules.
2. **No paired enforcement docs for new tooling** — `scripts/check_doc_language.py`, `scripts/check_link_integrity.py`, `scripts/secrets_scan.py`, `scripts/gemini_start.py`, `scripts/openspec_apply_marker.py` exist as scripts but have no `docs/rules/<slug>.rule.md` paired contract. Slice 5.E adds the missing paired docs (5 of the 10 rules pair to existing scripts; 5 add new stub scripts).
3. **No cross-rule integration tests** — when two rules interact (break-glass + verdict-contract, output-completeness + verification-before-completion), nothing asserts the verdicts compose consistently. Plan §"Slice 5.E" mandates `tests/integration/test_rule_interactions.py` with ≥5 scenarios.

Sub-slice 5.E runs in parallel with 5.A (existing rules rewrite), 5.C (runbooks), 5.D (tutorials) after 5.B locks anchors. Sub-slice 5.F (sequential harmonisation, runs last) bumps VERSION to v0.18.1 and composes the unified CHANGELOG entry covering all 6 sub-slices.

## What Changes

- **Author 10 new process rules** under `docs/rules/<slug>.rule.md` following the canonical v1 format (`schema: rule/v1` frontmatter, META + sandwich-defense body, ≤60 lines per D7):
  - `install-playbook.rule.md` — consumer bootstrap of `.ai-playbook` submodule
  - `update-playbook.rule.md` — bumping the submodule pin (paired with `_bumper.py`)
  - `cleanup-on-bump.rule.md` — running `cleanup_zombies.py --apply` post-bump (paired hardrule)
  - `update-documentation.rule.md` — co-edit-pairs enforcement (paired with `check_doc_drift.py`)
  - `openspec-apply-enforcement.rule.md` — apply skill marker contract (paired with `openspec_apply_marker.py`)
  - `gemini-session-start.rule.md` — Gemini CLI wrapper invocation contract (paired with `gemini_start.py`)
  - `data-handling.rule.md` — no PII in logs, hash session_ids (advisory pending Slice 6 telemetry pipeline)
  - `secrets-handling.rule.md` — SOPS/.env.local strategy (paired with `secrets_scan.py`)
  - `english-only-docs.rule.md` — all docs/ in English (paired with `check_doc_language.py`)
  - `link-integrity.rule.md` — no dead links under docs/ (paired with `check_link_integrity.py`)
- **Stub 5 new paired_hardrule scripts** under `scripts/rules/<slug>.rule.py` for rules whose paired script does not yet exist (`install-playbook`, `update-playbook`, `cleanup-on-bump`, `update-documentation`, `openspec-apply-enforcement`, `gemini-session-start`). Each ≤50 LOC scaffold with a `validate` subcommand and the canonical exit-code policy (0 = pass, 1 = block, 2 = schema break / fatal).
- **Author `tests/integration/test_rule_interactions.py`** with ≥5 cross-rule scenarios:
  1. `break-glass` + `verdict-contract` — verdict-contract verdicts NOT overridable by break-glass
  2. `output-completeness` + `verification-before-completion` — joint completion gate
  3. `english-only-docs` + `link-integrity` — both lint the same docs/ corpus without conflict
  4. `secrets-handling` + `data-handling` — orthogonal but additive privacy invariants
  5. `openspec-apply-enforcement` + `verdict-contract` — apply-marker absence triggers verdict warning
- **Extend `docs/rules/INDEX.md`** with the 10 new entries (run `scripts/gen_indexes.py` to auto-regenerate).
- **No VERSION bump, no CHANGELOG entry.** Both land in Sub-slice 5.F per user direction 2026-05-19 (target final v0.18.1).

## Impact

- **Consumers**: zero — rules are loaded as context by LLMs; no consumer hooks invoke the new rule files by path other than via `docs/rules/` already locked in Slice 4.
- **Schema compliance**: every new `docs/rules/*.rule.md` validates against `schemas/schema-rule-v1.json`.
- **Pairing invariant**: `scripts/validate_pairing.py` (default lenient) passes; 9 of 10 rules have non-null `paired_hardrule`; `data-handling` is advisory (`paired_hardrule: null`) pending Slice 6.
- **Test surface**: 1 new integration test file with ≥5 scenarios. Existing unit tests (`tests/test_*.py`) untouched.
- **Cross-slice contract**: rule slugs locked in this PR are stable inputs for 5.F harmonisation. Renames after this slice merges break that pass.

## Versioning

No VERSION bump. CHANGELOG unchanged. Sub-slice 5.F is the harmonisation pass that bumps to v0.18.1 and writes the unified CHANGELOG entry covering 5.A through 5.F.
