# release-management.md

> **Status**: v1.2.0 (new in v0.8.1). Defines the universal contract for **how OpenSpec changes ship**: branch model, PR shape, CI gates, project board schema, dependency-driven merge order, the **visibility-driven enforcement profile** (public-OSS vs private-solo), and the **AI-reviewer feedback loop** (CodeRabbit / claude-code-action). Complements [issue-tracking.md](issue-tracking.md) (which automates ticket↔proposal sync) by codifying the source-control + review side that issue-tracking assumes but does not normatively specify.
>
> **Changelog**:
> - **v1.2.0** (2026-05-01): added §4.5 (AI-reviewer feedback loop) — worker AI MUST read + respond to AI-reviewer comments (CodeRabbit on Profile A, claude-code-action when Phase 3 lands) before requesting Gate F. Closes the gap surfaced when the v0.8.0 rollout itself admin-merged 5 PRs without checking CodeRabbit's feedback (rate limit was hit; no real comments missed, but the FLOW was the failure mode).
> - **v1.1.0** (2026-05-01): added §5.5 (trace fields Branch + Base SHA), §5.6 (visibility-driven profile A/B), §4.4 (pre-commit diff mode in CI), §6.5 (pre-flight rebase before slice start), §3.4 (bump-bot supersede expectation). `bootstrap_gh_project.py` gains `--profile {auto,public,private}`.
> - **v1.0.0** (2026-04-29): initial spec — branch model, PR shape, CI gates, project board schema, dependency-driven merge order, bootstrap automation.

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

## AI-reviewer signoff
- **Reviewer**: <CodeRabbit | claude-code-action | self-review (Profile B)>
- **Status**: <X actionable / Y addressed / Z rejected with reason / W deferred to follow-up>
- **Notes**: <free-form: link to deferred items, rejected-with-reason justifications, etc.>

## References
- Slice plan: docs/openspec-slice.md row <N>
- Gate E approval: docs/hitl-gates-log.md (date)
```

The "Acceptance criteria" section is the live progress tracker. The PR cannot move to "Review" until every checkbox is ticked AND CI is green (see §4). The "AI-reviewer signoff" section is the live AI-review record, populated per §4.5 — the human reviewer (Gate F) reads this section first to know what's already been triaged.

### 3.3 Linked tracker ticket

Per [issue-tracking.md](issue-tracking.md) §2.2, the change's `proposal.md` carries `tracker_id: PROJ-N` (Jira) or `tracker_issue: N` (GH). The PR body MUST reference it via `Closes #N` (GH) or `PROJ-N:` prefix in the title (Jira). This drives automatic ticket transitions on merge.

### 3.4 Bump-bot supersede expectation

Auto-generated PRs (e.g. `chore/bump-playbook-v<tag>`, `chore/bump-skills-ai-playbook-v<tag>`, dependabot, renovate) MUST close any prior open PR on the same logical change-stream when a newer one opens. A "logical change-stream" is identified by the branch-name prefix:

- `chore/bump-playbook-v*` — playbook submodule bumps
- `chore/bump-skills-ai-playbook-v*` — skills-side playbook bumps
- `chore/bump-skills-eligia-skills-v*` — eligia-skills bumps
- Future bot streams: declare prefix in `.github/workflows/<bot>.yml`

The opening workflow finds previous open PRs whose head branch shares the same prefix, closes them with a `superseded by #<N>` comment, and deletes the source branch. This prevents the pile-up pattern observed during ai-playbook v0.8.0-rc1→rc6 dogfooding (10 stacked bump PRs, each pairwise-conflicting on the same submodule SHA, none individually mergeable).

The `propagate-{playbook,skills}-bump.yml` templates in `templates/new-project/.github/workflows/` ship this logic as of v0.8.0.

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

### 4.4 Pre-commit must run on the PR diff in CI, not `--all-files`

Consumer projects' CI pre-commit step MUST invoke the hooks against the diff between the PR's base ref and HEAD, not against the entire repository. Concretely:

```yaml
- name: Run pre-commit
  run: |
    if [ -n "$GITHUB_BASE_REF" ]; then
      git fetch origin "$GITHUB_BASE_REF" --depth=1
      pre-commit run --from-ref "origin/$GITHUB_BASE_REF" --to-ref HEAD --show-diff-on-failure
    else
      pre-commit run --from-ref HEAD~1 --to-ref HEAD --show-diff-on-failure
    fi
```

`--all-files` mode re-flags every legacy issue in `main` on every PR (trailing whitespace, missing trailing newlines on files added before the hook config, etc.) — false positives the PR didn't introduce. It also breaks any hook that decides "is this commit modifying file X?" by inspecting the path rather than the diff (e.g. `block-manual-spec-edit` flags every existing `openspec/specs/*.md` even when the PR doesn't touch any).

The diff-based invocation only checks files this PR actually changes. Hooks that ALSO need to be diff-aware (i.e. decide on the modified set of files, not the existing set) are listed in the `block_manual_spec_edit.py` reference implementation as of v0.8.0.

### 4.5 AI-reviewer feedback loop (worker AI must read + respond before Gate F)

When a Profile A repo opens a PR, an **AI reviewer** (CodeRabbit by default; claude-code-action when Phase 3 lands) leaves comments. These comments are not optional reading — the worker AI that opened the PR MUST integrate them into the loop:

1. **Wait for the AI-reviewer signal** — after pushing the final task commit on `slice/<change-id>`, poll for the reviewer's "review completed" status check (CodeRabbit posts it as `CodeRabbit / Review`; claude-code-action as `claude-review`). Allow up to 5 minutes per push (free tier rate limits the reviewer; high-frequency commits within a 5-minute window are batched into one review).
2. **Read the comments** — `gh pr view <N> --comments` lists summary + inline comments. The worker AI MUST inspect the structured "Actionable comments" section (CodeRabbit) or the equivalent in claude-code-action.
3. **Triage each comment** — for every comment:
   - **Address** — push a fix commit to the slice branch. The fix commit message MUST reference the comment ID or quote the relevant snippet so the audit trail is reconstructible.
   - **Reject with reason** — reply `@coderabbitai resolve` (or equivalent) with a one-line rationale. Acceptable reasons: (a) the suggested change conflicts with a project hard rule (cite AGENTS.md §X); (b) the suggestion is out of slice scope (cite slice's `proposal.md` "Out of scope"); (c) the suggestion is a false positive on a workaround the slice deliberately ships (cite the corresponding gotcha entry).
   - **Defer to follow-up** — open a tracking item on the project board with a brief note + reply `@coderabbitai resolve — tracked as #N`.
4. **Re-poll until clean** — push fixes triggers a new AI-reviewer pass (typically 30-90s). Repeat steps 2-3 until either:
   - All actionable comments are addressed or rejected with reason, AND
   - No new comments appear after a stabilising push.
5. **Only then request Gate F** — the PR description's "AI-reviewer signoff" subsection (added to §3.2 below) carries the final reviewer status + a one-line note ("CodeRabbit: 0 actionable / 3 addressed / 1 rejected: out-of-scope") before the human reviewer is pinged.

The contract is **strict** on Profile A repos because the AI reviewer IS the second pair of eyes that branch protection assumes. Skipping it (e.g. via `--admin` merge, or hand-waving the "pass" status before reading the comments) breaks the gate's invariant.

#### Failure mode this prevents

The v0.8.0 release itself admin-merged 5 PRs without inspecting CodeRabbit's output, justifying it as "rate-limited, no real comments to read." That justification is **conditional**, not exonerating:

- The rate limit was hit because the playbook fired 6 successive bumps in 60 seconds. Normal slice work doesn't hit rate limits — those PRs DO get real reviews.
- The audit trail of admin-merged PRs has no record of the worker AI ever reading the CodeRabbit summary, so a future reader cannot verify whether comments existed or were ignored.
- The AGENTS.md §4 hard rules + branch protection + AI reviewer form a defense-in-depth: dropping any one layer (especially the AI reviewer) reduces it to single-line defense (the human reviewer alone).

#### Profile B (private repos without CodeRabbit)

Until claude-code-action lands in Phase 3, Profile B repos have no AI reviewer. The contract degrades to: the worker AI MUST self-review the diff before requesting Gate F (run `gh pr diff <N>` and emit a structured self-review covering correctness, scope, security, idempotency). Self-review is logged in the PR description's "Self-review" subsection. Gate F humans can override but the audit trail must show it happened.

### 4.5.1 L1 — Worker-AI in-session check (mandatory after every PR push)

Introduced in v0.9.0. After **every** `gh pr create` or commit-push that updates a PR, the worker AI MUST invoke:

```
python -m scripts.check_coderabbit_status \
    --pr <N> --repo <owner/name> --wait 300
```

Behavior by exit code:

| Exit code | Status | Worker AI action |
|---|---|---|
| `0` | `available` | Resume the §4.5 normal loop (read comments, address, re-poll). |
| `1` | `rate-limited` or `silent` | **Apply Profile B fallback inline using [`runbooks/coderabbit-fallback.md`](../runbooks/coderabbit-fallback.md)**. Populate the PR-body §4.5 section per the schema in §4.5.3 below. Do NOT declare the PR ready for Gate F until §4.5 is populated. |
| `2` | setup error (gh unavailable, PR / repo not found) | Fix the setup error and retry. The PR is not ready for Gate F until L1 succeeds. |
| `3` | unrecoverable (gh / network failure during polling) | Treat as `rate-limited` — apply Profile B fallback. Note the gh failure in the §4.5 audit trail. |

The worker AI MUST NOT skip L1 because the diff is "obviously trivial". Bump PRs (submodule SHA + AGENTS.md version refresh) still get an L1 self-review — short, but present (see [`runbooks/coderabbit-fallback.md`](../runbooks/coderabbit-fallback.md) "bump PR" example).

### 4.5.2 L2 — CI safety net (auto-posts checklist when L1 didn't run)

Introduced in v0.9.0. The workflow [`templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`](../templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl) (propagated via `bootstrap_gh_project.py --profile auto`) fires on `pull_request: [opened, synchronize]`:

1. Sleeps 5 minutes (CodeRabbit's typical response window).
2. Runs `scripts/check_coderabbit_status.py --pr <N> --repo <R> --wait 0` (instant check; no further polling).
3. **If status is `available`** → workflow exits 0; no comment posted; status check `ai-self-review-required` set to `success`.
4. **If status is `rate-limited` or `silent`** → workflow runs `scripts/post_self_review_checklist.py`:
   - Reads `gh pr diff` + `gh pr view --json body`.
   - Checks the PR body for §4.5 schema markers (per §4.5.3 below).
   - **If §4.5 is populated** (markers present + non-stub) → status check set to `success`; no comment posted (L1 already ran in-session; L2 is silent).
   - **If §4.5 is empty / stubbed** → posts a structured fallback checklist as a PR comment + sets status check to `failure` (visible in branch-protection settings, but NOT in the required-checks list by default — Profile A consumers can opt in to enforcement).

This makes L2 a **silent safety net**: invisible when L1 ran successfully, present otherwise.

The status check `ai-self-review-required` is intentionally **not added to required-checks** by default. Consumers who want strict enforcement add it manually to their branch protection's `required_status_checks.contexts` list. Without enforcement, the check is informational — an audit-trail breadcrumb visible in the PR's "Checks" tab.

### 4.5.3 PR-body §4.5 schema (regex-validated by L2)

The "AI-reviewer signoff" subsection in the PR body MUST contain the following three markers (case-sensitive substring match) for L2 to consider it populated:

1. `Profile: A` or `Profile: B` (the AI-reviewer profile).
2. `Reviewer:` followed by any non-empty content (CodeRabbit, claude-code-action, or "self-review" with a reason).
3. `Self-review findings:` followed by any non-empty content (a finding list, OR the literal "none" / "no findings" if the diff was trivial).

If any marker is missing or stubbed (e.g. `Self-review findings: TODO`, or `<placeholder>` brackets), L2 considers §4.5 unpopulated and posts the checklist.

The full canonical structure is documented in [`runbooks/coderabbit-fallback.md`](../runbooks/coderabbit-fallback.md) §4. Bump PRs (submodule SHA + AGENTS.md version) MAY use the shorter form documented in that runbook's examples — markers still required, but the findings list can be `none` with a one-sentence justification.

#### `bootstrap_gh_project.py` does NOT auto-merge

The `apply_profile` helper (per §5.6) sets `allow_auto_merge=true` at the repo level, which exposes the per-PR "Enable auto-merge" button. The worker AI MUST NOT click it before §4.5 is satisfied. Auto-merge is a CONVENIENCE for clean PRs after Gate F approval, not a bypass for the feedback loop.

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

### 5.4 Repo linking + visibility

Because Projects v2 live at **user/org scope** (not repo scope), a freshly-created project does NOT appear in the repo's Projects tab until it is explicitly **linked** to the repo. Linking is a one-shot GraphQL mutation that adds the project to the repo's `projectsV2` collection. Without it, the project is reachable from `https://github.com/<owner>/projects/<number>` but invisible from `https://github.com/<owner>/<repo>/projects`.

The `bootstrap_gh_project.py --repo <owner/name>` flag (per §7) handles the link idempotently. Re-runs are no-ops.

Project **visibility** is independent: a project can be private (default) or public regardless of the visibility of the repos it is linked to. Set with `--visibility {private,public,keep}`. Public visibility is appropriate for community / OSS projects where contributors outside the org should see the roadmap; private is the default for closed-source work.

### 5.5 Trace fields: `Branch` + `Base SHA` (mandatory, text)

In addition to the canonical Status + recommended Risk/P&L fields, every consumer project's GitHub Project board MUST carry two text fields populated by the worker AI when a slice transitions `Todo → In Progress`:

| Field | Value | Populated when |
|---|---|---|
| `Branch` | `slice/<change-id>` (the literal branch name) | `/opsx:apply <change-id>` creates the worktree branch. |
| `Base SHA` | Short SHA of `main` HEAD at the moment the branch was forked (e.g. `e4c6e75`) | Same step: `git rev-parse --short HEAD` after `git checkout -b slice/<id> main`. |

These fields are not just metadata — they enable **two diagnostic queries** that have no other source of truth:

1. **"Is this slice's branch stale relative to main?"** — fetch the project board's `Base SHA` for the slice, compare to current `main` HEAD, count commits-behind. Deciding whether a pre-flight rebase is needed (per §6.5) becomes a one-shot lookup instead of a repo clone.
2. **"What version of `main` did the AI fork from?"** — for post-mortems, when a slice ships a regression that didn't exist at fork time, the `Base SHA` tells you the exact `main` snapshot the AI saw. Without it, you reconstruct from PR creation timestamps + git reflog (lossy, slow).

The fields are populated by the worker AI's `/opsx:apply` skill (per §6.5). The `bootstrap_gh_project.py` script adds the fields idempotently as part of project schema setup; existing projects get them on the next bootstrap run.

### 5.6 Visibility-driven enforcement profile

Branch protection rules + merge queue + CodeRabbit GH App are **gated on repo visibility + GH plan**:

| Feature | GH Free public | GH Free private | GH Pro / Team / Ent. private |
|---|---|---|---|
| Branch protection (classic) | ✅ | ❌ | ✅ |
| Repository rulesets | ✅ | ❌ | ✅ |
| Merge queue | ✅ | ❌ | ✅ (Team+) |
| CodeRabbit GH App (free tier) | ✅ unlimited | ❌ (paid only) | ❌ (paid only) |
| Auto-merge per-PR | ✅ | ✅ (vestigial without checks) | ✅ |
| GH Actions secrets | ✅ | ✅ | ✅ |
| Project boards (org/user-scoped v2) | ✅ | ✅ | ✅ |

Consumer projects therefore split into two **profiles**:

#### Profile A — Public OSS (full enforcement)

Applies when `gh repo view <repo> --json visibility` returns `"PUBLIC"`. The bootstrap script applies:

- Classic branch protection on `main`: required status checks (the consumer's CI matrix), 1 required review, dismiss-stale-reviews on new commits, strict (branch-up-to-date), conversation-resolution required, force-push blocked, branch-deletion blocked.
- Repo settings: auto-merge enabled, squash-only (`allow_merge_commit=false`, `allow_rebase_merge=false`, per §3.1's atomicity invariant), `delete_branch_on_merge=true`.
- `.coderabbit.yaml` template at repo root (CodeRabbit auto-installs on the next PR; the user must approve the GH App once via marketplace install).
- Project board with full schema (Status + Risk + P&L + Branch + Base SHA per §§5.1, 5.2, 5.5).
- Merge queue: deferred until the consumer enters its first parallel wave (queue is most useful when 2+ slices target main concurrently). Activate via `gh ruleset` once Wave 2 begins.

#### Profile B — Private Solo (convention-based)

Applies when `gh repo view <repo> --json visibility` returns `"PRIVATE"` AND the user is on GH Free. No branch protection enforcement is possible at the API level — `gh api repos/.../branches/main/protection` returns 403. The bootstrap script applies what is available:

- Repo settings: auto-merge enabled (vestigial — no required checks to satisfy, so functionally equivalent to a manual squash-merge), squash-only, `delete_branch_on_merge=true`.
- CI workflows: same matrix as Profile A, but **advisory only** — a red CI doesn't block merge mechanically; the AI MUST refuse to merge a PR whose CI is red, by `AGENTS.md` §4 hard rule (project-level).
- Project board: same full schema (consistency across the consumer constellation).
- CodeRabbit: skipped (paid for private repos in 2026). Two alternatives:
  1. Self-review — the AI reads the diff before requesting human Gate F.
  2. (Phase 3 follow-up) `claude-code-action` GitHub Action runs Claude on every PR with project-aware prompting from `AGENTS.md` + `release-management.md`. Pay-per-token; lower bound ~$0.01/PR.

Upgrading from Profile B → Profile A on the same repo is a one-line `gh repo edit --visibility public` followed by re-running `bootstrap_gh_project.py --profile auto` (which detects the new visibility and adds the missing rules).

#### Profile selection

`bootstrap_gh_project.py --profile {auto,public,private}`:

- `auto` (default) — query `gh repo view --json visibility` and dispatch to public/private path. Recommended for first-time bootstrap.
- `public` — apply Profile A even if the repo currently reads as private (intent: about to flip visibility; idempotent so it's safe to run before the flip).
- `private` — apply Profile B even if public (rarely useful; mostly for testing).

### 5.7 Initial Status assignment per slicing graph

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

### 6.4 Anti-collision contract (parallel waves)

Wave N (N ≥ 1) slices that run in parallel MUST declare in `docs/openspec-slice.md` "Anti-collision contract" the **shared files** they touch (`Makefile`, `.pre-commit-config.yaml`, `pyproject.toml`, `apps/api/src/main.py`, etc.). The contract is enforced socially (reviewer rejects if violated) and structurally (each slice owns its own `Makefile.includes`, `apps/<bounded-context>/`, `migrations/000N_<slice>.py`, etc., declared in the slice's proposal).

When a parallel-wave slice MUST touch a shared file, it coordinates via:

1. **Sequential serialization within the wave** — re-categorise the slice into a later wave that runs after the conflict-prone neighbour merges.
2. **Ownership split** — the shared file is split into N per-slice fragments (e.g. `Makefile` becomes `Makefile` + `apps/api/Makefile.includes` + `apps/web/Makefile.includes` + ...), each slice owns its fragment.
3. **HITL coordination** — for files where neither (1) nor (2) is possible (e.g. `.gitignore`), the affected slices add a HITL gate at design-review time documenting the touch.

### 6.5 Pre-flight rebase before slice start

Before the AI begins implementing a slice (i.e. before the first task commit on `slice/<change-id>`), it MUST:

1. `git fetch origin`
2. `git rev-parse --short origin/main` → record as the slice's `Base SHA` on the project board (per §5.5).
3. If currently on `slice/<change-id>`: `git rebase origin/main`. Conflicts → abort the rebase and notify the human reviewer (do NOT auto-resolve — slice scope drift is a slicing failure per §2.2's anti-pattern).
4. Set the project board's `Branch` field to `slice/<change-id>` (per §5.5).
5. Begin implementation; commits land on `slice/<change-id>` cleanly above `origin/main`.

This ensures every slice's PR opens against an up-to-date `main`, eliminating the "PR cannot merge: N commits behind main" friction at Gate F time. It also makes the `Base SHA` recorded on the project board meaningful for diagnostics (per §5.5).

#### Reference implementation: `scripts/opsx_apply_companion.py` (v0.8.3+)

The openspec-CLI-generated `openspec-apply-change` skill lives upstream and cannot embed §6.5 logic directly. Instead, the playbook ships a companion script that the worker AI invokes BEFORE implementation work begins:

```bash
python .ai-playbook/scripts/opsx_apply_companion.py \
    --change-id <slice-name> \
    --owner <gh-user-or-org> \
    --project-number <N> \
    --repo <owner/name>
```

The companion verifies a clean working tree, fetches origin, captures the base SHA, rebases the slice branch (if currently on it), and sets the `Branch` + `Base SHA` text fields on the matching project item via GraphQL. Idempotent. Exits non-zero on rebase conflicts so the worker AI knows to pause and notify the human.

The contract: `AGENTS.md` §0 (bootstrap directive) tells the AI to read `release-management.md` at session start; this section directs the AI to invoke the companion as Step 0 of `/opsx:apply` work. The AI MUST run the companion AND get exit-code 0 BEFORE making the first task commit.

### 6.6 Intra-slice parallelism (multiple subagents inside one slice)

§6.4 codifies parallelism **across** slices (Wave-N concurrency). This subsection codifies the orthogonal axis: parallelism **inside** a single slice, when the slice's `tasks.md` has independent task groups (typically one per bounded context inside one OpenSpec change).

**When it applies.** The slice contains ≥2 task groups with disjoint write-paths. The canonical example is a slice that scaffolds N bounded contexts in one shot (e.g. `module-1-ingredients-implementation` covering `iam/`, `ingredients/`, `suppliers/`, `cost/`, `shared/uom/` — 5 disjoint roots under `apps/api/src/`). Sequential implementation works fine; intra-slice parallelism just shortens wall-clock.

**When it does NOT apply.** Single-bounded-context slices, slices with TDD-tight ordering (e.g. interface → impl → consumer), slices small enough that spawning + coordination overhead exceeds the savings (rule of thumb: <3 task groups, or any group <10 tasks).

**Pre-conditions** (before spawning subagents):

1. `tasks.md` declares per-task-group **write-path ownership** in a header block, e.g.:

   ```markdown
   ## §2 IAM domain
   - **Owns**: `apps/api/src/iam/**`, `apps/api/src/migrations/0001-0004_*.ts`
   - **Reads**: `apps/api/src/data-source.ts` (no edits), `apps/api/src/app.module.ts` (registers via §8)
   - **Migration sequence numbers reserved**: 0001-0004
   ```

2. The main agent (the one orchestrating the slice) cross-checks ownership: no two groups own the same path; migration sequence numbers are non-overlapping; shared files (`app.module.ts`, `package.json`, `data-source.ts`, top-level `tsconfig`, etc.) are NOT owned by any subagent — they are touched serially by the main agent in a recombination step.

3. Migration sequence numbers are **pre-allocated** (not chosen by subagents) to avoid collisions in `apps/api/src/migrations/` numbering.

**Spawn pattern.** Use the `Agent` tool with `isolation: "worktree"` per group. Each subagent gets:

- A separate temporary worktree (off the same `slice/<change-id>` branch is impossible — git refuses two worktrees on the same branch — so the main agent creates one ephemeral branch per subagent: `slice/<change-id>--<group-id>`, branched from the slice base SHA).
- A scoped prompt: "Own these paths, don't touch the rest. Commit only to your branch. When done, return your branch name + commit SHA."
- The list of read-only paths it may consult.

**Recombination.** Subagents do NOT push their branches to `origin`. The main agent:

1. Awaits all subagents' completion.
2. Cherry-picks each subagent's commits onto `slice/<change-id>` in order of dependency (data-source.ts updates last).
3. Updates the shared files (`app.module.ts` registers the new modules; `package.json` aggregates new deps).
4. Runs the slice's full test suite. Conflicts → abort recombination, fall back to sequential implementation, file as a slicing-too-coarse failure for next retro.
5. Pushes `slice/<change-id>` once with the full bundle.

**Anti-patterns** (each is a `goal_drift` per [agentic-failures.md](agentic-failures.md)):

- A subagent edits a file outside its declared write-paths.
- A subagent pushes to a public branch (`origin/slice/...` or `origin/feat/...`) instead of returning a local branch SHA.
- The main agent skips the cross-check and spawns with overlapping ownership.
- Migration numbers chosen by subagents instead of pre-allocated.

**Hard limit.** This pattern caps at the number of disjoint bounded contexts the slice covers. Most slices have 1–2; modules-as-foundation slices have 3–5; nothing in the playbook spawns >6 subagents inside one slice (above that, the slice is mis-sliced — see §2.2 of [runbook-bmad-openspec.md](runbook-bmad-openspec.md)).

**Coordination cost vs. wall-clock saving.** The recombination step + the cross-check overhead is ~10–15 min. Below ~30 min of parallelisable work, sequential is faster. The pattern earns its keep on slices like `module-1-ingredients-implementation` (95+ tasks across 5 groups, ~4–6 hours sequential → ~1.5 hours parallel + 15 min recombination).

---

## 7. Bootstrap automation

A consumer project that adopts this contract for the first time runs **one** command to set up the project board with the correct schema, link it to the repo, set visibility, and apply the right enforcement profile:

```bash
python .ai-playbook/scripts/bootstrap_gh_project.py \
    --owner <gh-user-or-org> \
    --project-number <existing-project-id> \
    --repo <gh-user-or-org>/<repo-name> \
    --visibility private \
    --profile auto \
    --slicing-file docs/openspec-slice.md
```

`--profile {auto,public,private}` controls which enforcement profile to apply (per §5.6):
- `auto` — query `gh repo view` and apply Profile A (public) or Profile B (private) based on visibility. Default; recommended.
- `public` — apply Profile A regardless (use when about to flip visibility public; idempotent).
- `private` — apply Profile B regardless.

The script (per [`scripts/bootstrap_gh_project.py`](../scripts/bootstrap_gh_project.py)):

- Looks up the project under the given owner. **Projects v2 always live at user/org scope, never at repo scope** — the repo's Projects tab is purely a link surface.
- **Links the project to the repo** if `--repo <owner/name>` is passed (idempotent). Without this step, the project exists but does NOT appear in the repo's Projects tab; only the user/org Projects page lists it. Re-running on an already-linked repo is a no-op.
- **Sets project visibility** if `--visibility {private,public,keep}` is passed: `private` (default for new projects), `public`, or `keep` to leave the existing setting alone. Default flag value is `keep` so re-runs do not surprise the operator with an unintended visibility change.
- Adds the canonical Status field options (`Todo`, `Blocked`, `In Progress`, `Review`, `Done`) — idempotent (existing options preserved; missing ones added; names verified against §5.1; rename-divergence emits a warning that the human must resolve).
- Adds the recommended custom fields (`Risk`, `P&L impact`) — idempotent, with `--no-custom-fields` to opt out.
- Adds the trace fields (`Branch`, `Base SHA` per §5.5) — idempotent.
- Applies the visibility profile (per §5.6):
  - **Profile A (public)**: PUTs branch protection on `main` (required checks from `--required-checks` flag, 1 review, strict, conv-resolution, force-push blocked); PATCHes repo settings (`allow_auto_merge=true`, `allow_squash_merge=true`, others false, `delete_branch_on_merge=true`); writes `.coderabbit.yaml` from template if absent.
  - **Profile B (private)**: PATCHes repo settings same as Profile A; emits a `⚠ Profile B: branch protection unavailable on GH Free private — relying on convention + advisory CI.` notice; skips `.coderabbit.yaml`.
- Reads `docs/openspec-slice.md`, creates one draft project item per change row — idempotent (existing items detected by Title and skipped; items with unset Status get their initial Status applied as a recovery path).
- Sets initial Status: Wave 0 first slice → `Todo`; rest → `Blocked`.

Re-running the script after later edits to `docs/openspec-slice.md` adds new items / updates dependencies without dropping existing in-progress items. Removed-from-slicing items emit a warning (manual cleanup required to avoid losing review history).

---

## 8. Migration for existing consumers

Existing consumer projects on ai-playbook v0.7.x → v0.8.0 follow:

1. **Audit visibility**: `gh repo view <owner>/<repo> --json visibility`. Decide Profile A (make public) or Profile B (keep private). Document the decision in the consumer's `docs/hitl-gates-log.md`.
2. **Audit project board**: list current Status options. If they diverge from §5.1, plan a rename pass (one PR per consumer, since Status field rename can break external bookmarks).
3. **Run bootstrap**: `python .ai-playbook/scripts/bootstrap_gh_project.py --owner <user> --project-number <existing> --profile auto --no-create-items` (no-create-items mode aligns just the schema, not the items).
4. **Update consumer's `AGENTS.md`**: add `release_management: .ai-playbook/specs/release-management.md` to the inherited specs list. If on v0.7.x, also bump `inherits_from` to `@v0.8.0`.
5. **Update consumer's `.github/workflows/ci.yml`**: switch the pre-commit step to diff-mode invocation per §4.4. The template at `templates/new-project/.github/workflows/ci.yml.tmpl` ships the canonical form.
6. **Bump submodule pointer** to v0.8.0 (the propagate-bump bot opens the PR automatically per §3.4 once the playbook tag lands).

Consumer projects on v0.8.0+ inherit this spec automatically; new consumers bootstrapped via `scripts/bootstrap.py` get the AGENTS.md template that already references it.

### 8.1 Migration matrix (v0.7.x → v0.8.0)

For Arturo's current consumer constellation (May 2026):

| Project | Visibility | Profile | Migration owner | Notes |
|---|---|---|---|---|
| `iguanatrader` | PUBLIC | A | partial migration in v0.8.0-rc6→stable | Already on v0.8.0-rc6; first dogfood. Re-run bootstrap with `--profile auto` after stable. |
| `openTrattOS` | PUBLIC | A | full migration | OSS BOH project; description already reads "Open Source". |
| `eligia-skills` | PUBLIC (flipped 2026-05-01) | A | full migration | Skills are commodity; no IP concern. |
| `eligia-core` | PRIVATE | B | full migration | Personal infra; contains private endpoints. Stays private. |
| `eligia-rag` | PRIVATE | B | full migration | Personal data over RAG. Stays private. |
| `livekit` | PRIVATE | B | full migration | Personal voice AI for Palafito. Stays private. |
| `palafito-b2b` | PRIVATE | B | full migration | B2B business code. Stays private. |
| `ai-playbook` | PRIVATE | B (self-host) | self | The playbook eats its own dogfood; private until v1.0.0 stable. |

---

## 9. Anti-patterns

- **Per-task branches**: forbidden per §2.2.
- **Skipping CI for "trivial" changes**: every PR runs full CI; no opt-out for "just docs" or "just config" — language-specific lints + secrets scan apply universally.
- **Closing the change ticket without merge**: `Done` Status is reserved for actually-merged-to-main work. Items archived without merge land in `Cancelled` (custom Status option that consumer may add AFTER `Done`).
- **Cross-PR rebase chains**: do NOT branch slice 5 off slice 4's branch. Each slice branches off `main` (after its dependencies have merged). Cross-PR chains turn into rebase nightmares + force-pushes that reviewers cannot follow.
- **Reusing a slice/<id> branch after merge**: slice branches are deleted post-squash-merge. If new work is needed for the same change, that is a re-slice (new change-id, new branch).
- **Pre-commit `--all-files` in CI**: forbidden per §4.4. Always invoke with `--from-ref/--to-ref` against the PR's base ref.
- **Skipping pre-flight rebase**: forbidden per §6.5. AI must rebase before first commit on the slice branch.
- **Bump-bot stacking PRs**: forbidden per §3.4. Each new bump auto-closes prior open PRs on the same logical change-stream.
- **Manual edits to `openspec/specs/*.md`**: forbidden — must come via `openspec archive`. The `block-manual-spec-edit` pre-commit hook enforces this; CI invocation must use diff-mode (§4.4) so the hook only checks files actually modified by the PR.
- **Skipping AI-reviewer triage** (Profile A) or **self-review** (Profile B): forbidden per §4.5. The "AI-reviewer signoff" subsection in the PR body is the audit trail. Admin-merging without populating it skips the second pair of eyes that branch protection assumes — branch protection alone is single-line defense.
- **Clicking "Enable auto-merge" before §4.5 is satisfied**: forbidden. Auto-merge is convenience for clean PRs after Gate F, not a bypass for the AI-review feedback loop.

---

## 10. Cross-references

- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §3 — OpenSpec lifecycle this spec governs the source-control side of.
- [issue-tracking.md](issue-tracking.md) — ticket↔proposal automation (Jira / GH Issues); this spec extends to the source-control side.
- [bmad-openspec-bridge.md](bmad-openspec-bridge.md) §3 — slicing artefact schema this spec depends on for dep-graph parsing.
- [verdict-contract.md](verdict-contract.md) — `❓ CLARIFICATION NEEDED` triggers Status `Blocked`.
- [agentic-failures.md](agentic-failures.md) — `goal_drift` if a worker creates a per-task branch.
- [break-glass.md](break-glass.md) — Gate F can be overridden with `--force-with-reason` in genuine emergencies; CI green and dependency-merged are NEVER overridable (red CI = real signal; missing dep = wrong order).
- [`templates/new-project/.coderabbit.yaml.tmpl`](../templates/new-project/.coderabbit.yaml.tmpl) — CodeRabbit config template applied in Profile A.
- [`templates/new-project/.github/workflows/project-status.yml.tmpl`](../templates/new-project/.github/workflows/project-status.yml.tmpl) — auto-transition `Blocked → Todo` workflow (§6.3).
- [`templates/new-project/.github/workflows/dep-check.yml.tmpl`](../templates/new-project/.github/workflows/dep-check.yml.tmpl) — optional hard dependency enforcement (§6.2).
- [`templates/new-project/.github/workflows/propagate-playbook-bump.yml.tmpl`](../templates/new-project/.github/workflows/propagate-playbook-bump.yml.tmpl) — bump-bot with supersede logic (§3.4).
