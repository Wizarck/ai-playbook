# tasks — `project-board-sync-and-agent-telemetry`

> TDD-ordered implementation steps for v0.10.0. Companion to
> `proposal.md` and `design.md`.

## 1. Documentation (already shipped in commit `cde2a13`)

- [x] 1.1 New spec `specs/project-board-sync.md` (v1.0.0) — 7-layer contract
- [x] 1.2 New spec `specs/agent-telemetry.md` (v1.0.0) — Claude Code OTLP → Langfuse
- [x] 1.3 New spec `specs/event-and-data-patterns.md` (v1.0.0) — 7 stack-agnostic patterns
- [x] 1.4 New spec `specs/cross-language-tooling.md` (v1.0.0) — `tools/<name>/` convention
- [x] 1.5 New runbook `runbooks/windows-dev-environment.md` — 4 Windows gotchas
- [x] 1.6 Update `specs/verification-before-completion.md` §4.1 — broadest-scope + tool-exit-code
- [x] 1.7 Update `specs/release-management.md` §4.4 — gitleaks + markdown style
- [x] 1.8 Update `specs/release-management.md` §6.4 — append-only ranges + verbose migrations
- [x] 1.9 Update `specs/release-management.md` §6.6 — cross-BC verification gates guidance
- [x] 1.10 Update `specs/release-management.md` §9.5 — cross-ref to project-board-sync
- [x] 1.11 Update `specs/runbook-bmad-openspec.md` §3.7.1 — design-mock HTML
- [x] 1.12 Update `specs/runbook-bmad-openspec.md` §4.1 — forward-authored retros
- [x] 1.13 CHANGELOG entry for all of the above

## 2. L2 — `templates/workflows/project-status.yml`

- [ ] 2.1 Create workflow file scaffold (push + PR triggers, GraphQL via `gh api`)
- [ ] 2.2 Implement `push to slice/**` handler: extract change-id from branch, set `Branch` field + `Base SHA` + `Status=In Progress` on the project item
- [ ] 2.3 Implement `pull_request opened` handler: set `Status=Review`
- [ ] 2.4 Implement `pull_request synchronize` handler: refresh `Base SHA`
- [ ] 2.5 Document required secrets (`GH_PROJECT_TOKEN` with `project` + `repo` scopes); add to `templates/new-project/.env.example.tmpl`

## 3. L3 — `templates/workflows/project-board-synced-check.yml`

- [ ] 3.1 Create required-status-check workflow that runs on every PR push
- [ ] 3.2 GraphQL query: fetch the project item matching the PR's branch (via `Branch` field), assert `Status=In Progress` and `Base SHA` not empty
- [ ] 3.3 Exit non-zero on assertion failure with actionable error message
- [ ] 3.4 Document the consumer-side step: add `project-board-synced` to required-status-checks list per `release-management.md` §4.1

## 4. L4 — `templates/workflows/project-state-machine.yml`

- [ ] 4.1 Workflow listening on `project_v2_item.edited` event
- [ ] 4.2 Compare `previous_status` vs `new_status`; reject if transition violates the graph (Backlog → Todo → In Progress → Review → Done)
- [ ] 4.3 On illegal transition: revert via GraphQL + post audit comment on the item's linked issue/PR
- [ ] 4.4 Honor `break-glass` label exception (per `specs/break-glass.md`)

## 5. L6 — Extend `scripts/opsx_apply_companion.py` with `--enforce-board`

- [ ] 5.1 Add `--enforce-board` CLI flag (default false to preserve backwards compat)
- [ ] 5.2 When set: after the existing pre-flight rebase + Branch/Base-SHA write, query the project item via GraphQL and assert `Status=In Progress`
- [ ] 5.3 Exit non-zero with actionable message if assertion fails

## 6. L7 — `scripts/verify_board_state.py` + skill update

- [ ] 6.1 Create `scripts/verify_board_state.py` — CLI entrypoint with args: `--change-id <id>`, `--owner <gh-user-or-org>`, `--project-number <N>`, `--repo <owner/name>`, `--expected-status <Status>` (default `Done`)
- [ ] 6.2 Implement GraphQL query to fetch the project item by `Branch` field; compare to expected status; exit non-zero on mismatch
- [ ] 6.3 Update `skills/openspec-archive-change/SKILL.md` Step 0: invoke `verify_board_state.py --expected-status Done` before archive; refuse archive on non-zero exit

## 7. Tests

- [ ] 7.1 `tests/test_verify_board_state.py` — happy path (Status=Done passes), wrong-status fail path, branch-not-on-board fail path; mock `gh api graphql` via subprocess monkeypatch
- [ ] 7.2 `tests/test_opsx_apply_companion.py` — extend existing tests: new fixture for `--enforce-board` flag; assert exit codes for each board-state scenario
- [ ] 7.3 Run full `pytest` locally; ensure existing tests still pass
- [ ] 7.4 Run `ruff check .` + `mypy --strict scripts/` clean

## 8. Verification + close-out

- [ ] 8.1 Run `python scripts/gen_indexes.py` to refresh `specs/INDEX.md` with new specs
- [ ] 8.2 CHANGELOG sweep — confirm every added/changed file in §1-§7 is referenced
- [ ] 8.3 Push branch; CI green (validate, pytest 3.11/3.12, recommend, CodeRabbit)
- [ ] 8.4 PR ready for Master review
