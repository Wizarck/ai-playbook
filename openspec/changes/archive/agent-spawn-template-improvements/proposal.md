# proposal — `agent-spawn-template-improvements`

> **Status**: in-flight (slice/`agent-spawn-template-improvements`).
> **Wave**: ai-playbook v0.13.4 candidate (additive PATCH — docs/spec only).
> **Authored**: 2026-05-14.
> **Parent project**: `Wizarck/consumer-e` parallel-slice dashboard wave (PRs #141 → #152). This proposal upstreams two prompt-engineering patterns that emerged across 4 consecutive worker-agent-delegated PRs (#149, #150, #151, #152) and one CI-recovery cycle (PR #152 L2 re-run).

## Problem

`release-management.md` §4.5 already documents the AI-reviewer signoff contract — the §4.5.3 markers (`Profile:`, `Reviewer:`, `Self-review findings:`) regex-validated by the L2 fallback workflow, and §4.5.4 auto-generated bump-PR pre-population rule. What §4.5 does **not** cover is the **worker-agent delegation pattern**: when the main agent invokes `Agent(isolation="worktree", ...)` to ship a WHOLE slice end-to-end (apply tasks → lint → push branch → open PR → STOP), the delegated worker agent operates from a self-contained prompt with no live conversation context.

Two failure modes recur in that delegation flow, neither addressed by §4.5.1-4.5.4:

### A. Worker agent polls CI from inside its task budget

The worker agent's task budget is finite (configurable, typically ≤10 min). If the prompt does not explicitly tell it to STOP after `gh pr create` returns, the worker will idle waiting for CI to go green — exhausting budget that contributes nothing the parent agent could not see itself via `gh pr checks`. Observed across consumer-e PRs #141/#143/#148 (~16 min agent wall-time, mostly idle polling); fixed in prompts for #149/#150/#151/#152 by adding the literal sentence "STOP after `gh pr create` returns the PR URL — parent monitors CI". Wall-time dropped to 4-8 min consistently.

### B. Worker agent writes a substantive `§4.5 self-review` section that misses the §4.5.3 markers

Worker agents trained on prior PRs imitate the **shape** of past self-review sections without re-reading [`release-management.md`](../docs/concepts/release-management.md) §4.5.3 to learn that the **literal marker strings** (`Profile:`, `Reviewer:`, `Self-review findings:`) are regex-validated. They write good substantive prose under a `## §4.5 self-review` heading, miss the markers, and the `ai-self-review-required` status check fails. Observed on consumer-e PR #152: agent's body had a full self-review section with deprecation context, file counts, and cross-tenant handling — but no canonical block. Recovery required parent to edit the body + `gh run rerun` the L2 workflow (~6 min total).

Both failure modes are **prompt-engineering** problems: the agent-spawn prompt template the main agent assembles ad-hoc does not include the patterns. Codifying them in `release-management.md` makes the contract discoverable to any worker agent that follows the playbook.

## Proposed change

Extend `docs/concepts/release-management.md` with two new subsections under §4.5:

### §4.5.5 Worker-agent delegation: STOP-after-`gh pr create` directive

The main agent MUST embed this directive in any prompt that delegates whole-slice shipping (apply → lint → push → open PR) to a worker agent via `Agent(isolation="worktree", ...)` or equivalent. The directive:

> **STOP after `gh pr create` returns the PR URL.** Do NOT poll CI. Do NOT wait for checks. The parent agent monitors CI status via `gh pr checks <N>` and handles merge / fix-forward / abort decisions.

Reason: worker-agent task budgets are finite. Polling CI from inside the budget produces no signal the parent cannot see itself, while burning ~10 minutes of wall-time per delegated slice. Verified on consumer-e PRs #149-#152 (4-for-4): worker wall-time dropped from ~16 min to 4-8 min after this directive landed in the prompt.

### §4.5.6 Worker-agent delegation: AI-reviewer signoff canonical block in prompt

The main agent MUST include the literal §4.5.3 canonical block in the worker-agent prompt's "PR body template" section, NOT a free-form "write a self-review section" instruction. Free-form instructions produce substantive prose under a `## §4.5 self-review` heading that misses the regex-validated markers, triggering an L2 re-run cycle.

Minimum viable prompt-embedded template (the worker agent copy-pastes this into its PR body, substituting placeholders):

```markdown
## AI-reviewer signoff

- **Profile**: <A | B>  <!-- A = code-bearing slice; B = mechanical chore / docs-only -->
- **Reviewer**: self-review <!-- (or claude-code-action / CodeRabbit when invoked) -->
- **Self-review findings**: <one-sentence justification grounded in the diff shape; "none — <reason>" is acceptable for trivial Profile B diffs>
```

Reason: agents imitate shape, not contract. The §4.5.3 markers are regex-validated by `scripts/post_self_review_checklist.py`; agents that learn from past PR bodies without re-reading the spec produce near-misses. Verified on consumer-e PR #152: worker agent wrote a substantive `## §4.5 self-review` section with deprecation context, file counts, and cross-tenant handling — but no markers → L2 re-run cycle (+6 min).

## Out of scope

- **Auto-generated bump PRs**: already covered by §4.5.4. The new §4.5.5+§4.5.6 cover the *worker-AI* delegation flow, not the *automation* flow.
- **Sub-slice parallel-group delegation**: covered by `skills/openspec-apply-parallel/SKILL.md`. That skill's subagents commit and return; the *main* agent opens the PR + handles §4.5 — so §4.5.5/§4.5.6 don't apply at the sub-slice level.
- **Two-hit rule for promoting deferred retro items**: observed once on consumer-e's `test-cookies-pattern-migration` retro promotion. Single observation = insufficient evidence for canonicalization; revisit when a second recurrence lands.
- **`gh pr create --body-file` template artifact**: a `templates/new-project/.github/PR-BODY-TEMPLATE.md.tmpl` that worker prompts can `cat`-include is a v0.14.x candidate; v0.13.4 stays docs-only.

## Acceptance

- `docs/concepts/release-management.md` gains §4.5.5 + §4.5.6 (~30 lines added).
- `CHANGELOG.md` gains a `[0.13.4]` entry.
- Consumers (consumer-e, consumer-b, consumer-d, consumer-c) bump submodule to v0.13.4 in follow-up bump PRs (handled by `propagate_bump.py`, mechanical).
