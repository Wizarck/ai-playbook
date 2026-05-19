# development-flow.md

> **Status**: v1.0.0. Authored under OpenSpec change `industrialize-dev-flow` (Phase 5 wave 2) on 2026-05-05. **LLM-agnostic** — applies to Claude Code, Cursor, Antigravity, Gemini CLI, OpenCode, and humans equally.
>
> This is the **canonical entry point** for "how do I make a change in any playbook-consuming project?". Every other doc / spec on the topic points HERE; this doc points OUT to specific specs for detail. If you read one document before starting work, read this one.

The playbook formalises a development flow that scales from solo work to multiple agents and humans collaborating on the same project without coordination overhead. This document maps the canonical hierarchy, the parallelism modes, and the entry/exit points so any actor (human or LLM) can pick the right path the first time.

---

## TL;DR — the rules, in one paragraph

**A unit of work is an OpenSpec change.** One change = one branch = one PR with N semantic commits. Branch name encodes the change ID (`feat/<change-id>`). Each commit message updates `tasks.md` checkboxes (auto-ticked from the conventional commit subject). PRs target `main`; main is always green and always mergeable but **not always released**. Releases are tags (`vX.Y.Z`) cut when the maintainer decides the accumulated PRs in main constitute a coherent shippable unit. Tag pushes trigger automatic propagation to consumer repos.

That's the whole flow. The rest of this doc explains the parts and points at where each is enforced.

---

## 1. The four-level hierarchy

```
ROADMAP                                   specs/v0.9.0-roadmap.md
  └── PHASE / WAVE / SLICE                docs/openspec-slice-phase5.md
        │
        ▼
OPENSPEC CHANGE  ◄────────────────────── THE UNIT OF WORK
  • openspec/changes/<change-id>/
  •   proposal.md   problem + approach + decisions (Dx.y)
  •   tasks.md      granular checklist `- [ ]` per implementable step
  •   specs/        deltas to playbook specifications
  See: specs/runbook-bmad-openspec.md
        │
        ▼
BRANCH (one OpenSpec change = one branch)
  • Naming: `<type>/<change-id>` where type ∈ {feat, fix, chore, docs, refactor}
  • Lives in its own worktree (when ≥ 3 concurrent slices)
  See: specs/git-worktree-bare-layout.md, runbooks/git-worktree-bare-setup.md
        │
        ▼
COMMITS (multiple, semantically distinct)
  • Conventional commits (feat:, fix:, docs:, chore:, refactor:, test:)
  • One commit = one logical step within the change
  • Commit subject auto-ticks matching tasks.md checkboxes
  See: scripts/auto_tick_tasks.py + .git/hooks/prepare-commit-msg
        │
        ▼
PULL REQUEST (one branch = one PR, base: main)
  • CI: ruff + pytest 3.11 + pytest 3.12 + CodeRabbit + 3-layer review
  • Merge style: merge-commit (multi-commit) | squash (trivial single-commit)
  See: specs/merge-policy.md, specs/parallel-review.md
        │
        ▼
MAIN (accumulating PRs for the next release tag)
  • Always green (CI passes), always mergeable
  • Merge to main ≠ release. Many PRs may accumulate between releases.
  • Tagging is a separate operation, not auto-triggered by merge.
        │
        ▼
TAG  ◄──────────────────────────────── THE RELEASE EVENT
  • git tag -a vX.Y.Z + push tag
  • Triggers .github/workflows/propagate-playbook-bump.yml
  • Which opens `chore(playbook): bump to vX.Y.Z` PRs in every consumer
  See: runbooks/release.md, scripts/release_cut.py, scripts/propagate_bump.py
        │
        ▼
CONSUMERS (eligia-core, nexandro, palafito-b2b, iguanatrader, livekit, …)
  • Auto-PR opens with submodule pin bump + AGENTS.md cross-ref refresh
  • Consumer mergers → consumer is on the new playbook version
  See: specs/projects-registry.md, consumers.yaml, scripts/bump_consumers.py
```

The hierarchy is **strict**: every commit is inside a branch, every branch is inside a PR, every PR maps to one OpenSpec change, every change is part of a slice/wave/phase in the roadmap. CI gates enforce each level (see §5).

---

## 2. The three axes of parallelism

Three orthogonal mechanisms let multiple agents/humans work concurrently without stepping on each other. Use the smallest one that fits your scenario.

### Axis 1 — Wave-N (between independent OpenSpec changes)

**Spec**: [release-management.md §6.4](../specs/release-management.md)

**When**: you have ≥ 3 OpenSpec changes that touch disjoint capabilities (e.g. `add-litellm-enforcement` + `complete-ir-and-model-migration-specs` + `extend-vps-maintainer` — none of them write to the same files).

**How**: each change in its own worktree + branch + PR. Open all in parallel. Merge in any order. The maintainer (Profile A) cuts a release tag once the wave is complete.

**Limit**: max ~3-5 concurrent waves before review fatigue dominates. Beyond that, batch them into the next release cycle.

### Axis 2 — Intra-slice (within one OpenSpec change)

**Spec**: [release-management.md §6.6](../specs/release-management.md) + skill [`openspec-apply-parallel`](../skills/openspec-apply-parallel/SKILL.md) (added v0.9.2)

**When**: a single OpenSpec change has `tasks.md` groups with disjoint write-paths (canonical example: a slice that scaffolds 5 bounded contexts under `apps/api/src/` — `iam/`, `ingredients/`, `suppliers/`, `cost/`, `shared/uom/`).

**How**: one subagent per group. All commit to the same branch. Recombination at the end (one final PR). Use the skill `/openspec-apply-parallel <change-id>` to drive the gating questions, ownership cross-check, and spawn matrix.

**Gating questions** (from §6.6):
- Are the task groups *write-path disjoint*? If any two groups would touch the same file, fall back to sequential.
- Is the change ≥ 4 logical groups? Below 4, sequential overhead < parallel coordination overhead.
- Are dependencies clear (which groups can run before which)? If a DAG isn't explicit, sequential is safer.

When the gating questions don't pass, fall back to `/opsx:apply` (sequential).

### Axis 3 — Worktrees (the operational base for both)

**Spec**: [git-worktree-bare-layout.md](../specs/git-worktree-bare-layout.md) + [runbook git-worktree-bare-setup.md](../runbooks/git-worktree-bare-setup.md) + script `scripts/wt_add.py`

**When**: ≥ 3 slices concurrent (axis 1) OR ≥ 4 groups in one slice (axis 2). Below those thresholds, single working tree is simpler.

**How**: bare repository + one worktree per branch. Each worker (agent or human) operates in their own folder; no `git stash` dance, no branch-switching context loss. `wt_add.py` post-creates: ecosystem deps installed (npm/pnpm/poetry/uv) + submodules initialised (added in v0.9.3 / PR #32).

### Decision table

| Scenario | Use |
|---|---|
| 1 agent, 1 OpenSpec change at a time | trunk-based, single working tree, no parallelism |
| ≥ 3 OpenSpec changes, disjoint scope | Axis 1 (Wave-N) + Axis 3 (worktrees) |
| 1 OpenSpec change, 5 bounded contexts | Axis 2 (intra-slice) — single branch, multiple subagents |
| 2 humans on same project, different topics | Axis 1 + Axis 3 |
| 1 human + 1 LLM agent on different changes | Axis 1 + Axis 3 |
| Hot patch on prod (no OpenSpec ceremony) | `fix/<short-id>` branch + minimal PR; archive proposal post-hoc |

**The 5-min decision rule**: if you spend > 5 min deciding which axis to use, your scope is wrong. Either the change is too big (split it into N OpenSpec changes — Axis 1) or you're not paralleling enough (within the change groups — Axis 2). Sequential default is always valid; complexity is opt-in.

---

## 3. The lifecycle (from "I want to change something" to "consumers are on the new version")

### 3.1 Decide the scope

1. Is this change ≤ 5 lines + obvious + zero blast radius? → **trivial fix path**. `fix/<short-id>` branch, no OpenSpec change required, single commit, squash-merge to main.
2. Otherwise: **OpenSpec change path** (the canonical flow).

Any agent (LLM) following this doc that decides "trivial" path MUST justify in PR description; reviewer can require promotion to OpenSpec change if scope was misjudged.

### 3.2 OpenSpec change path

```
Author proposal:        openspec/changes/<change-id>/proposal.md
                        problem + approach + decisions
                        See: skill `openspec-propose`
                          ▼
Author tasks.md:        openspec/changes/<change-id>/tasks.md
                        granular `- [ ]` checklist
                          ▼
Create branch:          git checkout -b <type>/<change-id> [main]
                        (or wt_add.py for worktree-based)
                          ▼
Implement + commit:     conventional commit subjects auto-tick boxes
                        in tasks.md (prepare-commit-msg hook + scripts/auto_tick_tasks.py)
                          ▼
Open PR:                gh pr create --base main --title "..." --body "..."
                          ▼
CI runs:                ruff → pytest 3.11/3.12 → CodeRabbit → bmad-code-review
                          ▼
Address review:         additional commits as needed (preserve semantic history)
                          ▼
Merge:                  merge-commit if ≥ 2 commits, squash if 1 trivial commit
                        (See specs/merge-policy.md)
                          ▼
Archive:                openspec archive <change-id>
                        Verifies tasks.md is N/N ticked (CI gate check-tasks-checkboxes.yml)
                          ▼
Branch deleted          (auto via gh pr merge --delete-branch)
```

### 3.3 Release path

When the maintainer (Profile A — see [`specs/role-matrix.md`](../specs/role-matrix.md)) decides the accumulated PRs in main are a coherent release:

```
Release-prep PR:        chore(release): vX.Y.Z
                        - bump VERSION
                        - update CHANGELOG.md (consolidated notes from all PRs)
                          ▼
Merge release-prep      to main
                          ▼
Tag + push:             git tag -a vX.Y.Z -m "..." + git push origin vX.Y.Z
                          ▼
Workflow fires:         .github/workflows/propagate-playbook-bump.yml
                          ▼
Per-consumer PRs:       chore(playbook): bump to vX.Y.Z
                        - submodule pin updated
                        - AGENTS.md cross-refs auto-migrated (if applicable)
                          ▼
Consumers merge         to land on the new playbook version
                          ▼
OpenSpec archive:       in each consumer where the change applied,
                        `openspec archive <change-id>` retires the proposal
```

Release timing is a **policy decision**, not auto-cut. See [release-management.md §3](../specs/release-management.md) for criteria (semver discipline, CHANGELOG quality, breaking-change review).

---

## 4. What lives where (LLM-agnostic pointer table)

If you're an agent (any LLM) bootstrapping into a project, this is your map. Read top-to-bottom; deeper specs pull from the level above.

| Level | Question you'd ask | Doc / Spec | Location |
|---|---|---|---|
| L0 | What is this project? | `AGENTS.md` (project root) | per-project |
| L1 | How do I make any change? | **THIS DOC** (`development-flow.md`) | `.ai-playbook/docs/` |
| L2 | What's the OpenSpec workflow? | `runbook-bmad-openspec.md` | `.ai-playbook/specs/` |
| L2 | How do branches/PRs/releases work? | `release-management.md` | `.ai-playbook/specs/` |
| L2 | When do I parallelise? | `release-management.md §6.4 §6.6` + this doc §2 | `.ai-playbook/specs/` |
| L3 | How do I bootstrap a worktree? | `git-worktree-bare-setup.md` | `.ai-playbook/runbooks/` |
| L3 | When squash vs merge-commit? | `merge-policy.md` | `.ai-playbook/specs/` |
| L3 | Who resolves conflicts? | `conflict-resolution-policy.md` | `.ai-playbook/specs/` |
| L3 | What's the verdict shape? | `verdict-contract.md` | `.ai-playbook/specs/` |
| L3 | What CI gates fire? | `enforcement-status.md` | `.ai-playbook/specs/` |
| L3 | How does break-glass work? | `break-glass.md` | `.ai-playbook/specs/` |
| L3 | What channels for notifications? | `notification-policy.md` | `.ai-playbook/specs/` |

CLI-specific routers (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/`) are **thin pointers to AGENTS.md** — they never carry content of their own. The playbook is LLM-agnostic by construction.

---

## 5. Industrialisation — what's enforced vs what's convention

Following [`specs/enforcement-status.md`](../specs/enforcement-status.md) shape:

| Discipline | Enforcement | Where |
|---|---|---|
| 1 PR = 1 OpenSpec change | ✅ wired | `.github/workflows/branch-name-validator.yml` (validates `<type>/<change-id>` + `openspec/changes/<change-id>/` exists) |
| `tasks.md` boxes ticked on archive | 🟡 partial | (1) `scripts/auto_tick_tasks.py` invoked by `prepare-commit-msg` hook auto-ticks from conventional commit subject; (2) `.github/workflows/check-tasks-checkboxes.yml` warns at PR-open if `<X> of N` unchecked. Hard `openspec archive --strict` deferred per Followup #4 §3 |
| AGENTS.md cross-ref to dev-flow | 🟠 wired-pending-trigger | `agents-md-v1.schema.json` flag `dev_flow_cross_ref` (warn-only initially, promote to required after 30d green per change C pattern). Migration via `propagate_bump.py` extended (Opción 1) |
| Branch naming | ✅ wired | `branch-name-validator.yml` |
| Conventional commits | 📋 spec-only | Convention; commit-lint hook recommended but not enforced |
| Merge style (squash vs merge-commit) | 🟡 partial | `pr-merge-style.yml` advisor comments on PRs; no hard block. See `merge-policy.md` |
| Schema-validate AGENTS.md | ✅ wired | `schema_validate.py` (pre-commit + CI + bootstrap) |
| OpenSpec block-manual-spec-edit | ✅ wired | `block_manual_spec_edit.py` (pre-commit) |
| Verdict + severity (S1-S4) | ✅ wired | `verdict_lint.py` |
| Drift LLM routing | 🟡 warn-only | `verify_llm_routing.py` (warn-only window 30d → strict per D3.5) |
| Notification policy 4 levels | ✅ wired | `notify.py` |
| 7-day post-mortem trigger | 🟠 wired-pending-trigger | `lifecycle_check.py` |
| Consumer-side playbook zombie cleanup | 🟡 partial | `scripts/cleanup_zombies.py` + declarative manifest `specs/zombies-manifest.yaml` + hook templates `templates/new-project/scripts/git-hooks/{post-merge,post-checkout}.tmpl`. Auto-fires on consumer `git pull` / `git checkout`. Status flips ✅ when ≥ 1 consumer adopts and reports a quiet 30-day window. v0.15.0. |
| Doc-drift on paired (code, doc) tuples | ✅ wired | `scripts/check_doc_drift.py` + declarative manifest `specs/co-edit-pairs.yaml` + CI workflow `.github/workflows/doc-drift-check.yml` (sticky PR comment + hard fail). Fires on every PR. Escape hatch: `[no-doc-impact]` (case-insensitive) anywhere in PR title; logged for slice 6 telemetry. v0.16.0. |

**Status legend** (per [enforcement-status.md](../specs/enforcement-status.md)):
- ✅ wired — code + tests + pre-commit/CI fires it
- 🟡 partial — some enforcement, gaps named
- 📋 spec-only — convention, no automation
- 📌 deferred — activates on documented trigger
- 🟠 wired-pending-trigger — runnable but pending real activation event

---

## 6. The skill orchestrator (Nivel 3, deferred to v0.9.4)

A future `skills/dev-flow/SKILL.md` (deferred to PR #34) will package this entire flow as `/dev-flow start <description>` and `/dev-flow ship` commands so an LLM agent can execute the canonical path without re-reading 5+ specs each time. Not yet shipped — agents follow this doc by hand for now.

---

## 7. Anti-patterns — common ways to drift off the canonical flow

Document these so future agents (and humans) recognise them:

- **Bypassing OpenSpec for a "quick fix" that's actually 80 lines.** If your "fix" creates new files, deletes existing files, or touches > 50 lines: it's an OpenSpec change. Promote it.
- **Squashing a multi-commit PR with semantic history.** Squash collapses authorial intent. Reserve squash for trivial single-commit PRs (typo, doc fix, lint cleanup). See `merge-policy.md`.
- **Merging to main without CI green.** Pre-commit hooks are the floor, not the ceiling. CI must pass before merge regardless of local pre-commit.
- **Committing with `tasks.md` boxes 0/N ticked.** Filed as Followup #4 from iguanatrader slice 3 (PR #57). Auto-tick + CI warning prevent recurrence.
- **Tagging a release without consolidated CHANGELOG.** A tag without notes is invisible to consumers; they merge a bump PR with no context.
- **Manual edits to `openspec/specs/*.md` outside an `openspec-archive:` commit.** Caught by `block_manual_spec_edit.py`. Use OpenSpec workflow.
- **Cherry-picking commits across PRs to "consolidate".** Loses CI history per PR. Open one PR per logical unit; merge all to main; tag when bundle is coherent.
- **Branch named `feature-thing` (no slash, no change-id).** Caught by `branch-name-validator.yml`.

---

## 8. Cross-references

- [`specs/release-management.md`](../specs/release-management.md) — Sections §3 (semver), §4 (PR shape + AI-reviewer feedback loop), §5 (Profile A/B), §6.4 (Wave-N), §6.5 (pre-flight rebase), §6.6 (intra-slice).
- [`specs/runbook-bmad-openspec.md`](../specs/runbook-bmad-openspec.md) — BMAD discovery → OpenSpec implementation flow.
- [`specs/git-worktree-bare-layout.md`](../specs/git-worktree-bare-layout.md) — bare-repo + per-branch worktree layout.
- [`runbooks/git-worktree-bare-setup.md`](../runbooks/git-worktree-bare-setup.md) — operational procedure for worktree management.
- [`specs/merge-policy.md`](../specs/merge-policy.md) — squash vs merge-commit decision rules.
- [`specs/conflict-resolution-policy.md`](../specs/conflict-resolution-policy.md) — what to do when two PRs collide.
- [`specs/parallel-review.md`](../specs/parallel-review.md) — 3-layer review (blind / edge case / adversarial).
- [`specs/enforcement-status.md`](../specs/enforcement-status.md) — what's wired vs spec-only.
- [`specs/agents-md-v1.schema.json`](../specs/agents-md-v1.schema.json) — frontmatter contract.
- [`specs/projects-registry.md`](../specs/projects-registry.md) — `~/.ai-playbook/projects.yaml` schema.
- [`specs/v0.9.0-roadmap.md`](../specs/v0.9.0-roadmap.md) — Followup #4 (task-checkbox enforcement).
- [`runbooks/release.md`](../runbooks/release.md) — release cut + propagation runbook.
- [`runbooks/onboard-new-project.md`](../runbooks/onboard-new-project.md) — bootstrap a new playbook consumer.
- [`skills/openspec-apply-parallel/SKILL.md`](../skills/openspec-apply-parallel/SKILL.md) — intra-slice parallelism (Axis 2).

---

## 9. Decisions

- **D1.1** This doc lives in `docs/` (onboarding) not `specs/` (enforcement). Rationale: it's a navigational hub. Enforcement lives in the specs it points to.
- **D1.2** LLM-agnostic — no `~/.claude/CLAUDE.md` or `~/.gemini/GEMINI.md` references. Pointers go through `AGENTS.md` (project) and `AGENTS.md.tmpl` (template). Rationale: per `README.md` ("LLM-agnostic. Norms live in AGENTS.md + specs/; CLI-specific routers are thin pointers"), CLI-home dispatchers are not the right surface.
- **D1.3** Single canonical entry point. Other docs/specs MUST link here when discussing the dev flow; this doc points OUT to specifics. Rationale: readers shouldn't have to guess which of 5+ docs is the starting point.
- **D1.4** Sequential is the default; parallelism is opt-in. Rationale: the cost of coordination overhead at low N exceeds the wall-clock savings; only graduate to parallel axes when scope justifies.
- **D1.5** "Trivial fix" path documented but bounded. Rationale: a PR that bypasses OpenSpec ceremony for a 200-line refactor is a process violation; the threshold (≤ 5 lines + obvious + zero blast radius) is conservative on purpose.
