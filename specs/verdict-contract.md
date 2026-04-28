# verdict-contract.md

> **Status**: v1.1.0. ai-playbook v0.7.0 added the `⛔ ARCHITECTURE QUESTIONED` literal as a 4th canonical verdict (§1) for cases where repeated rework reveals a structural design issue rather than an implementation gap. Punctuation note: `⚠️ ISSUES FOUND (iter N)` uses a SPACE between `ISSUES` and `FOUND` (not an underscore) — this is the linter-checked literal.

Every QA-style artefact produced by an agent (code review, readiness check, spec audit, retro) ends
with exactly one **verdict line**, optionally followed by a structured findings list. This contract
is the machine-readable interface between workers and QA, and between parallel review layers (see
[parallel-review.md](parallel-review.md)) and the main agent that triages their output.

---

## 1. Canonical verdicts

Exactly one of the following literal strings MUST appear on its own line in every QA artefact. The
emoji, capitalisation, and spacing are part of the contract and are checked by
`scripts/verdict_lint.py`.

| Verdict literal | Meaning | Next action |
|---|---|---|
| `✅ APPROVED` | Artefact meets intent and all gates; no blocking findings. | Parent agent proceeds. |
| `⚠️ ISSUES FOUND (iter N)` | One or more findings listed; `N` counts rework cycles starting at 1. | Fix, re-submit, increment `N`. |
| `❓ CLARIFICATION NEEDED` | Judgement blocked by ambiguity; worker cannot proceed in good faith. | Halts track; human disambiguates. |
| `⛔ ARCHITECTURE QUESTIONED` | Repeated rework (iter ≥ 2) reveals the structural design is wrong, not the implementation. The worker has tried in good faith and the same class of failure keeps recurring across attempts. | Halts track; an architect-level review (human or `bmad-agent-architect`) re-opens the design (`design.md`, ADR, or upstream spec). The worker does not attempt iter 3. |

Rules:

- The verdict line is the **last line** of the artefact's top-level section (or the last line of the
  JSON `verdict` field for machine-shaped returns — see [agent-contract.md](agent-contract.md)).
- An artefact containing zero or more-than-one verdict literal is **malformed** and rejected by the
  linter with an `error-message-standard.md`-compliant message.
- `N` in `⚠️ ISSUES FOUND (iter N)` is an integer ≥1. Iter 1 is the first pass. See §3 for the
  max-2-rework rule.

## 2. Severity levels

Each finding inside a `⚠️ ISSUES FOUND` artefact MUST declare exactly one severity. `S0` is a
retro-only annotation and never emitted by runtime agents (§2.1).

| Level | Name | Rationale | Blocks progression? |
|---|---|---|---|
| **S1** | Correctness / safety | The change is wrong, unsafe, breaks an invariant, leaks a secret, or corrupts data. | Yes — unconditionally. |
| **S2** | Scope / architecture | In-scope but crosses a boundary defined in `AGENTS.md` hard rules, an ADR, or the OpenSpec proposal (e.g. direct cross-context entity import in a modular monolith). | Yes — unconditionally. |
| **S3** | Style / naming / readability | Code works and is in-scope, but a reader downstream will pay a tax (naming, duplicated helper, missing docstring on a public port). | No — batched. |
| **S4** | Nit / nice-to-have | Subjective polish, speculative refactor, minor typo. | No — batched or ignored. |

Findings shape (prose artefacts):

```
- [S1] <short title>
  Location: <file:line> (or symbolic address)
  Detail:   <one paragraph, WHY the rule fires + FIX>
```

JSON-shaped findings use the schema in [agent-contract.md](agent-contract.md) §4.

### 2.1 S0 — audit-only

`S0` means **"the rule that fired was itself wrong; escalate upstream"**. It is produced only by
retrospectives (see `specs/retrospective-cadence.md` when populated) and only when the retro author
passes `scripts/verdict_lint.py --audit`. An agent emitting `S0` in normal operation is a
`goal_drift` failure (see [agentic-failures.md](agentic-failures.md)) and the linter rejects it.

## 3. Max 2 rework cycles

A QA track runs at most **3 passes** total: the initial review plus **2 rework cycles**. Counting:

- Iter 1 = `⚠️ ISSUES FOUND (iter 1)` after first review.
- Iter 2 = second `⚠️ ISSUES FOUND (iter 2)` after worker's first fix.
- Iter 3 = if QA still finds the **same** S1/S2 finding repeating, the issue is SYSTEMIC. The worker
  DOES NOT attempt a third fix. The track escalates per §4 with one of two literals:
  - `❓ CLARIFICATION NEEDED` — when the spec or the rule is ambiguous and a human can disambiguate.
  - `⛔ ARCHITECTURE QUESTIONED` — when the underlying structural design is wrong and the
    implementation cannot be made to satisfy the spec without revising the design itself
    (the spec is clear; the structural choice that the spec embodies isn't viable).

"Same finding" is identified by the `title` field plus `location` prefix match. If iter 2 introduces
a new S1/S2 not present in iter 1, the counter does not reset — the budget still ends at iter 2 and
the track escalates.

Rationale: further iterations burn tokens on a bad spec or a bad design. Humans break ties on the
spec; architects break ties on the design.

## 4. `❓ CLARIFICATION NEEDED` semantics

When a worker or reviewer emits `❓ CLARIFICATION NEEDED`:

1. The QA artefact MUST include a section `## Question for human` with one concrete question and
   (if applicable) 2–3 candidate answers with trade-offs.
2. Any OpenSpec change whose current artefact resolves to `❓` moves to lifecycle state
   `blocked-by-spec` per [dispatcher-chain.md](dispatcher-chain.md) lifecycle notes.
3. No further work on that track until a human edits the spec or replies. The playbook does not
   allow an agent to "answer its own question" — that pattern is `goal_drift`.

## 4.1 `⛔ ARCHITECTURE QUESTIONED` semantics

When a worker or reviewer emits `⛔ ARCHITECTURE QUESTIONED`:

1. The QA artefact MUST include a section `## Architecture concern` naming:
   - The structural choice in question (cite the ADR or the relevant `design.md` section).
   - The class of failure that keeps recurring (with iter 1 + iter 2 evidence).
   - One concrete proposal for how the design might be re-opened (e.g. "extract X from monolith into
     separate context", "reverse the direction of dependency between A and B").
2. The OpenSpec change moves to lifecycle state `blocked-by-architecture` (a sibling of
   `blocked-by-spec`).
3. Resolution is upstream: a human or `bmad-agent-architect` revises the design / ADR / upstream
   spec, then the change is re-proposed (potentially as a different change ID if scope shifts).
4. The worker does not attempt iter 3 on the same design. Burning a third iteration on a structural
   problem is `goal_drift`.

When to use `⛔` vs `❓`:

- The spec is **ambiguous** (could be interpreted multiple ways) → `❓`.
- The spec is **unambiguous, but the design that satisfies it isn't viable** → `⛔`.

Most tracks never see `⛔`. It is the rare exit when implementation has revealed a planning miss.

## 5. Interaction with break-glass

A verdict of `✅ APPROVED` that was reached only because the worker invoked
`--force-with-reason="<text>"` on a gate (see [break-glass.md](break-glass.md)) MUST carry a
`## Override notice` section citing the exact invocation, the reason string, and the OTel span id
where `ai_playbook.override=true` was emitted. Retros (T14i) flag any un-annotated override.

Break-glass never downgrades S1. An S1 finding cannot be waived; the worker must fix, accept the
block, or escalate to human via `❓`.

## 6. Error phrasing cross-reference

Any error produced alongside or inside a verdict (e.g. "verdict line missing" from the linter, or a
finding's `detail` when it reports a failure) MUST follow the WHY / WHERE / FIX / OVERRIDE shape
from [error-message-standard.md](error-message-standard.md). The linter itself emits its own errors
in that shape.

## 7. Worked examples

### 7.1 Clean approval (0 findings)

```
## Acceptance Auditor report — AC 1..7 (openspec/changes/acme-cart/specs/cart.md)

AC 1 (add item) — covered by `cart.service.spec.ts:42`. ✅
AC 2 (remove item) — covered by `cart.service.spec.ts:71`. ✅
AC 3 (clear cart) — covered by `cart.controller.e2e.ts:118`. ✅
AC 4..7 — all covered, evidence inline above.

Telemetry: bank_id=acme, trace_id=0196f34a-8c7e-7b2f-9d01-3e8a9b4c2f11

✅ APPROVED
```

### 7.2 Mixed severity (1×S1 + 2×S3)

```
## Edge Case Hunter report — diff @ apps/api/src/cart/cart.service.ts

- [S1] Null-pointer on empty cart clear
  Location: apps/api/src/cart/cart.service.ts:83
  Detail: `clearCart(orgId)` dereferences `cart.items[0].id` when the cart has zero rows.
          Repro: POST /cart/clear on a fresh org. FIX: early-return when `items.length === 0`.

- [S3] Repository name drifts from `@consumer-c-legacy/types` Supplier naming
  Location: apps/api/src/cart/cart.repository.ts:18
  Detail: `findVendorById` should be `findSupplierById` to match the shared DTO. No behaviour
          change. FIX: rename method + call sites.

- [S3] Missing @ApiOperation on DELETE /cart/:id
  Location: apps/api/src/cart/cart.controller.ts:54
  Detail: ADR-002 mandates summary + description on every endpoint. Add decorator.

⚠️ ISSUES FOUND (iter 1)
```

### 7.3 Clarification needed

```
## Blind Hunter report — openspec/changes/acme-loyalty/proposal.md

The proposal says "points decay after 365 days of inactivity" and also "points never expire for
Gold-tier customers". The specs/ folder only has one spec `points.md` covering decay. Tasks.md
plans a single code path `decayPoints(orgId)`.

I cannot determine whether Gold-tier accounts should be filtered out inside `decayPoints` or
whether a second path `decayPointsExceptGold` is intended. The two interpretations lead to
materially different RBAC and audit surfaces.

## Question for human

Which path does the proposal intend?
(a) One function; caller-side filter at the cron job layer.
(b) Two functions; the "except Gold" variant is the one wired to the cron.
(c) Gold-tier flag on the customer row, checked inside the single function.

❓ CLARIFICATION NEEDED
```

## 8. CI lint rules — `scripts/verdict_lint.py`

`scripts/verdict_lint.py` is a stub at v0.1.0. When populated (T05 + T09 pre-commit integration) it
will enforce:

1. Exactly one verdict literal in the artefact (§1).
2. If the literal is `⚠️ ISSUES FOUND`, every finding carries a severity token `[S1]`..`[S4]`.
3. `S0` is rejected unless `--audit` was passed on the command line (§2.1).
4. The `iter N` counter is present, `N` is a positive integer, and monotonically increases relative
   to the previous artefact in the same QA track (when run with `--track <id>`).
5. On any violation, the error is emitted in the
   [error-message-standard.md](error-message-standard.md) shape and the process exits non-zero.

Consumers wire the linter into pre-commit (`.pre-commit-config.yaml`) and into their CI for any
path under `**/reviews/*.md`, `**/qa/*.md`, `openspec/changes/*/reviews/*.md`.

## 9. See also

- [parallel-review.md](parallel-review.md) — consumers of this rubric (3 layers).
- [agent-contract.md](agent-contract.md) — machine-shaped envelope carrying the verdict.
- [agentic-failures.md](agentic-failures.md) — `over_confidence` and `premature_completion` are
  the failure modes that attack this contract.
- [break-glass.md](break-glass.md) — the only way `✅ APPROVED` coexists with a failing gate.
- [error-message-standard.md](error-message-standard.md) — error phrasing inside findings.
- [dispatcher-chain.md](dispatcher-chain.md) — `blocked-by-spec` lifecycle state.
