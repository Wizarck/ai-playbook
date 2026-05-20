---
schema: concept/v1
slug: enforcement-pairing-exceptions
title: Pairing exceptions — advisory-only rules
summary: |
  Most ai-playbook rules carry a paired L1 hardrule. A handful do not —
  they declare paired_hardrule null and rely on L2 + L3 only. This doc
  defines when that exception is legitimate and how the audit trail works.
last_validated: "2026-05-20"
---

# Enforcement pairing exceptions

## Why

The pairing invariant (every L1 hook has an L2 doc and vice versa) is the backbone of the three-layer enforcement architecture described in `enforcement-layers.md`. But three real-world cases break it:

1. The rubric is non-deterministic and resists a Python check (judgement on prose tone, on a code-style nuance, on intent).
2. The rule is informational rather than enforced (a list of approved technologies, a routing table read by humans).
3. A Python hook would fire on so many normal edits that the false-positive storm degrades developer trust faster than the rule's enforcement gain warrants.

Without an explicit escape hatch, authors either invent fragile hooks that get disabled in the first incident, or skip writing the rule altogether. Both outcomes are worse than an honest advisory-only rule with documented justification.

## What

A rule may declare `paired_hardrule: null` in its frontmatter only when one of four conditions holds:

1. **No deterministic L1 check exists.** Example: "tone of voice in user-facing error messages" — needs human or LLM judgement.
2. **The rule is purely informational.** Example: a doc listing approved technologies — no per-edit enforcement applicable.
3. **Consumer-side surface.** Example: a rule that names a directory (`scripts/notifications/`, `langgraph-aiops/`) that lives only in consumers, not in the playbook tree. A playbook-side hardrule would have nothing to validate locally; consumers may mirror the contract under their own `scripts/rules/`.
4. **The hook would produce a false-positive storm.** Example: a rule that fires on every line of code; an L3 PR-time check at the diff level is the correct cadence.

The validator (`scripts/validate_pairing.py --strict`) enforces three follow-on invariants:

- Every advisory-only rule has an entry in the table below.
- The entry names which of the three conditions applies.
- The rule's L2 doc body explicitly states "L1 enforcement: advisory-only" so the LLM reading it knows the rubric is not testable by a hook.

The frontmatter shape:

```yaml
schema: rule/v1
slug: <slug>
paired_hardrule: null
activation: ...
status: advisory   # status is not enforced; the rule is documented but unenforced
```

## How it relates to other concepts

- The full three-layer model is described in `enforcement-layers.md`. `paired_hardrule: null` removes the L1 layer; L2 (markdown rule) and L3 (CI gate, if any) still apply.
- Schema disjointness (D9) requires every `docs/rules/*.rule.md` to carry `paired_hardrule:` as a field — `null` is a valid value, the field is not absent.
- Per-LLM degradation from `cross-llm-activation.md` is sharper for advisory-only rules: with no L1 hook to fall back on, the rule depends entirely on L2 loading correctly. Gemini's narrower activation framework matters more here.

## Concrete example

Hypothetical rule `error-message-tone`: every user-facing error string should be concise, blameless, and actionable. There is no Python regex that distinguishes a blameless message from a blame-y one. The rule lives at `docs/rules/error-message-tone.rule.md` with:

```yaml
schema: rule/v1
slug: error-message-tone
paired_hardrule: null
activation: agent       # loaded by LLM when editing error strings
status: advisory
```

Its body explains the rubric in prose, gives preferred / avoided examples, and includes the line "L1 enforcement: advisory-only — see enforcement-pairing-exceptions.md condition #1". The table below carries an entry naming condition #1.

## Pairing-exception register

| Rule slug | Condition | Rationale |
|---|---|---|
| `conflict-resolution-policy` | #1 (non-deterministic) | Conflict-tier classification (T1 / T2 / T3 / T4) requires judgment of intent; no Python check distinguishes "overlapping lines with disjoint intent" from "overlapping lines with combinable intent". Reviewer-driven; persistent ad-hoc resolutions surface in the monthly retro. |
| `verify-existing-patterns` | #1 (non-deterministic) | "Did the agent substantively read `docs/concepts/INDEX.md` and `docs/rules/` before proposing new infra?" requires prose inference of semantic overlap between the proposal and existing artefacts; no Python check distinguishes a substantive read from a token-counting glance, and a hook firing on every "let's add" phrase would produce a false-positive storm. Reviewer-enforced via `❓ CLARIFICATION NEEDED` on proposals lacking an in-message verification footprint. |
| `parallel-wave-anti-collision` | #1 (non-deterministic) | Wave-N anti-collision contract is enforced socially via the `docs/openspec-slice.md` "Anti-collision contract" section plus reviewer discipline. A grep-style L1 could surface drift but cannot judge whether two slices' touch-lists are genuinely disjoint or only superficially so. |
| `slice-preflight` | #2 (informational) | Records the preflight checklist any slice must satisfy before the first task commit. The individual checks are already L1-enforced by the underlying skills (apply-skill-enforcement, validate_pairing, openspec_validate); this rule's value is the assembled checklist, not a new enforcement layer. |
| `parallel-review-verdict-dismissal` | #2 (informational) | Documents the verdict-contract branch for parallel-review aggregation. The verdict literals themselves are paired-hardrule-checked in `verdict-contract.rule.md`; this entry exists for discoverability when triaging a dismissed reviewer verdict. |
| `data-handling` | #2 (informational) | PII-hashing contract for telemetry / hook persistence layers. The deterministic check ships inside `scripts/telemetry/anonymize.py`; the rule documents the contract that anonymizer enforces. Listed here because the rule itself carries `paired_hardrule: null` even though the hashing logic is testable downstream. |
| `notification-channel-adapter` | #3 (consumer-side surface) | Channel adapters live under each consumer's own `scripts/notifications/` — Slack / PagerDuty / SMTP / etc. wiring is project-specific. A playbook-side hardrule would have nothing to validate locally. Consumers MAY mirror the contract under their own `scripts/rules/`. |
| `notification-level-declared` | #3 (consumer-side surface) | `notify.send()` and the channel adapters live consumer-side; the playbook does not ship a runtime notify package. The contract is enforced at the consumer's emit-time. |
| `notification-no-secrets` | #3 (consumer-side surface) | Same as the adapter rule — the scan chokepoint runs inside the consumer's `notify.send()`. The playbook's `scripts/secrets_scan.py` remains the canonical scanner, but the integration point is downstream. |
| `apply-fix-contract` | #3 (consumer-side surface) | The `langgraph-aiops/` workflow surface and the `hitl.request_approval` runtime live in consumer projects (e.g. consumer-a-core, tenant-b). A playbook-side hardrule would only see references that do not resolve in this tree. |
| `hitl-approval-pattern` | #3 (consumer-side surface) | The mutation-class DTOs, channel adapters, and `approval_decisions` schema live in single-operator AI systems consuming the playbook (broker / prod-deploy / secret-rotation surfaces are project-specific). |

Slice 5.A added the first four entries (one for the existing `conflict-resolution-policy` and three for new advisory rules picked up from `flagged-for-rule-migration.md`). Slice 5.F added `data-handling` after strict-mode validation surfaced the missing register row. Slice 7 added condition #3 (consumer-side surface) and five entries (notification trio, apply-fix-contract, hitl-approval-pattern) after the showcase pass surfaced that those rules document contracts whose runtime lives entirely downstream of the playbook.

## Further reading

- `enforcement-layers.md` — full three-layer model.
- `enforcement-status.md` — live status of the rule corpus, including which rules are enforced vs advisory.
- D9 (disjoint rule / concept schemas) — Slice-5 plan decisions doc.
