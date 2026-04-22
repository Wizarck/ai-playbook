# parallel-review.md

> **Status**: stub, v0.1.0. Populated in **T05**.

## Pattern

For high-stakes artifacts (code review, proposal review, readiness check), spawn **three orthogonal subagents in parallel**:

1. **Blind Hunter** — reads diff WITHOUT the task context. Catches changes that drift from stated intent.
2. **Edge Case Hunter** — walks every branch, boundary, and error path. Reports only unhandled cases.
3. **Acceptance Auditor** — checks acceptance criteria one-for-one against the artifact. Verdict with severity.

Each returns an independent verdict per [verdict-contract.md](verdict-contract.md). The main agent triages into:
- Actionable now (S1/S2) — blocks progress.
- Batched (S3/S4) — commit-cleanup queue.
- False positive — dismissed with rationale.

## Task subagent discipline

- Each subagent receives a **fresh, minimal context** — never the full conversation.
- Prompt explicitly states the role, the artifact, and the return shape.
- No subagent edits files; they produce reports, the main agent acts.
- Reports are logged to the trace via `scripts/log_event.py`.

## Populated in T05

Canonical prompts per subagent, worked examples from archived OpenSpec changes, and cost/latency budgets (reviewed artifacts don't need Opus — Sonnet parallel is usually optimal).
