# verification-before-completion.md

> **Status**: v1.0.0. New in ai-playbook v0.7.0. Cross-cutting iron law for any agent emitting `✅ APPROVED` per [verdict-contract.md](verdict-contract.md). Reinforces principle #1 from `~/.claude/CLAUDE.md` — *Do not assume*.
>
> **Pattern adopted from** `obra/superpowers`'s `verification-before-completion` skill (MIT, © Jesse Vincent — see [github.com/obra/superpowers](https://github.com/obra/superpowers)). Adapted for the BMAD+OpenSpec hybrid flow.

## 1. The principle

**No claim of completion without fresh verification output in the same message.**

An agent that emits `✅ APPROVED` (or any equivalent "done", "ready", "passing", "should work") MUST include in the same message the verbatim output of the verification command(s) that prove the claim. The output must be from a run that happened *after* the work being claimed, not from memory of a past run.

This rule applies to any worker emitting a verdict, any QA emitting a verdict, any retro recording an outcome.

## 2. What "fresh verification" means

Fresh verification has three properties:

### 2.1 It happened **after** the work it claims

- Tests, lint, build, or check executed after the latest code/spec change in the message.
- A verification dated before the change is stale — it could not possibly cover the change.

### 2.2 It produced **observable output** included in the message

- Test runner output (`pytest`, `vitest`, etc.) with the actual pass/fail summary line.
- Lint output (or "no issues found") visible in the message.
- Build output with the success line ("compiled in Xs").
- For verdicts on docs/specs: a manual check that quotes the artefact's relevant sections.

Output in a separate message, in a CI log link, or paraphrased ("tests pass") does NOT count.

### 2.3 It is **specific to the claim**

- A `✅ APPROVED` on `m2-recipes-core/tasks.md` must show acceptance scenarios mapping to test ids.
- A `✅ APPROVED` on a code change must show the test that covers the change running and passing — not a sweep that includes 200 unrelated tests passing.

## 3. Why this matters

Without verification before completion, the worker→QA contract degrades fast:

- Workers emit `✅ APPROVED` based on the *belief* the code works, not evidence.
- QA reviewers can't tell which approvals are checked vs assumed.
- Bugs slip through gates because every verdict is "trusted by default".
- Retro reveals patterns of *I thought it was working* with no recourse — the failure is invisible until production.

Iron law eliminates this by making verification mandatory at the moment of claim.

## 4. Required posture per artefact type

### 4.1 Code changes (workers in /opsx:apply)

The worker's verdict message MUST include:

- The **test command** run (`pnpm test packages/api/src/recipes/recipe.service.spec.ts`, `cargo test --package recipes`, etc.).
- The **command output** with the pass/fail summary.
- A note tying the output to the spec it covers (e.g. "covers AC-1, AC-2 from `specs/recipes.md`").

If lint / build is part of the verification (per the project's CI), include those outputs too.

#### 4.1.1 Broadest-scope rule

Run lint / typecheck at the **broadest scope CI uses**, not the slice subdirectory.

CI runs `mypy --strict apps/api/`, `pnpm --filter @consumer/api check`,
`cargo check --workspace`, etc. — paths that span the whole package, not just
the bounded context the slice touches. A worker that runs `mypy --strict
apps/api/src/iguanatrader/contexts/<slice>/` and reports clean has **not
verified what CI will verify**: the broader scope picks up test files,
fixtures, sibling modules, and cross-cut imports that the slice's subdir
silently excludes.

This rule was retro-proven by iguanatrader Wave 2 slice P1
(`approval-channels-multichannel`, 2026-05-06): six `mypy --strict` errors
in test files were invisible at `apps/api/src/iguanatrader/contexts/approval/`
scope but immediately surfaced at `apps/api/` scope. The fix-push-fix cycle
that resulted (cf. retro at `retros/approval-channels-multichannel.md`) was
preventable with one pre-push command.

The verdict message MUST cite the actual command CI runs, not a narrower
proxy. If the project's CI workflow uses a different scope per check (e.g.
type-check on `apps/`, lint on the changed files only), the worker matches
that exactly — discoverable via `.github/workflows/*.yml` inspection.

#### 4.1.2 Tool-exit-code-over-text rule

When a claim *can be* mechanically verified by a tool, the verdict message
MUST cite the tool's exit code, not paraphrase the tool's output.

Examples:

| Claim | ❌ Forbidden form | ✅ Required form |
|---|---|---|
| "All migrations applied successfully" | "I confirmed migrations are clean" | `alembic current` exit 0 + output showing the head revision |
| "GH Project board updated to In Progress" | "I updated the project board" | Output of `python scripts/verify_board_state.py --change-id X` exit 0 |
| "Tests pass" | "Tests look good" | Pytest's last line `===== N passed in Ms =====` |
| "No mypy errors" | "Types check out" | `mypy --strict <scope>` exit 0 + `Success: no issues found in N source files` |

The rule's justification, per [LLM Structured Outputs: Schema Validation 2026](https://collinwilkins.com/articles/structured-output):

> *"Structured output guarantees syntactically correct JSON, but does not
> guarantee the values are semantically correct. You must always validate the
> final output in your application code before using it."*

An LLM can fabricate plausible tool output. Only **the tool's actual exit
code from a non-LLM-controlled process** is proof. This rule generalises the
slice-2 incident (cf. `gotchas.md` #14) where a worker AI claimed `pytest`
was green based on a hallucinated transcript; CI then failed on push because
the test had not been run.

Reviewers (humans or QA agents) reject any verdict that paraphrases instead
of cites. The reject reason is canonical: `❓ CLARIFICATION NEEDED — verdict
paraphrases tool output instead of citing exit code; per
verification-before-completion.md §4.1.2`.

### 4.2 Spec / doc changes

For `proposal.md`, `design.md`, `tasks.md`, ADRs, etc., where there's no automated verification:

- Quote the relevant section of the upstream spec the artefact must satisfy.
- Show that every clause / FR / acceptance criterion is addressed (point at the line in the deliverable).
- The verdict message reads as a small audit, not a "looks good to me".

### 4.3 Mock / UI artefacts

For HTML/visual mocks (UX track variants, journey mocks):

- Quote the design tokens / DESIGN.md sections the mock claims to follow.
- Show the WCAG-AA contrast ratios verified for every text pair.
- Note any anti-patterns explicitly avoided.

## 5. Failure mode catalogue

Anti-patterns that this spec rejects (each emits at least `goal_drift` + the specific failure name from [agentic-failures.md](agentic-failures.md)):

- **Confidence-without-check**: agent emits `✅ APPROVED` and a description of what *should* happen, no command output. Failure: `over_confidence`.
- **Stale verification**: agent shows command output from before the latest edit. Failure: `over_confidence` + `goal_drift`.
- **Paraphrased output**: agent says "all tests pass" instead of showing the runner output. Failure: `over_confidence`.
- **Sweep verification**: agent runs the full test suite and claims a specific change is verified because the suite passed. Failure: `goal_drift` (the link from change to test isn't shown).
- **Verification of the wrong thing**: agent runs tests for module B when the change touched module A. Failure: `goal_drift`.

## 6. The 3-strike escalation

Mirroring [verdict-contract.md](verdict-contract.md) §3 (max 2 rework cycles):

If the same code/spec is rejected for incomplete verification on iter 1 AND iter 2, the agent does NOT attempt a third self-fix. The track escalates with `❓ CLARIFICATION NEEDED` and a `## Question for human` section explaining what the agent cannot verify.

When the verification gap is structural (e.g. "no test exists for this acceptance criterion"), the resolution is upstream: a spec change to add the AC to a test plan, then implementation, then verification. Not "verify with no test".

## 7. Interaction with `⛔ ARCHITECTURE QUESTIONED` (the 4th verdict)

When verification fails repeatedly because the architecture itself is wrong (e.g. the test cannot pass given the structural choice in the design), the verdict escalates from `❓` to `⛔ ARCHITECTURE QUESTIONED` per [verdict-contract.md](verdict-contract.md) §1. The work pauses; an architect-level review (a human or `bmad-agent-architect`) re-opens the design, not the implementation.

This is the canonical exit for "I tried to verify, three times, and the failure is in the bones, not the code".

## 8. Honest exception: synthesis claims

When an agent emits a verdict on **synthesis work** (a spec, an ADR, a plan), the verification is a self-audit, not a command. The audit MUST:

- Quote the inputs (PRD section, ADR clause, FR, journey doc).
- Show the synthesis matches each input (point at the relevant section of the deliverable).
- Note any input that was deliberately not addressed (with rationale per [output-completeness.md](output-completeness.md) §4).

The audit IS the verification. There is no command output to show, but the structure of the audit substitutes — and is just as observable.

## 9. CI lint (future)

`scripts/check_verification.py` (planned for v0.8.0) will scan messages for the pattern: a `✅ APPROVED` emission must be preceded in the same message by either a fenced code block containing recognisable test runner output OR an explicit synthesis audit (§8). Initial implementation: warning. Hardening: CI-blocking.

## 10. Cross-references

- [verdict-contract.md](verdict-contract.md) — the literals; this spec governs *when* `✅ APPROVED` is emit-able.
- [output-completeness.md](output-completeness.md) — the work itself must be complete; this spec ensures it is *also* verified.
- [agentic-failures.md](agentic-failures.md) — `over_confidence`, `goal_drift`, `premature_completion`.
- [parallel-review.md](parallel-review.md) — QA layers consume verified verdicts; an unverified verdict invalidates the parallel-review chain.
