---
schema: concept/v1
slug: v090-roadmap
title: v0.9.0 Roadmap
summary: |
  v0.8.x shipped the release-management contract (§4.5 codifies that the
  worker AI must consume the AI reviewer's comments before declaring Gate F
  ready) but the §4.5 contract assumes CodeRabbit is available. In practice
  CodeRabbit's free-tier rate-limit burns through during…
last_validated: "2026-05-19"
---

# v0.9.0 Roadmap

## Why this release

v0.8.x shipped the release-management contract (§4.5 codifies that the worker AI must consume the AI reviewer's comments before declaring Gate F ready) **but** the §4.5 contract assumes CodeRabbit is **available**. In practice CodeRabbit's free-tier rate-limit burns through during multi-bump series and substantial slices, leaving the worker AI to apply Profile B (self-review) **manually** — fragile, easy to forget, no automation backstop.

v0.9.0 turns the manual fallback into an enforced 3-layer defense.

## Design objectives

### 1. CodeRabbit fallback — 3-layer defense in depth

**Motivation** (Arturo, 2026-05-01): *"podemos hacer nosotros el review en vez coderabbit como fallback?"* — followed by *"si lo estoy push desde aqui lo suyo seria que el fallback se ejecute por aqui, puede ser mediante IA sin problema"* — followed by *"pero entiendo que no son excluyentes no? pudieran ser complementarias"*.

The 3-layer model:

| Layer | Trigger | What it does | Failure mode it covers |
|---|---|---|---|
| **L0** (already exists) | Every commit / push | Pre-commit + CI mechanical checks: ruff / black / mypy --strict / pytest / gitleaks / boundary checks / license checks | Mechanical issues regardless of who pushed |
| **L1 — AI in-session self-review** (new) | Worker AI invokes `check_coderabbit_status.py` after `gh pr create`. If `rate-limited` or `silent` after 5 min, AI runs the self-review **inline in the same session** using `docs/runbooks/coderabbit-fallback.md` as the structured guide; populates §4.5 of the PR body before declaring Gate F ready | Narrative review of high quality (AI has full context); fixes critical findings immediately as additional commits | CodeRabbit unavailable **AND** AI session is active |
| **L2 — GH Action safety net** (new) | `pull_request: [opened, synchronize]`. After 5-min wait, polls CodeRabbit. If silent/rate-limited **AND** PR body §4.5 still empty (regex check), posts a structured fallback checklist as a PR comment + marks status check `ai-self-review-required` as failing | Structured checklist persists in the PR for the next AI session or the human reviewer to address | Worker AI session ended before L1 ran; or push was made by a human without an AI; or L1 silently failed (script error, etc.) |

**L1 + L2 coordination**: L2 reads the PR body before posting. If §4.5 is **already populated** (regex match for non-stub `Self-review findings:` plus `Profile: [AB]` plus `Reviewer:`) → L2 marks the status check ✅ and does NOT post the checklist (avoids redundant noise). If §4.5 is empty / stub → L2 posts the checklist and the status check stays red until §4.5 gets filled in.

This makes **L2 a silent safety net**: invisible when L1 worked, present when L1 didn't.

#### Components (planned)

| Component | Path | Purpose | Approx LOC |
|---|---|---|---|
| **L1 detection script** | `scripts/check_coderabbit_status.py` | Args: `--pr <N> --repo <r> --wait <secs> --json`. Polls `gh pr view --comments` every 30 s for up to `--wait` seconds. Returns JSON `{status: "available\|rate-limited\|silent\|error", since_open_seconds: N, last_comment_excerpt: "..."}` | ~80 |
| **L1 self-review runbook** | `docs/runbooks/coderabbit-fallback.md` | Structured guide for the worker AI: what to inspect by category (security, async / race, error handling, type safety, deps, edge cases, docs) + how to populate §4.5 in PR body | ~120 |
| **L2 checklist script** | `scripts/post_self_review_checklist.py` | Reads `gh pr diff` + `gh pr view --json body`. Generates a diff-aware checklist (new public symbols, new async paths, new error paths, new deps, security-relevant changes). Posts via `gh pr comment` if §4.5 is not yet populated. Marks status check via `gh api` (Checks API) | ~150 |
| **L2 workflow template** | `templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl` | Trigger: `pull_request: [opened, synchronize]`. Sleeps 5 min. Runs both detection + checklist scripts. Sets status check `ai-self-review-required` | ~60 |
| **§4.5 spec update** | `docs/concepts/release-management.md` | Insert subsections §4.5.1 (worker-AI in-session check — must run after every PR push), §4.5.2 (CI safety net — auto-posts checklist if §4.5 unpopulated), §4.5.3 (PR-body §4.5 schema requirements that L2 regex-validates) | ~40 lines added |
| **Release runbook update** | `docs/runbooks/release.md` Step 7 | Mention that the L2 workflow auto-posts the checklist on bump PRs too — and that the L1 in-session pattern applies to manual bump merges if CodeRabbit is rate-limited | ~10 lines added |

#### Trade-offs honestly considered

- **L1 blocks the AI session for ~5 min per PR**: chosen for simplicity. If this becomes annoying we evolve to a background-poll pattern (`run_in_background=true` Bash + a wakeup) in v0.9.x.
- **L2 generates a redundant comment if L1 is slow**: mitigated by L2 doing the body check just before posting; race window is small (seconds).
- **L2's status check `ai-self-review-required` is informational by default** (not in branch-protection required-checks list). Profile A consumers can add it to required-checks to enforce; v0.9.0 ships it as opt-in to avoid breaking existing PRs mid-flight.
- **L2's checklist quality is mechanical, not narrative** — accepted; the narrative version IS L1.
- **Doesn't cover the case where CodeRabbit is available but mid-quality** (e.g., reviewed only 3 of 11 commits because the rate-limit burned mid-review). This is rarer; v0.9.x can extend.

#### Alternatives considered

1. **Local LLM (Ollama)** as the reviewer when CodeRabbit fails. Rejected: adds infra (Ollama install + model), unreliable quality, and Arturo explicitly excluded "API token" reviewers — preferring zero infra.
2. **Only L1 (no L2)**. Rejected at the user's prompt: doesn't cover human pushes without an active AI session, or AI sessions that ended mid-flow.
3. **Only L2 (no L1)**. Rejected: generates a checklist instead of a real review; loses the AI's full-context narrative analysis. L1 produces strictly better output when applicable.
4. **GitHub Merge Queue with required AI-review check**. Rejected for v0.9.0: requires GitHub Pro for some features and adds another layer of branch-protection complexity. Worth revisiting in v1.0.

#### Validation plan

1. Tag `v0.9.0-rc1`. Propagation auto-opens bump PRs across the 5 consumers.
2. **Validate on `consumer-e` first** — the next slice (slice 3 `persistence-tenant-enforcement`) is a perfect bench: medium-sized, exercises real CodeRabbit usage. Verify both L1 (worker AI runs the script + does inline review) and L2 (workflow posts the checklist on a synthetic PR with §4.5 stubbed empty).
3. If both layers behave: tag `v0.9.0` stable → cascade to all 5 consumers.
4. If issues: fix → tag `rc2`. Each rc cleanly supersedes prior bump PRs per `docs/concepts/release-management.md` §3.4.

#### Consumer impact

- **Additive**. No breaking changes to existing consumer behavior.
- Consumers that bump to v0.9.0 receive the L2 workflow template (after `bootstrap_gh_project.py --profile auto` re-runs to apply new workflow templates) and the L1 spec/runbook.
- Profile B consumers (private + GH Free) get full benefit — L2 is a GH Action and works on private repos without Pro.
- The `ai-self-review-required` status check is **NOT** added to required-checks by default. Consumers who want enforcement add it to their branch-protection list manually.

#### Semver decision

**Minor bump** (`0.8.5 → 0.9.0`) — additive scripts, additive workflow template, additive spec subsections. No frontmatter schema changes, no env-var renames, no removed scripts. Safe under `docs/concepts/rollout-strategy.md`.

## Tasks (implementation checklist)

Grouped per `templates/new-project/.claude/skills/openspec-apply-change` conventions for traceability.

### A. L1 — AI in-session self-review

- [ ] A.1 Implement `scripts/check_coderabbit_status.py` per the API in the components table. Pure stdlib + `gh` CLI. Returns JSON to stdout for easy worker-AI parsing.
- [ ] A.2 Author `docs/runbooks/coderabbit-fallback.md` — the structured guide the worker AI follows when status is `rate-limited` / `silent`. Sections: detection, diff-classes-to-inspect (by category), how to fix critical findings, how to populate §4.5 PR body, examples (cite PR #41 of `consumer-e` as the manual reference run).
- [ ] A.3 Add unit tests under `tests/` for `check_coderabbit_status.py`: mock `gh pr view --comments` output for each of the 4 status outcomes; assert correct JSON output.
- [ ] A.4 Spec update `docs/concepts/release-management.md` §4.5: insert §4.5.1 codifying that worker AI must invoke the script after every `gh pr create` and follow the runbook if status is not `available`.

### B. L2 — GH Action safety net

- [ ] B.1 Implement `scripts/post_self_review_checklist.py`: reads `gh pr diff` + `gh pr view --json body`; generates the diff-aware checklist; posts as PR comment via `gh pr comment` IF §4.5 in body is unpopulated (regex check); marks status check `ai-self-review-required` via `gh api`.
- [ ] B.2 Author `templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl` per the API in the components table. 5-min sleep, then runs detection + checklist scripts in sequence.
- [ ] B.3 Add unit tests under `tests/` for `post_self_review_checklist.py`: mock the various PR-body states (empty §4.5 / stub §4.5 / populated §4.5) and assert correct posting / skip behavior.
- [ ] B.4 Spec update `docs/concepts/release-management.md` §4.5.2: codify the CI safety net + the `ai-self-review-required` status check semantics + how consumers can opt-in to required-check enforcement.
- [ ] B.5 Spec update §4.5.3: define the PR-body §4.5 schema (the regex L2 uses to detect "populated"). Document the canonical structure: `Profile: A|B`, `Reviewer:`, `Self-review findings:`, etc.

### C. Bootstrap + propagation integration

- [ ] C.1 Update `scripts/bootstrap_gh_project.py` to apply the new workflow template (`coderabbit-fallback.yml.tmpl`) under `apply_profile()` when running `--profile auto` on a consumer. UNION semantics — don't overwrite an existing file with local edits.
- [ ] C.2 Update `docs/runbooks/release.md` Step 7 + Step 8 to mention that consumers re-run `bootstrap_gh_project.py --profile auto` after the v0.9.0 bump merges, to pick up the new workflow.
- [ ] C.3 Update `docs/runbooks/onboard-new-project.md` Step 11 to mention the new workflow file in the "templates copied" list.

### D. Release

- [ ] D.1 Bump `VERSION` to `0.9.0-rc1`.
- [ ] D.2 Add `CHANGELOG.md` section: `## [0.9.0] — YYYY-MM-DD — CodeRabbit fallback (3-layer defense)` summarizing L1 + L2 + spec updates + new scripts.
- [ ] D.3 Tag `v0.9.0-rc1` → push → propagation auto-opens bump PRs.
- [ ] D.4 Validate on `consumer-e` slice 3 (`persistence-tenant-enforcement`).
- [ ] D.5 If clean → tag `v0.9.0` stable → propagation cascades to 5 consumers.

## Followups surfaced during the rc1 + rc2 rollout (2026-05-01)

Two real bugs surfaced while propagating v0.9.0-rc1 / rc2 across the 5 consumers. Both deferred to a v0.9.x patch release (or v0.9.0 stable if we cut it before the patches land).

### Followup 1 — `propagate_bump.py` doesn't bump `AGENTS.md` `inherits_from:` — **RESOLVED v0.9.1 (2026-05-01)**

Closed by [`fix(release-management/v0.9.1)`](https://github.com/Wizarck/ai-playbook/pull/29). Validated end-to-end during the v0.9.1 cascade dogfood: livekit's auto-generated bump PR ([Wizarck/livekit#40](https://github.com/Wizarck/livekit/pull/40)) included `AGENTS.md` `inherits_from:` change automatically — no manual fix-PR required. The `_edit_frontmatter_skills_source` helper was extracted to `scripts/_bumper.py::bump_agents_md_pin` and is now invoked from BOTH propagation scripts.

**Surfaced**: livekit ended the rc2 cascade with `.ai-playbook/` submodule at v0.9.0-rc2 (correct) but `AGENTS.md` `inherits_from: ai-playbook@v0.3.0` (stale). Required a manual bump PR (Wizarck/livekit#36) to fix.

**Root cause**: `scripts/propagate_bump.py` only writes the submodule pointer file (`.ai-playbook` gitlink); it never touches `AGENTS.md`. `scripts/propagate_skills_bump.py` DOES rewrite `AGENTS.md` frontmatter — but only fires for consumers that have `skills_pins:` in `consumers.yaml`. livekit doesn't (it's a personal project with no skills tracking), so neither propagation path bumps its `inherits_from:`.

**Why this matters**: `inherits_from:` is the canonical declaration of which playbook semver tag the project tracks. Stale value confuses humans + AIs reading AGENTS.md and breaks the audit trail.

**Fix**: extend `propagate_bump.py` to ALSO rewrite `AGENTS.md` frontmatter `inherits_from:` line for the consumer it's bumping. Same regex pattern as `_edit_frontmatter_skills_source` already uses (it already matches `inherits_from:` lines incidentally — confirmed by inspection during the cycle). Move the regex helper into `_bumper.py` so both propagation scripts share it.

**Test plan**: re-run propagation on livekit at next playbook release; confirm `inherits_from:` bumps automatically without needing a manual PR.

### Followup 2 — Supersede uses tag-push chronology, not semver order — **RESOLVED v0.9.1 (2026-05-01)**

Closed by [`fix(release-management/v0.9.1)`](https://github.com/Wizarck/ai-playbook/pull/29). `_bumper.supersede_open_bump_prs()` is now semver-aware — parses the head-branch's version (`chore/bump-(playbook|skills-*)-vX.Y.Z[-rc.N]`), compares via tuple key (stable releases sort above their rcs of the same series; older series sort below newer), and only closes an open PR whose parsed version is `<=` the new bump's. Both fix options from the original analysis shipped: option #1 (operational pre-tag check codified in `docs/runbooks/release.md` Step 3) AND option #2 (semver-aware code fix in `_bumper.py`). Covered by 8 unit tests in `tests/test_bumper.py`.

**Surfaced**: pushed `v0.8.7`, `v0.8.8`, `v0.9.0-rc2` simultaneously. Three propagate workflows fired in parallel; `v0.8.7`'s PRs opened LAST (workflow scheduling order, not semver order) and the supersede helper closed the rc2 PRs in favor of v0.8.7 — exactly backwards. Recovery required closing 9 stale v0.8.7 PRs manually + delete-and-re-push the v0.9.0-rc2 tag to retrigger propagation.

**Root cause**: `scripts/_bumper.py::supersede_open_bump_prs()` uses "newer-PR-by-creation-time wins" semantics. When multiple tags push close together, the workflow scheduling determines order, not semver.

**Fix options**:
1. **Pre-tag check in `docs/runbooks/release.md` Step 3**: require `git log <prev-tag>..HEAD` to be empty before tagging (forces consolidating fixes into the next-version's bundle). Operational fix; doesn't change script behavior.
2. **Semver-aware supersede in `_bumper.py`**: parse the tag from the branch name (`chore/bump-playbook-v0.8.7` → `v0.8.7`), compare via `packaging.version`, supersede only if the new PR's version is `>=` than the open one. Code fix; bulletproof against any push order.

Recommend **#2 long-term** + **#1 documented as the operational guard** so devs don't have to rely on script correctness when tagging.

**Test plan**: write a test in `tests/test_bumper.py` that opens 3 PRs at versions v0.8.7, v0.9.0-rc2, v0.8.8 (in that order) and asserts only v0.9.0-rc2 ends open after each subsequent supersede call.

### Followup 3 — `block_manual_spec_edit.py::read_commit_message` doesn't read CI env vars — **RESOLVED v0.9.1 (2026-05-01)**

Closed by [`fix(release-management/v0.9.1)`](https://github.com/Wizarck/ai-playbook/pull/29). `read_commit_message()` now ALSO reads `$PRE_COMMIT_FROM_REF/$PRE_COMMIT_TO_REF` and runs `git log --format=%B%x00 $FROM..$TO` to concatenate every commit message in the range. The `openspec-archive:` marker is detected if it appears in ANY commit on the branch. Covered by 4 new tests in `tests/test_block_manual_spec_edit.py` (real git repo, real env vars).

**Surfaced**: consumer-e PR #57 (slice 3 archive — `chore(openspec): archive slice 3 persistence-tenant-enforcement`). The commit body INCLUDED the `openspec-archive: persistence-tenant-enforcement` marker on its own line. Local pre-commit (commit-msg stage) read the marker correctly via `$PRE_COMMIT_COMMIT_MSG_FILE` and allowed the commit. CI's `pre-commit run --from-ref ... --to-ref ...` then re-flagged `openspec/specs/persistence-layer/spec.md` as a "hand-edit" with: `❌ openspec/specs/*.md hand-edit detected and commit message unavailable at openspec/specs/persistence-layer/spec.md`. Required `--admin` merge to bypass.

**Root cause**: [`scripts/block_manual_spec_edit.py::read_commit_message()`](../../scripts/block_manual_spec_edit.py) only resolves the message via:
1. `$PRE_COMMIT_COMMIT_MSG_FILE` (commit-msg stage; works locally)
2. `<repo-root>/.git/COMMIT_EDITMSG` (fallback)

It does NOT iterate the commits in `$PRE_COMMIT_FROM_REF..$PRE_COMMIT_TO_REF` (CI's `--from-ref/--to-ref` mode), so in CI it always returns None and the hook fails as if the marker were missing — even when it's present in the actual commit. The script's docstring CLAIMS this CI mode is supported, but the implementation doesn't match.

**Why this matters**: every archive PR now requires admin-merge in CI. The hook is producing false positives that erode the value of branch protection.

**Fix**: extend `read_commit_message()` to also try `git log --format=%B $PRE_COMMIT_FROM_REF..$PRE_COMMIT_TO_REF` when those env vars are set. Concatenate all commit messages in that range (so the marker is detected if it appears in ANY of them). Update the docstring + README accordingly.

**Test plan**: write a test in `tests/test_block_manual_spec_edit.py` that sets `PRE_COMMIT_FROM_REF=base PRE_COMMIT_TO_REF=head` env vars, creates a 2-commit history where one commit edits an `openspec/specs/*.md` file and the OTHER commit's message contains `openspec-archive:`, and asserts the hook exits 0.

### Followup 4 — `/opsx:apply` skill doesn't enforce `tasks.md` checkbox-update discipline

**Surfaced**: consumer-e slice 3 (`persistence-tenant-enforcement`). The implementation merged with **0 of 55** task checkboxes ticked off, even though the slice was 100 % feature-complete (verified by 30 new tests + 95 % coverage on `persistence/*` + mypy strict clean + pre-commit clean before merge). When the archive ran, `openspec archive` flagged 55 incomplete tasks and required `--yes` to override. The audit trail value of `tasks.md` is undermined when the boxes drift from the actual implementation state.

**Root cause**: the `openspec-apply-change` skill (upstream OpenSpec CLI; not playbook-owned) instructs the agent to "update task checkbox immediately after completing each task" but enforces nothing — it's a soft guideline that's easy to miss when the agent is focused on the code work + tests + mypy + pre-commit cycles. There is no automation that ticks boxes from commit metadata, no failing CI check, no warning at PR-open time.

**Why this matters**: `tasks.md` is the only place where task-level completion state lives between proposal and archive. A drifted `tasks.md` makes:
- `openspec status` reports lying about real progress.
- Retros + dependency analysis useless (which tasks were actually exercised? unknown).
- The `--yes` override on `openspec archive` becomes habitual, training the worker AI to ignore the warning even when the slice ISN'T feature-complete.

**Fix options** (one of these, possibly more than one):

1. **Conventional-commit scope → checkbox auto-tick (recommended)** — the playbook ships a script + git hook (`scripts/auto_tick_tasks.py`, invoked from `prepare-commit-msg`) that:
   - Parses the commit subject for a task ID convention (e.g. `feat(persistence): groups 1-3` or `chore: §2.1 + §2.2`).
   - Walks `openspec/changes/*/tasks.md` for the active change, ticks matching `- [ ]` → `- [x]`.
   - Stages the modified `tasks.md` so it lands in the same commit.
   This is opt-in (consumers add the hook in `.pre-commit-config.yaml`); the playbook just provides the script + a regex schema.
2. **PR-open warning workflow** — `.github/workflows/check-tasks-checkboxes.yml` parses the open PR's branch for `slice/<change-id>` convention, reads `openspec/changes/<id>/tasks.md`, fails (or comments) if `<X> of N tasks unchecked` AND the diff suggests broader implementation. Soft enforcement; complements option 1.
3. **`openspec archive --strict`** — extend the archive command (or a wrapper) to refuse `--yes` when fewer than 100 % of tasks are ticked, forcing the worker AI to either tick honestly OR file a "scope reduced" amendment to `tasks.md`. Hard enforcement; less ergonomic.

**Recommended path**: ship option 1 + option 2 in v0.9.x. Option 3 deferred until we see whether 1+2 are sufficient — strict-mode is annoying enough that it should only land if soft mechanisms don't move the needle.

**Test plan**: dogfood on the next multi-group slice (Wave 2 in consumer-e). Compare boxes-checked rate before-and-after option 1 ships. Target: ≥ 95 % of tasks auto-ticked when the convention is followed; the remaining 5 % are tasks that span multiple commits + need a manual tick at the end.

**Status**: filed 2026-05-01 (v0.9.2 release). Open.

## References

- [`docs/concepts/release-management.md`](release-management.md) §4.5 — the AI-reviewer feedback loop this release extends.
- [`docs/runbooks/release.md`](../runbooks/release.md) — release flow, this release follows the rc-first pattern (substantial release).
- [`docs/concepts/v0.8.0-roadmap.md`](v080-roadmap.md) — prior roadmap, reference for format.
- `consumer-e` PR #41 — manual reference run of L1 (the worker AI did the self-review by hand on 2026-05-01 because CodeRabbit was rate-limited; v0.9.0 codifies what was done there).
- `livekit` PR #36 — the manual `inherits_from:` bump that surfaced followup #1.
- `ai-playbook` v0.9.0-rc1 → rc2 cycle — the supersede mishap that surfaced followup #2.
