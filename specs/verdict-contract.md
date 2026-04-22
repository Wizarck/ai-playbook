# verdict-contract.md

> **Status**: stub, v0.1.0. Populated in **T05** alongside parallel-review discipline and agentic failure catalog.

## Verdict rubric (canonical)

Every QA-style artifact (review, readiness check, spec audit) resolves to exactly one:

- `✅ APPROVED` — meets intent and gates; ready to proceed.
- `⚠️ ISSUES FOUND (iter N)` — concrete blockers listed with severity. `N` tracks rework cycles.
- `❓ CLARIFICATION NEEDED` — ambiguity blocks judgement; work stops until the human disambiguates.

## Severity

| Level | Meaning | Blocks? |
|---|---|---|
| S1 | Correctness / safety defect. | Yes. |
| S2 | Scope / architecture violation. | Yes. |
| S3 | Style, naming, readability. | No, batched. |
| S4 | Nit, nice-to-have. | No. |

S1 and S2 block progression. S3/S4 are batched for a later cleanup commit.

## S0 override

`S0` exists as an **audit-only** marker for "rule itself was wrong; propagating change upstream". Never used by agents; only by retros.

## Max rework cycles

Two. If the same issue recurs across three QA passes, the failure is SYSTEMIC and escalates to human — further iterations are burning cycles on a bad spec.

## Populated in T05

Full worked examples, CI lint rules (`verdict_lint.py` in `scripts/`), and interaction with parallel review layers (Blind Hunter / Edge Case Hunter / Acceptance Auditor).
