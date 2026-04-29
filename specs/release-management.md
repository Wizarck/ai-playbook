# release-management.md

> **Status**: v1.0.0. New in ai-playbook v0.8.0-rc1. Defines the universal contract for **how OpenSpec changes ship**: branch model, PR shape, CI gates, project board schema, and dependency-driven merge order. Complements [issue-tracking.md](issue-tracking.md) (which automates ticket↔proposal sync) by codifying the source-control + review side that issue-tracking assumes but does not normatively specify.

## 1. Why this spec

`runbook-bmad-openspec.md` §3 says "implementation in `slice/<id>` branch" and §5 lists Gate F as "implementation diff + tests pass + retro notes drafted", but never normatively answers:

- Is each `tasks.md` checkbox a separate branch + PR, or do all tasks of a change ship in one PR?
- What is the canonical Status field schema for a project board tracking OpenSpec changes?
- When does a PR move from "In Progress" to "Review"? What does CI need to be green for?
- How does the dependency graph in `docs/openspec-slice.md` translate to merge ordering?
- How does a fresh consumer project bootstrap its GH Project board with the right fields?

The implicit answers exist in `issue-tracking.md` (status states, automation hooks) and `bmad-openspec-bridge.md` (dependency graph in slicing), but the source-control / PR / CI side is undocumented. That gap surfaced concretely in `iguanatrader` 2026-04-29 when a contributor asked whether each `tasks.md` task should be its own branch — because the existing specs do not say.

This spec closes the gap with one normative answer per question.

---

## 2. Branch model

### 2.1 Hard rule: **1 branch = 1 OpenSpec change = 1 PR**

The atomic unit of release is the **OpenSpec change** (one row in `docs/openspec-slice.md`), NOT the individual task in `tasks.md`. Each change owns one feature branch, named `slice/<change-id>` (the kebab-case folder name under `openspec/changes/`), which targets `main` (or the consumer's release-receiving branch) via exactly **one** pull request.

Within that branch, individual tasks are tracked as a markdown checklist in the PR description (copied verbatim from `tasks.md`), ticked off as commits land. Reviewers see incremental progress via the PR's commit log; they approve the change **once**, at the end, when CI is green and all checkboxes are ticked.

### 2.2 Anti-pattern: per-task branches

Splitting a change's 50-task list into 50 branches + 50 PRs is **forbidden** because:

- Tasks within a change are interdependent (you cannot validate task 1.5 "make bootstrap idempotent" before tasks 1.1-1.4 land); merging task 1.1 alone gives `main` a half-built capability.
- N PRs per change × M changes per project = O(N×M) reviewer cognitive load; the slicing artefact already chose change-level granularity precisely to keep N×M tractable.
- The squash-merge at change-archive time (per [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §3.1 step 6) becomes meaningless if the change is already split across multiple merged PRs.

If a "task" turns out to be large enough to warrant its own PR, that is a **slicing failure** — re-open Gate C, split the change into two changes in `docs/openspec-slice.md`, and proceed with the new change-level granularity.

### 2.3 Branch lifecycle

```
main
 │
 ├─► slice/<change-id>   (created at /opsx:apply <change-id>)
 │      │
 │      ├─ commit ... task 1.1 done
 │      ├─ commit ... task 1.2 done
 │      ├─ ... incremental commits, each ticking checkboxes ...
 │      ├─ commit ... task N done; CI green
 │      │
 │      ▼
 │   PR opened, Status → "Review"
 │      │
 │      ▼ Gate F (human approves implementation diff + retro draft)
 │      │
 │      ▼ squash-merge to main; branch deleted; worktree torn down
 │
 ▼
main now contains the change in one squashed commit (atomicity preserved)
```

### 2.4 Worktree isolation

Each `slice/<change-id>` branch is created via `git worktree add ../<consumer>-<change-id> -b slice/<change-id> main` so multiple changes can be implemented in parallel (Wave 2/3/4 of the slicing artefact) without `cd` thrash or accidental cross-branch contamination. The Agent tool's `isolation: "worktree"` mode is the canonical way to spawn a worker subagent into the worktree.

---

## 3. PR shape

### 3.1 Title

Format: `<type>(<change-id-short>): <one-line summary> (slice <N>/<total>)`

- `<type>` per [Conventional Commits](https://www.conventionalcommits.org/) (typically `feat`, `fix`, `chore`).
- `<change-id-short>` may abbreviate the full change-id if it would push the title past 70 chars (e.g. `bootstrap-monorepo` → `bootstrap`).
- `<N>/<total>` references the slice number and total from `docs/openspec-slice.md` (e.g. `slice 1/20`).

Example: `feat(bootstrap): monorepo skeleton + tooling baseline (slice 1/20)`.

### 3.2 Body sections

The PR body is structured (parsable by automation) and contains exactly:

```markdown
## Summary
<2-4 bullets, the "what changed" — copied from proposal.md "What Changes" section>

## Acceptance criteria (from tasks.md)
<verbatim copy of tasks.md, with checkboxes; ticked as commits land>

## Specs implemented
<list of specs/<capability>/spec.md files added or modified>

## Dependency check
- Depends on: <change-ids from docs/openspec-slice.md row, or "—">
- All dependencies merged to main? <yes / no — if no, this PR cannot be merged yet>

## Test plan
<how the reviewer can manually verify, beyond CI>

## References
- Slice plan: docs/openspec-slice.md row <N>
- Gate E approval: docs/hitl-gates-log.md (date)
```

The "Acceptance criteria" section is the live progress tracker. The PR cannot move to "Review" until every checkbox is ticked AND CI is green (see §4).

### 3.3 Linked tracker ticket

Per [issue-tracking.md](issue-tracking.md) §2.2, the change's `proposal.md` carries `tracker_id: PROJ-N` (Jira) or `tracker_issue: N` (GH). The PR body MUST reference it via `Closes #N` (GH) or `PROJ-N:` prefix in the title (Jira). This drives automatic ticket transitions on merge.

---

## 4. CI gates

### 4.1 Mandatory CI for slice-branch PRs

A consumer project's `.github/workflows/ci.yml` (or equivalent) MUST run, at minimum:

- Lint (language-appropriate: ruff, eslint, etc.).
- Type check (mypy --strict, tsc --strict, etc.).
- Unit + integration tests.
- Secrets scan (gitleaks).
- Pre-commit hooks dry-run on changed files.

Project-specific extensions (license-boundary check, lighthouse-perf, contract tests) layer on top.

### 4.2 Status transition: In Progress → Review requires CI green

The PR's Project Status field stays `In Progress` until CI passes on the latest commit. Only then does it move to `Review` (manually, or automated via `.github/workflows/project-status.yml` — see §6). A red CI cannot be hand-waved into Review; if the CI failure is environmental (flake), the fix is to re-run CI after addressing the flake's root cause, not to bypass the gate.

### 4.3 Status transition: Review → Done requires Gate F + squash-merge

`Review → Done` happens automatically on squash-merge to `main`. Gate F (human approval per [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §5) is the **prerequisite** for the merge itself, not a separate field transition.

---

## 5. Project board schema

### 5.1 Status field (mandatory, single-select)

Every consumer project's GitHub Project (per [issue-tracking.md](issue-tracking.md) §1) MUST have a `Status` field with **exactly these five options** in this order:

| Option | Meaning | Entered when |
|---|---|---|
| `Todo` | Ready to start; dependencies satisfied. | Item created OR dependency closes Done. |
| `Blocked` | Has unresolved dependency in the slicing graph (or `❓ CLARIFICATION NEEDED` verdict). | Dependency exists in `Todo`/`In Progress`/`Review`; QA emits `❓`. |
| `In Progress` | `slice/<id>` branch exists; commits landing. | `/opsx:apply <change-id>` runs. |
| `Review` | PR open + CI green. | Last commit's CI run passes. |
| `Done` | Squash-merged to main + archived (`/opsx:archive`). | Squash-merge completes. |

Renaming options ("In review" instead of "Review", "Open" instead of "Todo") is **forbidden** because automation in `scripts/issue_sync.py` and downstream tooling references these names verbatim. If a project needs additional states (e.g. `Deployed` for a separate post-merge phase), they go AFTER `Done`, never as renames or replacements.

### 5.2 Custom fields (recommended)

Two single-select fields are recommended on every project board for prioritisation visibility:

| Field | Options | Purpose |
|---|---|---|
| `Risk` | `Low`, `Medium`, `High` | Reviewer-time allocation; high-risk slices warrant deeper QA. Set at Gate C slicing time. |
| `P&L impact` | `None`, `Low`, `Medium`, `High` | Business-side stack-ranking (consumer-discretionary; some projects have no P&L surface). |

Additional fields (`MVP Milestone`, `Sprint`, etc.) are consumer-discretionary and not normative.

### 5.3 Project items: one per OpenSpec change

The project board contains **one item per row** in `docs/openspec-slice.md`. Items are created at Gate C slicing time (or auto-synced by `scripts/issue_sync.py` when a `proposal.md` lands). Items are **not** created per-task — tasks live as the PR description checklist (per §3.2).

### 5.4 Initial Status assignment per slicing graph

When `docs/openspec-slice.md` is approved at Gate C, the bootstrap script assigns initial Status:

- Wave 0 first slice (the foundation, e.g. `bootstrap-monorepo`) → `Todo`.
- All other slices → `Blocked` (their `Depends on` column references something not yet `Done`).
- As each slice progresses through `In Progress → Review → Done`, downstream slices whose dependencies all become `Done` auto-transition `Blocked → Todo`.

This is enforced by the `.github/workflows/project-status.yml` template at §6.

---

## 6. Dependency-driven merge order

### 6.1 Source of truth: `docs/openspec-slice.md` `Depends on` column

The dependency graph from the slicing artefact is the merge-order contract. Wave 0 → Wave 1 → Wave 2 → Wave 3 → Wave 4 (where wave N items only run after their declared deps from wave M<N are merged). Concrete example from `iguanatrader`:

```
Wave 0 (sequential):  bootstrap-monorepo → shared-primitives → persistence-tenant-enforcement
Wave 1 (parallel ×2):  auth-jwt-cookie  ║  api-foundation-rfc7807   (after Wave 0)
Wave 2 (parallel ×6):  6 bounded-context bootstraps                   (after Wave 1)
Wave 3 (parallel ×7):  7 adapter / strategy slices                     (after Wave 2)
Wave 4 (parallel ×2):  2 consolidation slices                          (after Wave 3)
```

### 6.2 Merge enforcement

A PR for slice X cannot squash-merge until every change-ID in X's `Depends on` column is present on `main` (i.e. has Status `Done` on the project board). Two enforcement mechanisms:

- **Soft (default)**: PR description's "Dependency check" section (per §3.2) declares the deps; reviewer manually verifies. Reviewer rejects the PR if any dep is unmerged.
- **Hard (optional)**: `.github/workflows/dep-check.yml` parses `docs/openspec-slice.md`, looks up the PR's slice ID, walks the dep graph against `main`, fails the workflow if any dep is missing.

Hard enforcement is OPT-IN per consumer (some projects have lightweight slicing where soft is enough). The script template ships in `templates/new-project/.github/workflows/dep-check.yml.tmpl`.

### 6.3 Auto-transition `Blocked → Todo`

When a slice merges to `main` (`Done`), downstream slices whose entire `Depends on` set is now `Done` auto-transition from `Blocked` to `Todo`. The `.github/workflows/project-status.yml` template at `templates/new-project/.github/workflows/project-status.yml.tmpl` ships the GraphQL automation.

This avoids the human-tracker-drift failure mode where Wave 2 slices stay `Blocked` long after Wave 1 merged.

---

## 7. Bootstrap automation

A consumer project that adopts this contract for the first time runs **one** command to set up the project board with the correct schema:

```bash
python .ai-playbook/scripts/bootstrap_gh_project.py \
    --owner <gh-user-or-org> \
    --project-number <existing-project-id-or-new-name> \
    --slicing-file docs/openspec-slice.md
```

The script (per [`scripts/bootstrap_gh_project.py`](../scripts/bootstrap_gh_project.py)):

- Looks up or creates the project under the given owner.
- Adds the canonical Status field options (`Todo`, `Blocked`, `In Progress`, `Review`, `Done`) — idempotent (existing options preserved; missing ones added; names verified against §5.1; rename-divergence emits a warning that the human must resolve).
- Adds the recommended custom fields (`Risk`, `P&L impact`) — idempotent, with `--no-custom-fields` to opt out.
- Reads `docs/openspec-slice.md`, creates one project item per change row (or one GH Issue per change + adds the issue to the project, depending on `--issue-mode`).
- Sets initial Status: Wave 0 first slice → `Todo`; rest → `Blocked`.

Re-running the script after later edits to `docs/openspec-slice.md` adds new items / updates dependencies without dropping existing in-progress items. Removed-from-slicing items emit a warning (manual cleanup required to avoid losing review history).

---

## 8. Migration for existing consumers

Existing consumer projects on ai-playbook v0.7.x that adopt this contract follow:

1. **Audit**: list current project board fields. If Status options diverge from §5.1, plan a rename pass (one PR per consumer, since Status field rename can break external bookmarks).
2. **Run bootstrap**: `python .ai-playbook/scripts/bootstrap_gh_project.py --owner <user> --project-number <existing> --no-create-items` (no-create-items mode aligns just the schema, not the items).
3. **Update consumer's `AGENTS.md`**: add `release_management: .ai-playbook/specs/release-management.md` to the inherited specs list (or the project's `inherits_from` reference, depending on the consumer's `AGENTS.md` shape).
4. **Bump submodule pointer** to v0.8.0-rc1 (or the eventual v0.8.0 stable).

Consumer projects on v0.8.0+ inherit this spec automatically; new consumers bootstrapped via `scripts/bootstrap.py` get the AGENTS.md template that already references it.

---

## 9. Anti-patterns

- **Per-task branches**: forbidden per §2.2.
- **Skipping CI for "trivial" changes**: every PR runs full CI; no opt-out for "just docs" or "just config" — language-specific lints + secrets scan apply universally.
- **Closing the change ticket without merge**: `Done` Status is reserved for actually-merged-to-main work. Items archived without merge land in `Cancelled` (custom Status option that consumer may add AFTER `Done`).
- **Cross-PR rebase chains**: do NOT branch slice 5 off slice 4's branch. Each slice branches off `main` (after its dependencies have merged). Cross-PR chains turn into rebase nightmares + force-pushes that reviewers cannot follow.
- **Reusing a slice/<id> branch after merge**: slice branches are deleted post-squash-merge. If new work is needed for the same change, that is a re-slice (new change-id, new branch).

---

## 10. Cross-references

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §3 — OpenSpec lifecycle this spec governs the source-control side of.
- [issue-tracking.md](issue-tracking.md) — ticket↔proposal automation (Jira / GH Issues); this spec extends to the source-control side.
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3 — slicing artefact schema this spec depends on for dep-graph parsing.
- [verdict-contract.md](verdict-contract.md) — `❓ CLARIFICATION NEEDED` triggers Status `Blocked`.
- [agentic-failures.md](agentic-failures.md) — `goal_drift` if a worker creates a per-task branch.
- [break-glass.md](break-glass.md) — Gate F can be overridden with `--force-with-reason` in genuine emergencies; CI green and dependency-merged are NEVER overridable (red CI = real signal; missing dep = wrong order).
