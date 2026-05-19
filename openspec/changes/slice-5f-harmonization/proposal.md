## Why

Sub-slices 5.B / 5.A / 5.C / 5.D / 5.E shipped 6 PRs over 24 hours rewriting the entire `docs/` tree to the canonical formats locked in Slice 4 (rules, concepts, runbooks, tutorials, new process rules). Five agents wrote in parallel — each followed `docs/concepts/STYLE.md`, but seams remain:

1. **Cross-reference duplication.** `cross-rule-redundancies.md` (authored by 5.A) lists 10 redundancy classes R1–R10 across the rewritten rule corpus; each restates a rubric also present in `break-glass.rule.md` / `error-message-standard.rule.md` / `verdict-contract.rule.md`. The plan called these out for 5.F to dedupe via cross-reference, not by inlining the same MUST clause in 5 rules.
2. **Tone variance at the seams.** Concept docs softened RFC 2119 keywords (5.B); rule docs preserved them. Sub-slices borrowed phrasing across the boundary in a few places — 5.F normalises to STYLE.md.
3. **Lenient-by-default validators.** `validate_pairing.py` and `check_link_integrity.py` shipped lenient defaults during the rewrite window (Slice 4 commit) so legacy content could land. Slice 5 declared the content rewrite complete, so the lenient lifeline can retract — defaults flip to strict.
4. **VERSION not bumped, CHANGELOG entry pending.** 5.B-E intentionally deferred both to 5.F per user direction 2026-05-19 (target final v0.18.1). 5.F composes the unified entry summarising all six sub-slices.

## What Changes

- **Cross-reference dedupe.** Apply each R1–R10 class from `slice-5a-rules-rewrite/cross-rule-redundancies.md`: keep the authoritative rubric in one location, replace the duplicated content elsewhere with a one-line cross-reference. Target: ≥10% reduction in total markdown cross-references across `docs/`.
- **Tone normalisation.** Light editorial pass — no body rewrites. Smooth seams between sub-slices: enforce STYLE.md voice (declarative, present tense), normalise terminology to `taxonomy.md`, keep RFC 2119 keywords inside `docs/rules/` body only (concept bodies stay softened per 5.B).
- **Strict-by-default validators.** Flip `scripts/validate_pairing.py` to strict by default; add `--lenient` opt-in for legacy callers. Same for `scripts/check_link_integrity.py` (with `--warn-only` flag). Adapt the three paired CI workflows (`validate-pairing.rule.yml`, `check-link-integrity.rule.yml`, `check-rule-schemas.rule.yml`) so they invoke the strict-by-default form.
- **Hardrule stub authorship or deferral.** Strict mode surfaces ~25 rules whose `paired_hardrule:` points to a `.py` file not yet on disk. For each: either author a stub (when scope is trivial), or mark `paired_hardrule: null` + `status: advisory` and register the deferral in `enforcement-pairing-exceptions.md` plus `deferred-strict-failures.md`. The 9 stubs shipped by 5.E are the implemented set; the rest are deferred to a future slice that ships them as paired hardrules.
- **AGENTS.md Rule Map.** Regenerate the §2 dispatcher index to mention every rule slug (signal #4 from D3). Stays ≤500 lines per D14.
- **VERSION bump to 0.18.1.** Comprehensive CHANGELOG entry under a single `[0.18.1]` heading summarising every sub-slice with its merged PR number (#67 5.B, #68 5.D, #69 5.E, #70 5.C, #71 5.A, this PR 5.F).

## Impact

- **Consumers**: zero — content shape and slug names are stable from 5.B/A onwards. The strict-by-default validators surface drift faster but the rule corpus is consistent.
- **CI behaviour**: `validate-pairing.rule.yml` and `check-link-integrity.rule.yml` now fail the PR job on drift rather than warning; `check-rule-schemas.rule.yml` validates every rule and concept doc against its disjoint schema.
- **Deferred hardrules**: ~25 rule slugs declare `paired_hardrule: null` for now; the rule corpus stays advisory until a future slice ships the L1 implementations. The deferral is documented in `openspec/changes/slice-5f-harmonization/deferred-strict-failures.md` so the gap is visible.

## Versioning

VERSION bumps 0.18.0 → **0.18.1**. Aligns with user-refined versioning 2026-05-19: Slices 4–7 use v0.18.x; v0.19.x reserved for post-review fix iterations; v0.20.0 final cut on explicit user approval. Slice 5 (PR ranges #67–#71 + this PR) closes with v0.18.1.
