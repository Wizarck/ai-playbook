---
schema: concept/v1
slug: fusion-integration-pattern
title: Fusion Integration Pattern
summary: |
  You have a consumer project that meets these conditions: 1. The project has
  its own openspec/schemas/<schema-name>/schema.yaml with a non-trivial
  workflow (≥5 artefacts, role assignments per artefact, embedded discipline
  rules). 2. The schema has been used for ≥5 changes…
last_validated: "2026-05-19"
---

# Fusion Integration Pattern

## 1. When this pattern applies

You have a consumer project that meets these conditions:

1. The project has its own `openspec/schemas/<schema-name>/schema.yaml` with a non-trivial workflow (≥5 artefacts, role assignments per artefact, embedded discipline rules).
2. The schema has been used for ≥5 changes (i.e., the workflow is proven, not a sketch).
3. The project's workflow has **strengths the playbook default lacks** — e.g., dedicated test artefact with 2-layer verification (pytest + Playwright), dedicated verify artefact separate from review, embedded "Karpathy-style" discipline rules, central project-level memory.md as Markdown SSOT.
4. The project's workflow has **gaps the playbook addresses** — typically: granular verdict semantics, formal failure-mode taxonomy, parallel-review structure with context isolation, semantic-recall memory layer.

If condition 1 is false (project has no custom schema), use the default BMAD+OpenSpec runbook per [runbook-bmad-openspec.md](runbook-bmad-openspec.md). If conditions 2-4 are false (the project has a sketch workflow it's willing to abandon), prefer **replacement** over fusion.

The first reference implementation of this pattern is `consumer-a` (FastAPI + Next.js, modular monolith), which had 18 changes implemented under its custom `consumer-a-team` schema before adopting the playbook. The fusion preserved all 18 changes as-is and applied to new changes only.

## 2. The fusion decision matrix

For each capability the playbook brings, decide one of:

| Decision | When |
|---|---|
| **Import as-is** | The playbook spec is strictly more rigorous than the project's current rule, with no project-specific overlap to reconcile. |
| **Import as complement** | Both sides bring value on orthogonal dimensions. Keep both; document the mapping. |
| **Reject (override §7)** | The project's existing rule is strictly more rigorous, or the playbook rule overlaps in a way that would weaken project discipline. |
| **Defer (opt-in via submodule)** | The capability ships in the submodule, but the project doesn't activate it today. Document in §5 capability map. |

Worked decision matrix for `consumer-a` (illustrative):

| Aspect | Project rule | Playbook rule | Decision |
|---|---|---|---|
| Verdict semantics | PASS / PASS WITH NOTES / FAIL | ✅ / ⚠️ / ❓ / ⛔ + S1-S4 + max-2-rework | **Import as complement** — playbook adds granularity, document mapping table |
| Testing artefact | Dedicated 2-layer (pytest + Playwright) with iteration requirement | Embedded in apply via `verification-before-completion.md` | **Reject** — project's dedicated artefact is stricter |
| Verification before completion | "Run pytest, paste output" | Iron law: fresh tool output, tool-exit-code-over-text, broadest-scope | **Import as-is** — strictly more rigorous |
| Review | Single Reviewer running 5 holistic checks | 3-layer parallel with context isolation (Blind / Edge / Acceptance) | **Import as complement** — see §5 below: 4-layer pattern |
| Memory | `openspec/memory.md` Markdown SSOT | Hindsight semantic recall via bank `<project>` | **Import as complement** — see §6: dual canonical sources |
| Karpathy guidelines | Embedded in apply instruction | `output-completeness.md` + `verification-before-completion.md` + `agentic-failures.md` | **Import as complement** — orthogonal disciplines |
| BMAD Discovery (PRD/ADRs/UX/personas) | None | Mandatory pre-OpenSpec for full workflow | **Defer (opt-in)** — skills available; full workflow not required for incremental changes |
| Bare repo + worktrees | None | `scripts/wt_add.py` + `git-worktree-bare-setup.md` | **Defer (opt-in)** — activate when concurrent slices appear |
| Forward-authored retros | Post-apply | Mid-apply with `<filled in post-merge>` placeholders | **Defer (opt-in)** — activate when PR workflow formalises |

## 3. Declaring the fusion in AGENTS.md §7

The override is documented in the consumer's `AGENTS.md` §7 with this structure:

```markdown
## 7 Overrides inherited from playbook

### 7.1 OpenSpec workflow — <schema-name> schema (fusion, not replacement)

<project> operates under the custom workflow schema at
`openspec/schemas/<schema-name>/schema.yaml` (<N> artefacts: <list>),
NOT the BMAD-then-OpenSpec runbook at
`.ai-playbook/docs/concepts/runbook-bmad-openspec.md`.

**Rationale**: <N> changes already implemented under <schema-name>.
<List the strengths the project's workflow brings vs the playbook default>.

**Imported from playbook (fusion)**:

- **Verdict literals + S1-S4 severity** per `.ai-playbook/docs/rules/verdict-contract.rule.md`.
  Mapping:
  - <legacy-pass> → ✅ APPROVED
  - <legacy-pass-with-notes> → ⚠️ ISSUES FOUND (iter N) — only S3/S4
  - <legacy-fail> → ⚠️ ISSUES FOUND (iter N) — with S1/S2
  - <legacy-blocked-spec> → ❓ CLARIFICATION NEEDED
  - <legacy-blocked-design> → ⛔ ARCHITECTURE QUESTIONED

- **Max 2 rework cycles** per verdict-contract.md §3 — applies to <list of
  artefacts where iteration is possible>.

- **output-completeness.md rules** in <artefact-name(s)> instructions — no
  skeleton code, no placeholders, no ellipses in delivered files.

- **verification-before-completion.md iron law** in <artefact-name(s)>
  instructions — fresh tool output in same message, tool-exit-code-over-text,
  broadest-scope lint/typecheck.

- **N-layer parallel review** in <review-artefact-name> — N = 3 + M where
  M is the number of project-specific holistic checks (see §5).

- **agentic-failures.md taxonomy** referenced in <apply-artefact-name>
  self-check — hallucination, premature_completion, goal_drift, etc.

- **scope.write_paths declaration** in tasks artefact — each task lists
  intended write paths.

### 7.2 Memory — dual canonical sources

`openspec/memory.md` remains the project's canonical SSOT. Hindsight bank
`<project>` is added as a semantic-recall layer. See §6 of this spec.

### 7.3 BMAD Discovery — skills available, workflow not mandatory

<Project-specific statement about when BMAD discovery applies>.

### 7.4 Available but not active by default (opt-in)

<List of capabilities that ship via submodule but aren't activated today>.

### 7.5 Not applicable

<List of capabilities that don't apply to the project's scope, with rationale>.
```

The §7 block makes the fusion auditable and overridable. `scripts/drift_check.py --check overrides` validates that the §7 entries each cite a playbook spec by path — opaque "we don't follow rule X" entries fail.

## 4. Migration policy: existing changes are exempt

The fusion applies to **future changes only**. Changes already archived (or in-flight) under the project's original schema remain as-is. Two reasons:

1. **Cost**: re-running 18 changes through a fusion schema is rework with no audit value (the original outputs are already in git).
2. **Schema stability for retros**: weekly/monthly retros mine archived changes for patterns. Schema-uniformity within an archive era is more valuable than retrofitting.

State the migration policy explicitly in AGENTS.md §7.5:
> "Migration of `<N>` existing changes to fusion schema — they remain under original schema. Fusion rules apply to new changes only."

If the project later decides to backport fusion rules to old changes (rare), open a separate OpenSpec change for the migration with explicit per-change checklist.

## 5. The N-layer parallel review pattern

The playbook's [parallel-review.md](parallel-review.md) defines 3 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor) running in parallel with context isolation. For projects whose original `review` artefact has **holistic cross-cutting checks** (e.g., "spec compliance, code quality, security/perf, memory patterns, Karpathy compliance" — 5 holistic checks in consumer-a), the fusion adds a **4th layer**:

```
        ┌──── Layer 1: Blind Hunter        (context-isolated, intent drift)
parent ─┼──── Layer 2: Edge Case Hunter    (context-isolated, boundaries)
        ├──── Layer 3: Acceptance Auditor  (context-isolated, AC-by-AC)
        └──── Layer 4: <Project> Reviewer  (FULL context, M holistic checks)
                  │
                  ▼
          4 independent envelopes → parent triage
```

Rules:

- **Layers 1-3** keep the playbook's strict context isolation: each reads ONLY the artefacts named in its brief (typically diff + tests; specs for Acceptance Auditor). They do NOT read `design.md` rationale, the parent conversation, or other layers' output.
- **Layer 4 (`<Project> Reviewer`)** has FULL context: reads everything (proposal, specs, design, tasks, diff, openspec/memory.md, Hindsight recall, change history). Executes the project's existing M holistic checks. This is where project-specific knowledge applies: known anti-patterns from memory.md, project-specific security boundaries, naming conventions, blueprint patterns, etc.
- **No size opt-out**: the 4 layers run on EVERY change regardless of diff size. The holistic Layer 4 checks (memory patterns, security, project conventions) are cross-cutting — a 20-LOC diff can introduce a secret, violate a memory pattern, or break a convention as easily as a 500-LOC diff. The cost of 4 Sonnet subagents in parallel is less than the risk of skipping holistic checks on "small" changes.
- **Parent triage** receives 4 envelopes per [verdict-contract.md](../rules/verdict-contract.rule.md) §2 + [agent-contract.md](agent-contract.md) §3. Standard rules apply: S1+S2 block, S3+S4 batched, dedupe cross-layer, dismiss-with-rationale, any `❓` halts the track.
- **Telemetry**: emit `ai_playbook.review.layers=4`, `ai_playbook.review.holistic_checks=<M>` on the parent span. Retro cadence (per `retrospective-cadence.md` when populated) can compare 4-layer vs 3-layer catch rates.

The "quad_green" outcome (all 4 layers approve) replaces "triple_green" for fusion projects. Telemetry attribute: `ai_playbook.review.quad_green=true`.

### 5.1 Authoring the Layer 4 brief

The project's existing `review` instruction (whatever rendered M holistic checks under the original single-Reviewer schema) becomes the brief for Layer 4 verbatim. The Layer 4 brief must:

- Reference the project's `openspec/memory.md` and Hindsight recall via `.claude/injected-context.md`.
- List the M holistic checks explicitly (1, 2, ..., M) with concrete pointers to project-specific patterns from memory.md.
- Cross-reference `.ai-playbook/docs/concepts/agentic-failures.md` failure modes that apply to the project's stack.
- End with verdict emission per verdict-contract.md (no project-specific verdict literal — use the canonical 4).

Example Layer 4 brief skeleton (replace `<...>` placeholders):

```
You are the <PROJECT> REVIEWER. Unlike the 3 isolated layers, you have FULL
CONTEXT: read proposal, specs, design, tasks, diff, openspec/memory.md,
.claude/injected-context.md (Hindsight recall), and change history if relevant.

Execute these <M> holistic checks; emit findings inline with [S1..S4]:

1. <CHECK 1 NAME>
   <Specific rules for this check, including project-specific patterns from
   memory.md or Hindsight recall>

2. <CHECK 2 NAME>
   <...>

...

<M>. <CHECK M NAME>
    <...>

Return: envelope per agent-contract.md, telemetry.review.layer = "<project>_holistic".
```

## 6. Dual canonical memory sources

Projects with a mature `openspec/memory.md` (a Markdown file in git, append-only, human-readable, auditable) adopt Hindsight **as an additional layer**, not a replacement.

Comparison:

| Property | `openspec/memory.md` (Markdown SSOT) | Hindsight bank `<project>` |
|---|---|---|
| Storage | Markdown plain in git | Vector DB + REST API |
| Retrieval | Open the file | `hindsight.recall(query, top_k, similarity≥0.7)` semantic |
| Write | Append manual `## <Change> — YYYY-MM-DD` | `retain_memory.py --bank <project> --kind <kind>` |
| Decay | No decay; immortal in git history | 90-day soft decay (memory-hierarchy.md §3) |
| Conflict resolution | N/A (single source) | Observed > recall (memory-hierarchy.md §6) |
| Cross-session | Agent must open file | Auto-recall via SessionStart hook |
| Auditable | Yes (git log + diff) | Partial (queue file gitignored) |

### 6.1 Wiring the dual sources

In the project's `memory` artefact instruction, add a 2-step retain:

```yaml
STEP 1 (Markdown canonical): Append summary to openspec/memory.md with format
  ## <Change Name> — YYYY-MM-DD
  - Key lesson 1
  ...

STEP 2 (Hindsight retain — fusion): For each significant lesson
  ("significant" = applies across changes, not implementation detail), retain:

  python .ai-playbook/scripts/retain_memory.py \
    --bank <project> \
    --kind <lesson|gotcha|decision|failure> \
    --content "<text — 1-2 sentences>" \
    --why "<rationale>" \
    --tags "<project>,<change-id>,<topic-tags>"

  Examples:
  - Gotcha about <stack-specific behaviour> applies forever → retain.
  - The exact line where you added fix → DO NOT retain (git blame can find it).
  - ADR-style decision ("We chose X over Y because <rationale>") → kind=decision.
  - Failure mode encountered + fixed → kind=failure.
```

### 6.2 Conflict resolution: observed Markdown wins

When Hindsight recall in `.claude/injected-context.md` contradicts what's currently in `openspec/memory.md`:

1. **TRUST openspec/memory.md** (the Markdown SSOT in git).
2. Note the conflict in the proposal's "Memory conflicts" section.
3. The retro for the next change invalidates the stale Hindsight entry (`python -m scripts.retain_memory --invalidate <entry-id>` or via re-retain with date-annotated correction).

Rationale: Hindsight entries decay (90-day soft) and may reflect outdated state; `openspec/memory.md` is git-tracked, append-only, and PR-reviewed — it cannot drift silently.

### 6.3 DEGRADED_CONTEXT fallback

If Hindsight is unreachable during a session, the SessionStart hook writes `DEGRADED_CONTEXT` into `.claude/injected-context.md` and retains queue at `.ai-playbook/hindsight-queue.jsonl` (gitignored). The session continues using `openspec/memory.md` only.

When Hindsight reconnects, the queue flushes. This means **the project never blocks on Hindsight availability** — the Markdown SSOT is the durable floor.

## 7. Verdict mapping reference table

For projects whose original schema used a different verdict vocabulary, document the mapping in `AGENTS.md §7.1`:

| Legacy verdict | Canonical verdict (verdict-contract.md §1) | Notes |
|---|---|---|
| PASS / VERIFIED / OK | `✅ APPROVED` | All checks pass, output cited per verification-before-completion.md |
| PASS WITH NOTES / PASS-MINOR / ACCEPT-WITH-FOLLOWUP | `⚠️ ISSUES FOUND (iter N)` with only S3/S4 findings | Findings batched as separate cleanup work, not blocking |
| FAIL / REJECT / BLOCKED-IMPL | `⚠️ ISSUES FOUND (iter N)` with S1 or S2 findings | Blocking; fix and re-submit |
| BLOCKED (ambiguous spec) | `❓ CLARIFICATION NEEDED` | Change moves to `blocked-by-spec`; human disambiguates |
| BLOCKED (bad design) | `⛔ ARCHITECTURE QUESTIONED` | Only after iter 2 same finding; architect-level review |
| (no legacy equivalent — new state) | `budget_exhausted` (synthesised by harness) | Subagent hit max_tool_calls or wall_seconds |

The project's artefact templates emit the canonical literal on its own line as the LAST line of the top-level section. `scripts/verdict_lint.py --shape artifact` validates this literal post-emission.

## 8. Pre-commit hook profile for fusion projects

The fusion project's `.pre-commit-config.yaml` typically inherits these hooks from the playbook, with project-specific opt-outs:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-added-large-files
        args: [--maxkb=500]

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks

  - repo: local
    hooks:
      - id: schema-validate-agents
        name: Validate AGENTS.md against playbook schema
        entry: python .ai-playbook/scripts/schema_validate.py AGENTS.md
        language: system
        pass_filenames: false
        files: ^AGENTS\.md$

      - id: mcp-validate
        name: Validate mcp-servers project layer
        entry: python .ai-playbook/scripts/mcp/validate.py
        language: system
        pass_filenames: false
        files: ^mcp-servers\.project\.yaml$

      - id: verdict-lint
        name: Lint review/verify verdict shape (verdict-contract.md)
        entry: python .ai-playbook/scripts/verdict_lint.py --shape artifact
        language: system
        files: ^openspec/changes/.*/(review|verify)\.md$

      # OPTIONAL — disable if project does NOT promote specs to openspec/specs/ via archive workflow
      # - id: block-manual-spec-edit
      #   name: Block manual edits to openspec/specs/
      #   entry: python .ai-playbook/scripts/block_manual_spec_edit.py
      #   language: system
      #   files: ^openspec/specs/.*\.md$

      # OPTIONAL — disable if project does NOT call LLMs directly from code
      # - id: verify-llm-routing
      #   name: Verify LLM routing (direct-SDK callers)
      #   entry: python .ai-playbook/scripts/verify_llm_routing.py
      #   language: system
      #   pass_filenames: false
      #   always_run: true
```

The two commented-out hooks are project-specific and the fusion template comments them rather than removes them — the consumer enables them when the conditions apply.

## 9. Worked example: consumer-a

`consumer-a` (FastAPI + Next.js modular monolith) was the first project to adopt this pattern (2026-05-13, ai-playbook v0.11.0). Key choices:

- **Schema**: kept `openspec/schemas/consumer-a-team/schema.yaml` with 9 artefacts (proposal → specs → design → tasks → apply → test → review → verify → memory).
- **Imported from playbook**: verdict literals + S1-S4, max-2-rework, output-completeness, verification-before-completion (broadest-scope + tool-exit-code rules), 4-layer parallel review (3 isolated + consumer-a Reviewer with 5 holistic checks), agentic-failures self-check in apply, scope.write_paths declaration in tasks.
- **Layer 4 holistic checks**: (1) spec compliance, (2) code quality (FastAPI/Next.js conventions, blueprint pattern, async/await), (3) security & performance (multi-tenant FK leakage, RFC 7807 compliance, N+1, secrets), (4) patterns from memory.md + Hindsight recall (Celery-only syncs, admin-only sync buttons, stale job cleanup), (5) Karpathy compliance.
- **Dual memory**: `openspec/memory.md` (Markdown SSOT) + Hindsight bank `consumer-a`. Both retained per memory artefact.
- **Deferred (opt-in)**: BMAD Discovery full workflow, bare worktrees, forward-authored retros, slicing artefact, 6 HITL gates.
- **Not applicable**: migration of 18 existing changes (exempt), `block_manual_spec_edit.py` (consumer-a doesn't archive-promote specs), `verify_llm_routing.py` (consumer-a doesn't call LLMs directly).

See `c:\Projects\consumer-a\AGENTS.md` §7 for the full override block.

## 10. See also

- [dispatcher-chain.md](dispatcher-chain.md) — 3-level inheritance; §7 overrides are documented here.
- [verdict-contract.md](../rules/verdict-contract.rule.md) — canonical verdict literals + S1-S4 mapping.
- [parallel-review.md](parallel-review.md) — 3-layer pattern that becomes the lower 3 layers of fusion review.
- [memory-hierarchy.md](memory-hierarchy.md) — Hindsight bank semantics + decay policy.
- [agentic-failures.md](agentic-failures.md) — failure-mode taxonomy referenced in fusion apply self-check.
- [output-completeness.md](../rules/output-completeness.rule.md) — banned skeleton patterns.
- [verification-before-completion.md](../rules/verification-before-completion.rule.md) — fresh tool output + broadest-scope rule.
- [agent-contract.md](agent-contract.md) — scope.write_paths declaration.
- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) — the default workflow this pattern explicitly overrides.
