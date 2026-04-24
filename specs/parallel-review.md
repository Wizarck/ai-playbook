# parallel-review.md

> **Status**: v1.0.0.

For high-stakes artefacts — code review on a non-trivial diff, proposal review, implementation
readiness check, retrospective — the playbook spawns **three orthogonal subagents in parallel**.
Each receives a bounded, LEAN brief. Each returns an independent verdict per
[verdict-contract.md](verdict-contract.md) using the envelope in
[agent-contract.md](agent-contract.md). The main agent then triages the three reports.

The three layers are intentionally **orthogonal and isolated**: a finding missed by one is likely
to be caught by another, and none of them sees the others' output until the parent has triaged.

---

## 1. Pattern

```
                             ┌──── Blind Hunter       (context-isolated, checks intent drift)
parent agent ── Task × 3 ────┼──── Edge Case Hunter   (branch/boundary/error walk)
                             └──── Acceptance Auditor (AC-by-AC verification)
                                       │
                                       ▼
                               3 independent envelopes
                                       │
                                       ▼
                                 parent triage
```

Spawned via the Claude Code Task tool (or equivalent harness primitive) with `subagent_type` set
per layer. The three spawns run concurrently. Each child operates in a **fresh context** — it does
NOT see the parent's conversation history beyond what is explicitly embedded in its `brief`.

## 2. When to use it

| Artefact | Layers required |
|---|---|
| Code review on a diff >~50 LOC or touching a DDD boundary | All three. |
| OpenSpec `proposal.md` review | Blind Hunter + Acceptance Auditor (Edge Case Hunter N/A at proposal stage). |
| `specs/*.md` review (OpenSpec `Scenario: WHEN/THEN`) | Edge Case Hunter + Acceptance Auditor. |
| Implementation readiness check before `openspec apply` | All three. |
| Retro on a completed change | Blind Hunter + Acceptance Auditor, running over the archived change. |

For diffs ≤50 LOC that touch no boundary, a single `bmad-code-review` subagent is sufficient.

## 3. Canonical prompts

Each prompt is embedded into the subagent's `brief` field of the [agent-contract.md](agent-contract.md)
input envelope. Each prompt is ≥30 lines. The parent SHOULD template it (substitute `$VAR`s) rather
than hand-edit per call.

### 3.1 Blind Hunter

```
You are the BLIND HUNTER reviewer for $PROJECT.

You have been spawned WITHOUT the task's conversational context on purpose. You do NOT know what
the parent agent was asked to do beyond what this brief embeds. Your job is to read the artefact
and reconstruct its intent *from the artefact alone*, then flag any content that drifts from that
intent.

ARTEFACT UNDER REVIEW
- Path: $ARTEFACT_PATH
- Kind: $ARTEFACT_KIND (diff | proposal | specs | readiness | retro)
- The ONLY context you may read is: $ARTEFACT_PATH plus what it explicitly cites (and those
  citations, only).
- You may NOT read design.md, tasks.md, prior conversation, or the Edge Case Hunter / Acceptance
  Auditor outputs. Context isolation is the point.

WHAT TO FLAG (S1 unless noted)
- Statements or code that contradict the artefact's own stated intent.
- Scope creep: content not traceable to the stated problem/intent (usually S2).
- Magic numbers, unexplained constants, or "just works" assertions.
- Any citation to a file/function/flag you cannot verify exists (this is a `hallucination`
  failure — see agentic-failures.md).
- Verdicts (✅ / ⚠️) that appear over-confident relative to the evidence shown
  (this is `over_confidence` — see agentic-failures.md).

WHAT NOT TO FLAG
- Coverage gaps — that's Edge Case Hunter's job.
- AC-by-AC traceability — that's Acceptance Auditor's job.
- Style / naming unless it actively misleads the reader.

RETURN SHAPE
Emit a single JSON document matching agent-contract.md §3. Set
telemetry.ai_playbook.review.layer = "blind_hunter". Verdict per verdict-contract.md. Every
finding carries a severity S1..S4. Do NOT use S0.

BUDGET: respect the budget field in your input envelope. If you are close to the limit, emit the
envelope early with what you have and note truncation in telemetry.

Do NOT write any file. Do NOT spawn further subagents.
```

### 3.2 Edge Case Hunter

```
You are the EDGE CASE HUNTER reviewer for $PROJECT.

You walk every branch, boundary, error path, and concurrency hazard in the artefact. You report
ONLY unhandled cases — do not restate what IS handled. Method is orthogonal to attitude: you are
not adversarial, you are methodical.

ARTEFACT UNDER REVIEW
- Path: $ARTEFACT_PATH
- Kind: $ARTEFACT_KIND (diff | specs | proposal-with-pseudocode)
- You MAY read the artefact, the files it modifies, and the test files in the same change.
- You MAY NOT read the parent conversation, design.md beyond invariants, or the other layers'
  output.

DIMENSIONS TO WALK
1. Control flow: every branch, every early return, every exception path.
2. Boundaries: empty collections, zero, negative, max int, unicode edge, timezone cross-over,
   DST, leap day, leap second where relevant.
3. Error paths: what happens if the dependency throws? Times out? Returns malformed data?
4. Concurrency: can two tenants collide on a shared resource? Double-POST? Race on init?
5. I/O: partial reads, closed connections, disk full, DNS flap.
6. Data: NULLs, empty strings, whitespace, orgId mismatch, soft-deleted rows, inactive users.
7. Invariant drift: does the code violate an ADR or AGENTS.md hard rule? (S2).

WHAT TO FLAG
- Each unhandled case gets ONE finding with severity:
  - S1 if the case corrupts data, leaks a secret, breaks auth, or crashes the process.
  - S2 if it violates an ADR/hard rule without correctness impact (e.g. DDD boundary breach).
  - S3 if the handling is present but uninformative (e.g. swallows error silently).
  - S4 if the case is theoretical (no realistic trigger in this app).

WHAT NOT TO FLAG
- Intent drift — Blind Hunter's job.
- Missing AC coverage — Acceptance Auditor's job.
- Performance speculation unless you can name a concrete O(n²) hot path.

RETURN SHAPE
Single JSON document per agent-contract.md §3. Set
telemetry.ai_playbook.review.layer = "edge_case". Verdict per verdict-contract.md.

Do NOT write files. Do NOT spawn subagents. Respect the budget.
```

### 3.3 Acceptance Auditor

```
You are the ACCEPTANCE AUDITOR for $PROJECT.

Your job is mechanical: walk each acceptance criterion one-for-one and cite the evidence that it
is met — or name it as unmet. You are the pedant of the trio.

ARTEFACT UNDER REVIEW
- Implementation: $DIFF_OR_IMPLEMENTATION_PATH
- Source of truth for criteria: $SPEC_PATH (typically openspec/changes/$CHANGE_ID/specs/*.md)
- You MAY read both plus the test files they cite. You MAY NOT read design.md's rationale,
  the conversation, or the other layers' output.

METHOD
1. Parse the spec's `## Scenario: WHEN/THEN` blocks. Each scenario is ONE acceptance criterion.
2. For each AC, locate the test file and test name that exercises it. Cite `path:line`.
3. If no test exists, locate the code path that would satisfy it and cite `path:line`.
4. If neither exists, the AC is UNMET — emit a finding.

FINDING RULES
- Unmet AC with tests claimed elsewhere: S1 (contradiction with the spec).
- Unmet AC with no test and no code: S1.
- AC met but test is trivial (e.g. asserts only "no throw"): S3.
- AC met but off-by-one in the test name vs spec wording: S4.
- AC that is itself ambiguous (you cannot determine whether it's met): emit
  ❓ CLARIFICATION NEEDED with a ## Question for human section per verdict-contract.md §4.

RETURN SHAPE
Single JSON document per agent-contract.md §3. Set
telemetry.ai_playbook.review.layer = "acceptance". Verdict per verdict-contract.md.

Be exhaustive on ACs. Be silent on anything that isn't an AC.

Do NOT write files. Do NOT spawn subagents. Respect the budget.
```

## 4. Triage after return

The parent agent receives up to three envelopes. It performs triage **before** taking any action:

1. **Bin findings by severity**:
   - S1 + S2 → **block** this track, fix-list grows.
   - S3 + S4 → **batched** cleanup queue (separate commit or follow-up change).
2. **Dedupe across layers**: same `title` + `location` prefix from two layers counts as one
   finding (higher severity wins).
3. **Dismiss with rationale**: a finding may be a false positive. The parent agent MUST emit a
   one-sentence rationale into the retro log (via `scripts/log_event.py`); "LGTM" is not a
   rationale. A dismissal without rationale is an `over_confidence` failure.
4. **If any layer emitted `❓ CLARIFICATION NEEDED`**: the track halts regardless of the other
   layers. OpenSpec change moves to `blocked-by-spec` per
   [dispatcher-chain.md](dispatcher-chain.md). The parent does NOT attempt to answer the question.
5. **If all three emit `✅ APPROVED`**: proceed. Log the triple approval with
   `ai_playbook.review.triple_green=true` for retro surfacing.

Cross-contamination is forbidden: the parent does NOT feed one layer's output into another. If a
layer missed something, it is fixed by tightening its prompt, not by chaining layers.

## 5. Cost budgets

| Layer | Typical model | Token ceiling | Tool-call ceiling | Wall-seconds |
|---|---|---|---|---|
| Blind Hunter | Sonnet | 25 000 out | 40 | 240 |
| Edge Case Hunter | Sonnet | 25 000 out | 40 | 240 |
| Acceptance Auditor | Sonnet | 25 000 out | 40 | 240 |

Use **Opus** only when the artefact is architectural — a proposal that spans multiple bounded
contexts, a cross-cutting ADR, a retro on a SYSTEMIC failure. Opus-on-all-three for a routine 100-
LOC review is waste; see [model-routing.md](model-routing.md) when populated.

Three Sonnet parallels typically cost less wall-time than one Opus serial and catch more, because
isolation beats raw depth for review work.

## 6. Telemetry

Each subagent emits an OTel span child of the parent trace. Required attributes:

| Attribute | Value |
|---|---|
| `ai_playbook.review.layer` | `blind_hunter` \| `edge_case` \| `acceptance` |
| `ai_playbook.review.verdict` | one of the verdict literals |
| `ai_playbook.review.findings.s1_count` | int |
| `ai_playbook.review.findings.s2_count` | int |
| `ai_playbook.review.findings.s3_count` | int |
| `ai_playbook.review.findings.s4_count` | int |
| `ai_playbook.tokens_out` | int |
| `ai_playbook.tool_calls` | int |

The parent aggregates across the three children with attribute `ai_playbook.review.triple=true` on
its own span, and emits a single JSONL record via `scripts/log_event.py`.

## 7. Discipline rules

1. **Fresh context per subagent.** The brief is the only context. No "parent conversation" is
   passed in.
2. **No file edits.** The three layers produce reports; only the parent acts on them.
3. **Log via `scripts/log_event.py`** (one JSONL record per envelope received).
4. **Return via the [agent-contract.md](agent-contract.md) envelope.** A layer that free-forms
   narrative without the envelope is malformed; the linter and the parent reject it.
5. **Respect max-2-rework.** If the parent is about to spawn iter-3 with the same finding, it
   MUST instead escalate per [verdict-contract.md](verdict-contract.md) §3.

## 8. Worked example — `acme-shop` cart diff

**Setup.** Fictitious repo `acme-shop`. Branch `feat/cart-clear` adds a `clearCart` method on
`CartService`, touching 3 files, ~150 LOC. The parent agent is running `bmad-code-review`.

**Spawn (parallel, three Task calls in one message).**

| Layer | Brief highlights |
|---|---|
| Blind Hunter | Reads only `apps/api/src/cart/cart.service.ts`, its controller, and the test file. Reconstructs "clearing a cart deletes all items for the org" from the code. |
| Edge Case Hunter | Reads same files + the CartItem repository. Walks empty-cart, two-tenant collision, and exception paths. |
| Acceptance Auditor | Reads `openspec/changes/cart-clear/specs/cart.md` which lists AC 1..5. Walks each AC, cites test line. |

**Return envelopes (abbreviated).**

```
Blind Hunter     → ⚠️ ISSUES FOUND (iter 1)  [1×S2: adds tenant-wide clear when spec says "my cart"]
Edge Case Hunter → ⚠️ ISSUES FOUND (iter 1)  [1×S1: null-pointer on empty cart; 1×S3: swallows repo error]
Acceptance Auditor → ⚠️ ISSUES FOUND (iter 1) [1×S1: AC 3 "clear-cart audit log" has no test]
```

**Parent triage.**

- Dedupe: three distinct findings; no overlap.
- Block: 2×S1 + 1×S2 → block.
- Dismiss rationale: none (all confirmed by spot-check of `cart.service.ts:83` and AC 3 spec line).
- Emit single JSONL record summarising all three envelopes.
- Hand back to the worker: "iter 1 findings — fix the three listed items, re-submit for iter 2."

**Second pass.** Worker fixes all three; re-runs the same three layers with `iter` counter
incremented by the parent. All three return `✅ APPROVED`. Parent commits with
`ai_playbook.review.triple_green=true`. Change proceeds to `openspec apply`.

## 9. See also

- [verdict-contract.md](verdict-contract.md) — verdicts + severities emitted by each layer.
- [agent-contract.md](agent-contract.md) — envelope that carries the report.
- [agentic-failures.md](agentic-failures.md) — `hallucination`, `over_confidence`,
  `cascade_failure` — the three layers are the main defence against these.
- [memory-hierarchy.md](memory-hierarchy.md) — each layer queries `hindsight.recall` on its own
  bank scope.
- [model-routing.md](model-routing.md) — Sonnet × 3 vs Opus × 1 decision rule.
