# conflict-resolution-policy.md

> **Status**: v1.0.0. Authored under OpenSpec change `industrialize-dev-flow` (Phase 5 wave 2) on 2026-05-05. Referenced from [`docs/development-flow.md`](../docs/development-flow.md) §2 (parallelism) and §4 (pointer table).
>
> **Enforcement**: 📋 spec-only. Convention; humans + agents commit to it. No automated mediator.

When two PRs (or two parallel work streams) target the same file or capability, the playbook codifies who rebases, when to coordinate, and when to escalate. Without this, parallel work degrades into either silent overwrites or perpetual rebase-fights.

---

## 1. Scope

This policy governs:

- **PR-level conflicts**: two open PRs against `main` that touch the same file (git merge conflict territory).
- **OpenSpec-change-level conflicts**: two open OpenSpec changes (`openspec/changes/<id>/`) that touch the same spec or capability.
- **Wave-N coordination**: parallel slices (per [release-management.md §6.4](release-management.md)) that drift onto each other's territory.
- **Intra-slice coordination**: subagents inside one OpenSpec change writing to overlapping paths (per [release-management.md §6.6](release-management.md)).

Out of scope: branch-level conflicts within a single dev's work (use standard `git rebase` / `git merge` workflow).

---

## 2. The four conflict tiers

| Tier | Symptom | Resolution |
|---|---|---|
| **T1 — Trivial** | Auto-resolvable by `git`: non-overlapping line edits to the same file (e.g. one PR adds row 5 of a table, another adds row 7). | Second PR rebases on main; git auto-merges; no human attention. |
| **T2 — Mechanical** | Overlapping lines but semantic intent is clearly disjoint (one PR adds a row, another tweaks formatting in the same row). | Second PR's author rebases; conflict markers resolved by the rebaser; no review needed. |
| **T3 — Semantic** | Overlapping lines AND intent could be combined or reordered (one PR adds field `foo`, another adds field `bar`, both in the same dict). | Second PR's author rebases AND comments on first PR linking the conflict; first PR's author confirms the resolution captured both intents. Reviewer approves both. |
| **T4 — Architectural** | Two PRs implement the same capability differently (one PR adds `notify_telegram()`, another adds `notify_via_telegram_bot()` — competing designs). | **STOP both PRs**. Open an issue / OpenSpec change of higher scope. The maintainer (Profile A) decides which design wins; one PR closed, the other absorbs the work. |

---

## 3. The "second-merger rebases" rule

For T1 / T2 / T3 conflicts where both PRs are valid:

- The PR that **merges second** is responsible for the rebase work.
- The PR that **opened first** does NOT modify its branch to accommodate the later one; the later author absorbs the conflict cost.
- If the first PR is stale (>14 days no progress) and another PR conflicts, the maintainer can flip the order — but documents the rationale in the merge commit.

Rationale: conflict-cost incentives favour rapid review + merge cycles; the PR that languishes loses priority.

---

## 4. The 5-line rule for T3 escalation

When rebasing produces a semantic merge conflict:

- **Conflict ≤ 5 lines**: rebaser resolves alone, comments on first PR linking to the resolution commit.
- **Conflict > 5 lines OR ≥ 3 conflict markers**: STOP rebase. Open a coordination issue:

```
# Conflict-coordination issue template

**Title**: Conflict between PR #X and PR #Y on `<file>`

**Summary**: <1-line summary of competing changes>

**PR #X (opened first)**: <link>
- Touches lines A-B of `<file>`
- Intent: <1-line>

**PR #Y (opened second)**: <link>
- Touches lines C-D of `<file>` overlapping
- Intent: <1-line>

**Proposed resolution**:
- [ ] Option 1: PR #Y rebases keeping both intents
- [ ] Option 2: One PR closes, the other absorbs scope
- [ ] Option 3: Higher-scope OpenSpec change supersedes both
```

The issue gets discussed; resolution chosen; one PR proceeds, the other aligns.

Rationale: ad-hoc resolution of large conflicts loses authorial intent; explicit coordination issue makes the trade-off visible and audit-able.

---

## 5. Wave-N coordination protocol

When ≥ 3 OpenSpec changes are concurrent (Wave-N per release-management.md §6.4):

- **Pre-flight**: each change's `proposal.md §Cross-references` declares which specs/files it touches. If overlap detected with other live changes, escalate at proposal-review time, not at PR-merge time.
- **Daily sync** (optional, when ≥ 3 humans / agents working): a shared `runbooks/wave-N-status.md` file tracks "open PRs / blocked-by / in-flight". Updated by each worker before EOD.
- **Wave coordinator role**: when ≥ 3 PRs concurrent, the maintainer (Profile A) acts as wave coordinator: sequences merge order to minimise conflict cascades.

Without coordination, Wave-N still works (each PR rebases as it merges), but the cost grows quadratically with N. Coordination is opt-in below N=3 and recommended above.

---

## 6. Intra-slice coordination protocol

For subagents within one OpenSpec change (per release-management.md §6.6):

- **Write-path partitioning is the gate**: if subagents would touch the same file, they MUST coordinate at the proposal level (split the file into parts; assign disjoint paths) — not at commit time.
- **The skill `openspec-apply-parallel`** runs the gating questions automatically. Its decision tree is the authority.
- **Recombination phase**: after subagents finish their groups, a single recombination commit lands on the branch. That commit may resolve any residual cross-group conflicts (typically import-order tweaks, shared-helper signatures).
- **If recombination fails (>10 lines conflict between subagents)**: fall back to sequential (`/opsx:apply` instead of `/openspec-apply-parallel`). Don't try to power through.

---

## 7. When the policy itself is in conflict

If two policies in the playbook give different guidance (e.g. "merge-policy says squash, but the maintainer's hot-fix runbook says merge-commit"):

- **Most-specific wins**: domain runbook > spec > general doc.
- **Document the override**: any deviation from the canonical policy lands a `# OVERRIDE: <reason>` comment in the relevant commit / spec section.
- **Retro it**: persistent overrides surface in the monthly retro per [retrospective-cadence.md](retrospective-cadence.md).

---

## 8. Cross-references

- [`docs/development-flow.md`](../docs/development-flow.md) §2 (parallelism) — referrer.
- [`specs/release-management.md`](release-management.md) §6.4 (Wave-N) and §6.6 (intra-slice).
- [`specs/merge-policy.md`](merge-policy.md) — what merge style after rebase.
- [`specs/break-glass.md`](break-glass.md) — `--force-with-reason` for skipping a step under explicit override.
- [`specs/retrospective-cadence.md`](retrospective-cadence.md) — surfacing repeated overrides.
- [`runbooks/git-worktree-bare-setup.md`](../runbooks/git-worktree-bare-setup.md) — operational mechanism for Wave-N work.
- [`skills/openspec-apply-parallel/SKILL.md`](../skills/openspec-apply-parallel/SKILL.md) — intra-slice gating questions.

---

## 9. Decisions

- **D3.1** Second-merger rebases. Rationale: conflict-cost incentives reward rapid review cycles; languishing PRs lose priority.
- **D3.2** 5-line / 3-marker threshold for escalation. Rationale: empirical — below this, ad-hoc resolution preserves intent; above, explicit coordination prevents drift.
- **D3.3** T4 (architectural) conflicts stop BOTH PRs. Rationale: shipping competing designs in parallel guarantees one of them is eventually deleted; the cost of premature design-lock is lower than the cost of competing implementations on main.
- **D3.4** Wave coordinator role activates at N=3. Rationale: below 3, ad-hoc rebase suffices; quadratic conflict growth above 3 justifies coordinator overhead.
- **D3.5** Intra-slice partitioning is gating, not corrective. Rationale: trying to recombine subagents that wrote to the same path always loses information; partition at proposal time or fall back to sequential.
- **D3.6** The policy itself can be overridden, but with documentation + retro surfacing. Rationale: rigid policies that don't allow exceptions accumulate break-glass usage; explicit override-with-reason is the audit-able path.
