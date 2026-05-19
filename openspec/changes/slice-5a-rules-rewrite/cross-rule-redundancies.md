# Cross-rule redundancies — slice-5a-rules-rewrite

> Authored by Sub-slice 5.A (rules rewrite). Each entry lists overlapping rubrics across the rewritten rule corpus that 5.F dedupes during the harmonisation pass. The aim of this report is to flag, not resolve — 5.F will decide between consolidation, cross-reference, or accepted-overlap.

Format per entry: rubric / rules involved / nature of overlap / proposed resolution path (5.F decides).

---

## R1 — Override / break-glass rubric

- **Rules involved**: `break-glass`, `cleanup-zombies`, `apply-skill-enforcement`, `apply-fix-contract`, `doc-drift-enforcement`.
- **Overlap**: each carries a `## Break-glass` section that names a different `AIPLAYBOOK_*_SKIP` env var. The five sections re-state the contract verbs (≥10-char reason, audit append, banner) at varying levels of detail; `break-glass.rule.md` is the canonical full statement.
- **Nature**: not redundancy per se — each rule needs to name its own env var. But the contract verbs are restated in 5 places.
- **5.F resolution**: keep the per-rule `## Break-glass` paragraph (≤4 lines naming the env var + audit destination); replace the contract restatement with a 1-line "Per [break-glass](break-glass.rule.md)" pointer.

## R2 — Verdict literal handling

- **Rules involved**: `verdict-contract`, `output-completeness`, `verification-before-completion`, `apply-skill-enforcement` (the canonical block message references the `❓` literal indirectly via [error-message-standard]).
- **Overlap**: `output-completeness` and `verification-before-completion` both describe when `✅ APPROVED` is emit-able / forbidden. The first says "complete or halt"; the second says "verified or halt". Both gate the same literal.
- **Nature**: complementary — output-completeness is about the artefact's content; verification-before-completion is about the proof. They guard different failure modes (`over_confidence` from premature claim vs `goal_drift` from unverified claim).
- **5.F resolution**: keep both; consider adding a cross-reference table to `verdict-contract.rule.md` listing the two preconditions for `✅ APPROVED`.

## R3 — Error-shape rubric

- **Rules involved**: `error-message-standard`, `doc-drift-enforcement`, `apply-skill-enforcement`, `cleanup-zombies`.
- **Overlap**: doc-drift-enforcement and apply-skill-enforcement both name their canonical block messages "per error-message-standard.md shape". Each restates the WHY/WHERE/FIX/OVERRIDE form inline (~10 lines per rule).
- **Nature**: the inline restatement is the message body, not a contract paraphrase — it's load-bearing literal text the L3 gate emits.
- **5.F resolution**: keep the per-rule canonical block message verbatim; do NOT extract to a shared snippet (the message MUST be discoverable inside the rule that emits it).

## R4 — Frontmatter "globs" + "triggers" disjointness

- **Rules involved**: `cleanup-zombies`, `doc-drift-enforcement`, `pr-tracker-reference`, `alembic-migration-naming`, `notification-level-declared`, `notification-no-secrets`, `notification-channel-adapter`, `agentic-failure-catalog-schema` (all rules with `activation: auto` and `globs:`).
- **Overlap**: rules with `activation: auto` declare `globs:` to scope the L1 hook. Several of them ALSO declare `triggers: [Bash, PostToolUse]` etc. (D10 hook-dispatcher routing).
- **Nature**: not redundancy — globs scope file matching, triggers scope tool events. Both are necessary frontmatter fields.
- **5.F resolution**: no action needed; document the orthogonality in `docs/concepts/cross-llm-activation.md` if not already clear.

## R5 — AI-reviewer / auto-merge / delegated-shipping triad

- **Rules involved**: `ai-reviewer-signoff`, `auto-merge-discipline`, `delegated-shipping-prompt`.
- **Overlap**: all three reference §4.5 of `release-management.md`. ai-reviewer-signoff defines the §4.5.3 markers; auto-merge-discipline gates on their presence; delegated-shipping-prompt embeds them verbatim in spawn envelopes.
- **Nature**: complementary — three different surfaces (PR body, merge button, subagent spawn) all consume the same §4.5.3 contract.
- **5.F resolution**: consider adding a "Three-rule contract" diagram to `docs/concepts/release-management.md` §4.5 showing how the three rules interact.

## R6 — Slot reservation + Alembic naming + cross-slice additive

- **Rules involved**: `migration-slot-reservation`, `alembic-migration-naming`, `cross-slice-additive-extension`.
- **Overlap**: alembic-migration-naming asserts `revision = "<NNNN>_<topic>"` where `<NNNN>` is reserved per migration-slot-reservation. cross-slice-additive-extension uses migration-slot-reservation for slot claims. Three rules covering one logical workflow (claim slot → name revision → ship additive migration).
- **Nature**: complementary chain; each rule covers a discrete step.
- **5.F resolution**: keep the three rules; consider a bundle (`rule_bundle: migrations`) per D7 if a future slice adds a fourth migration-related rule.

## R7 — Notification rule trio

- **Rules involved**: `notification-level-declared`, `notification-no-secrets`, `notification-channel-adapter`.
- **Overlap**: three rules cover the same `scripts/notifications/` subsystem. Level + secrets are payload rules; channel-adapter is the consumer.
- **Nature**: complementary; each guards a different invariant.
- **5.F resolution**: same as R6 — consider a `rule_bundle: notifications` if a fourth notification rule lands.

## R8 — Parallel-wave / conflict-resolution / anti-collision

- **Rules involved**: `conflict-resolution-policy`, `parallel-wave-anti-collision`.
- **Overlap**: parallel-wave-anti-collision is essentially a Wave-N specialisation of conflict-resolution-policy §5. Both are advisory-only (`paired_hardrule: null`).
- **Nature**: parallel-wave covers Gate-C declaration; conflict-resolution covers runtime resolution.
- **5.F resolution**: keep both; consider whether parallel-wave-anti-collision could be absorbed as a subsection of conflict-resolution-policy (probably no — different trigger time: proposal vs PR).

## R9 — Subagent envelope vs delegated shipping prompt

- **Rules involved**: `subagent-envelope-schema`, `delegated-shipping-prompt`.
- **Overlap**: delegated-shipping-prompt is a specialisation of subagent-envelope-schema for the shipping-subagent case. Both validate the spawn envelope.
- **Nature**: nested — subagent-envelope-schema is the generic contract; delegated-shipping-prompt is the specialisation with the §4.5.3 verbatim requirement.
- **5.F resolution**: keep both; delegated-shipping-prompt cross-references subagent-envelope-schema; the special-case rule pulls its weight.

## R10 — Verdict-contract parallel-review branch

- **Rules involved**: `verdict-contract` (parallel-review branch).
- **Overlap**: flag #19 from 5.B (parallel-review dismissal rationale) was rolled into `verdict-contract.rule.md`. The wording references `parallel-review.md` §3 / §X.
- **Nature**: in-rule branch; not cross-rule.
- **5.F resolution**: confirm the rolled-in clause references the locked `parallel-review.md` anchors from 5.B; no further action.

---

## Open items for 5.F

- Verify every rule citing `release-management.md` §4.5 / §6.x uses the locked anchors from 5.B.
- Confirm the `rule_bundle:` field is well-typed by `schemas/schema-rule-v1.json` (it is — see schema line 84) and decide whether to introduce bundles for `migrations` (R6) and `notifications` (R7).
- Decide consolidation strategy for R1 (break-glass restatement) — pointer-only vs per-rule paragraph.
