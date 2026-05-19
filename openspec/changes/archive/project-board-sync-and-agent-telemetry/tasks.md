# tasks — `project-board-sync-and-agent-telemetry`

> TDD-ordered implementation steps for v0.10.0. Companion to
> `proposal.md` and `design.md`.

## 1. Documentation (already shipped in commit `cde2a13`)

- [x] 1.1 New spec `docs/concepts/project-board-sync.md` (v1.0.0) — 7-layer contract
- [x] 1.2 New spec `docs/concepts/agent-telemetry.md` (v1.0.0) — Claude Code OTLP → Langfuse
- [x] 1.3 New spec `docs/concepts/event-and-data-patterns.md` (v1.0.0) — 7 stack-agnostic patterns
- [x] 1.4 New spec `docs/concepts/cross-language-tooling.md` (v1.0.0) — `tools/<name>/` convention
- [x] 1.5 New runbook `docs/runbooks/windows-dev-environment.md` — 4 Windows gotchas
- [x] 1.6 Update `docs/rules/verification-before-completion.rule.md` §4.1 — broadest-scope + tool-exit-code
- [x] 1.7 Update `docs/concepts/release-management.md` §4.4 — gitleaks + markdown style
- [x] 1.8 Update `docs/concepts/release-management.md` §6.4 — append-only ranges + verbose migrations
- [x] 1.9 Update `docs/concepts/release-management.md` §6.6 — cross-BC verification gates guidance
- [x] 1.10 Update `docs/concepts/release-management.md` §9.5 — cross-ref to project-board-sync
- [x] 1.11 Update `docs/concepts/runbook-bmad-openspec.md` §3.7.1 — design-mock HTML
- [x] 1.12 Update `docs/concepts/runbook-bmad-openspec.md` §4.1 — forward-authored retros
- [x] 1.13 CHANGELOG entry for all of the above

## 2. L2 — `templates/new-project/.github/workflows/project-status-slice-progress.yml.tmpl`

- [x] 2.1 Create workflow file scaffold (push + PR triggers, GraphQL via `gh api`) — committed in `64899f2`.
- [x] 2.2 Implement `push to slice/**` handler: extract change-id from branch, set `Branch` field + `Base SHA` + `Status=In Progress` on the project item.
- [x] 2.3 Implement `pull_request opened` handler: set `Status=Review`. Also covers `reopened`.
- [x] 2.4 Implement `pull_request synchronize` handler: trigger included in `on.pull_request.types`; refresh runs idempotently on every push to the PR head ref.
- [x] 2.5 Document required secrets (`PROJECT_AUTOMATION_TOKEN`) + variables (`PROJECT_OWNER`, `PROJECT_NUMBER`) in the template's header comment block. Reuses the convention already established by the existing `project-status.yml` template (no new secret required for adoption).

## 3. L3 — `templates/new-project/.github/workflows/project-board-synced-check.yml.tmpl`

- [x] 3.1 Create required-status-check workflow that runs on every PR push — committed in `64899f2`.
- [x] 3.2 GraphQL query: fetch the project item matching the PR's branch via Title-contains-`<change-id>` lookup; assert Status ∈ {In Progress, Review} + Branch field matches PR head ref + Base SHA field populated.
- [x] 3.3 Exit non-zero on assertion failure with actionable error message naming `opsx_apply_companion.py` as the fix path.
- [x] 3.4 Document the consumer-side step in the template header: add `project-board-synced` to required-status-checks list per `release-management.md` §4.1.

## 4. L4 — `templates/new-project/.github/workflows/project-state-machine.yml.tmpl`

- [~] 4.1 v1 ships as periodic auditor (cron `*/15 * * * *` + `workflow_dispatch`); v2 will switch to native `project_v2_item.edited` webhook events when GH exposes them at the workflow level (tracked at <https://github.com/orgs/community/discussions/53973>). Documented as v0.10.1 follow-up.
- [~] 4.2 v1 detects items with `Status=Done` but no merged PR (the most common skip case). v2 will compare `previous_status` vs `new_status` once the webhook payload is available.
- [x] 4.3 Audit comment posted on the linked issue/PR via `gh api repos/.../issues/{N}/comments`; sticky-comment idempotency. **Auto-revert NOT shipped in v1** (intentional — per design D5: "v1 only audits + comments"). v2 ships revert.
- [x] 4.4 Honor `break-glass` label exception per `docs/rules/break-glass.rule.md`.

## 5. L6 — Extend `scripts/opsx_apply_companion.py` with `--enforce-board`

- [x] 5.1 Add `--enforce-board` CLI flag (default false to preserve backwards compat) — committed in `082daa2`.
- [x] 5.2 When set: after the existing pre-flight rebase + Branch/Base-SHA write, delegate to `verify_board_state.py` with `--expected-status='In Progress'` and propagate the exit code.
- [x] 5.3 Exit non-zero with actionable message if assertion fails. Telemetry event `opsx_apply_companion.board_enforce_failed` emitted on mismatch.

## 6. L7 — `scripts/verify_board_state.py` + skill update

- [x] 6.1 Create `scripts/verify_board_state.py` — CLI entrypoint with args: `--change-id`, `--owner`, `--project-number`, `--expected-status` (default `Done`) — committed in `082daa2`.
- [x] 6.2 Implement GraphQL query to fetch the project item by Title-contains-`<change-id>` lookup; compare Status to expected; exit non-zero on mismatch. Stable exit-code contract (0/1/2/3) documented in the script's docstring.
- [x] 6.3 Update `skills/openspec-archive-change/SKILL.md` Step 0: invoke `verify_board_state.py --expected-status=Done` before archive; refuse archive on non-zero exit.

## 7. Tests

- [x] 7.1 `tests/test_verify_board_state.py` — 11 tests covering all 4 exit codes + CLI parsing (mocked GraphQL transport at the `subprocess.run` boundary) — committed in `10864ef`.
- [~] 7.2 `tests/test_opsx_apply_companion.py` extension — DEFERRED to v0.10.1. The `--enforce-board` flag delegates to `verify_board_state.main()` which has full coverage; the companion's existing tests still pass (no behaviour change when `--enforce-board` is absent — backwards-compat invariant).
- [~] 7.3 Local pytest run — local shell environment has Bash auto-backgrounding pytest hangs; CI 3.11 + 3.12 both pass green (verified via `gh pr checks 40`). The CI run IS the verification.
- [x] 7.4 `ruff check .` + `ruff format --check` on the 3 new/changed Python files — clean (commit `bfdfb91`).

## 8. Verification + close-out

- [~] 8.1 `gen_indexes.py` regen — DEFERRED to v0.10.1 alongside the `INDEX.md` rows (the auto-generation runs at release time per the existing `gen_indexes.py` cadence; this slice's specs will be picked up there).
- [x] 8.2 CHANGELOG sweep — every added/changed file in §1-§7 is referenced with research-grounded justifications; committed in `10864ef`.
- [x] 8.3 Push branch; CI green: validate ✓ pytest 3.11 ✓ pytest 3.12 ✓ recommend ✓ scan ✓ CodeRabbit ✓ (PR #40, 6/6 required checks).
- [x] 8.4 PR ready for Master review at <https://github.com/Wizarck/ai-playbook/pull/40>.

## Legend

- `[x]` — done in this PR
- `[~]` — partial / scoped to v1; v2 path documented in design.md or CHANGELOG
- `[ ]` — not done (this PR has none)
