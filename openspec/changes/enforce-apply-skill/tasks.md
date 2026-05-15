# tasks — `enforce-apply-skill`

> TDD-ordered implementation steps. Each task is a worker→QA pair per [runbook-bmad-openspec.md](../../../specs/runbook-bmad-openspec.md) §3.2.
> Citations: [proposal.md](proposal.md), [design.md](design.md).

## Owns (write_paths)

* `scripts/openspec_apply_marker.py`
* `tests/test_openspec_apply_marker.py`
* `tests/test_apply_enforce_hook_template.py`
* `skills/openspec-apply-change/SKILL.md`
* `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`
* `templates/new-project/.claude/settings.json.tmpl`
* `specs/apply-skill-enforcement.md`
* `specs/runbook-bmad-openspec.md` (additive — §3.1.1 only)
* `specs/agentic-failures.md` (additive — new row in §2)
* `specs/enforcement-status.md` (additive — new row + flip runbook row to 🟡→partial-with-detail)
* `CHANGELOG.md` (additive — v0.14.0 entry)
* `VERSION`

## Reads

* `scripts/_break_glass.py` — canonical error shape helper
* `scripts/verify_llm_routing.py` — reference for AST/parser scripts that integrate with pre-commit (similar shape)
* `scripts/verdict_lint.py` — reference for tool-pattern of validation scripts
* `templates/new-project/.claude/settings.json.tmpl` — current structure to preserve

## Tasks (TDD order)

### Phase A — Marker helper script (foundation)

- [ ] **T1 — write failing tests for marker helper** in `tests/test_openspec_apply_marker.py`:
  - `test_start_creates_marker_with_required_fields` — invoke `start`, assert `.apply_log.jsonl` exists, last line has `event:"start"`, `change_id`, `session_id`, `ts`, `skill_version`.
  - `test_start_is_idempotent_within_session` — call `start` twice with same `session_id`, assert 2 records (audit-visible), no error.
  - `test_stop_records_outcome_and_tasks` — `stop` writes `event:"stop"`, `outcome`, `tasks_completed`, `tasks_total`.
  - `test_is_active_matches_session` — after `start`, `is_active` exits 0 for matching session; exit 1 for different session.
  - `test_session_started_returns_true_after_start` — `session_started` exits 0 if any `start` exists for current session; exit 1 if marker file empty.
  - `test_corrupt_jsonl_is_recoverable` — pre-seed marker with a malformed line; `session_started` and `is_active` still find valid records on other lines.
  - `test_override_writes_audit_record` — `override` subcommand writes `event:"override"` with `reason` and `file_path`.
  - `test_missing_change_folder_errors_per_standard` — `start --change-id nonexistent` exits non-zero with the canonical FIX/OVERRIDE error shape (per [error-message-standard.md](../../../specs/error-message-standard.md)).
  - Run: `pytest tests/test_openspec_apply_marker.py -x` → RED.

- [ ] **T2 — implement `scripts/openspec_apply_marker.py`**:
  - argparse-driven CLI with 6 subcommands (start, stop, override, is_active, session_started, list).
  - JSONL append helper (open in `"a"` mode, atomic-ish on POSIX; Windows uses native append).
  - Session ID resolution: `$CLAUDE_SESSION_ID` env → fallback to `local-<git-user>-<host>-<pid>`.
  - User: `git config user.email` if available; else `unknown`.
  - Agent: from `$CLAUDE_AGENT` env if set; else `unknown`.
  - Skill version: arg default = `"1.0"`; SKILL.md frontmatter is canonical, but caller passes it explicitly.
  - Path resolution: project root is `cwd`'s nearest ancestor with `openspec/` subdir. If none found, exit non-zero.
  - Run: `pytest tests/test_openspec_apply_marker.py -x` → GREEN.

- [ ] **T3 — pre-commit + CI wiring for the new script** (optional this slice; the script is invoked by callers, not by linter):
  - Confirm `pyproject.toml` includes the script entry point so `python -m scripts.openspec_apply_marker` works (mirrors existing scripts).
  - No new pre-commit entry needed; the script doesn't lint anything.
  - Manual sanity: invoke `python -m scripts.openspec_apply_marker start --change-id enforce-apply-skill` in this branch; assert marker created (this is the dogfooding step — the marker will be in our own commit).

### Phase B — Hook template

- [ ] **T4 — write failing tests** for `tests/test_apply_enforce_hook_template.py`:
  - `test_hook_template_renders_clean_python` — render the `.tmpl` (placeholder substitution), assert it `ast.parse`-es without error and shebang is correct.
  - `test_hook_blocks_when_no_marker` — temp project dir with one fake change in `applying` state; invoke rendered hook script with stdin `{"tool_name":"Edit","tool_input":{"file_path":"<write_paths_match>"}}`; assert exit code 2 + stderr matches `❌ apply phase bypass detected`.
  - `test_hook_allows_when_marker_present` — same setup, but pre-write a `start` record to `.apply_log.jsonl`; invoke hook; assert exit 0, no stderr.
  - `test_hook_allows_path_outside_write_paths` — file_path is in the repo but NOT in any change's write_paths; assert exit 0.
  - `test_hook_allows_path_in_changes_folder` — file_path is `openspec/changes/<id>/proposal.md`; assert exit 0 (proposal refinement).
  - `test_hook_honours_override_env` — `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE=<reason>` set; hook exits 0 AND `.apply_log.jsonl` gets an `override` record.
  - `test_hook_fails_open_on_missing_openspec_cli` — synthetic test simulating absent `openspec` binary; hook prints warning to stderr but exits 0.
  - Run: `pytest tests/test_apply_enforce_hook_template.py -x` → RED.

- [ ] **T5 — implement `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`**:
  - Shebang `#!/usr/bin/env python3` + docstring with version + spec link.
  - Read JSON from stdin (Claude Code hook protocol).
  - Extract `tool_input.file_path`, normalise to project-relative.
  - Walk `openspec/changes/*/tasks.md`; parse "Owns (write_paths)" section per design §1.3 + §2.2 step 4.
  - For each matching active change: invoke `python scripts/openspec_apply_marker.py session_started --change-id <id>` via subprocess.
  - Honour `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` env per design §2.2 step 6a.
  - Print canonical error per [error-message-standard.md](../../../specs/error-message-standard.md) on block; exit 2.
  - Run: `pytest tests/test_apply_enforce_hook_template.py -x` → GREEN.

- [ ] **T6 — update `templates/new-project/.claude/settings.json.tmpl`**:
  - Add `hooks.PreToolUse` entries for `Edit`, `Write`, `MultiEdit` (if multi-edit is in scope per current hook registry) pointing at the new hook script.
  - Preserve any existing entries (additive).
  - Manual diff review: existing hooks (e.g., `bootstrap-directive`, `verdict_lint`) keep working.

### Phase C — Skill update

- [ ] **T7 — update `skills/openspec-apply-change/SKILL.md`**:
  - Bump frontmatter `version: "1.0"` → `version: "1.1"`.
  - Insert new step 0 per design §3.
  - Renumber existing steps if necessary (existing numbering uses `1.`, `2.`, ... `4b.`; insert step 0 above step 1).
  - Cross-reference: link to `specs/apply-skill-enforcement.md` from step 0.

- [ ] **T8 — manual smoke test of the updated skill** (since `/openspec-apply-change` is a Claude Code skill, no automated test):
  - In a clean worktree with `openspec/changes/enforce-apply-skill/` present, invoke `/openspec-apply-change enforce-apply-skill` (via Claude session).
  - Verify marker line appears in `.apply_log.jsonl` BEFORE first context-file read.
  - Confirm tasks ⊆ {T1..T17} of this very file are walked by the skill (recursive dogfooding).
  - Document any issues observed in this commit's PR body.

### Phase D — Specs

- [ ] **T9 — write `specs/apply-skill-enforcement.md`**:
  - Per design §5 invariants INV-1..INV-4.
  - Sections: §1 Marker contract (lift from design.md §1) · §2 Hook contract (lift from §2) · §3 Break-glass (per [break-glass.md](../../../specs/break-glass.md)) · §4 Invariants · §5 Adoption checklist (for consumers) · §6 Retros + audit cadence.
  - Add to `specs/INDEX.md` alphabetically.

- [ ] **T10 — update `specs/runbook-bmad-openspec.md`**:
  - Add §3.1.1 immediately after §3.1: "Apply phase orchestration: skill-only".
  - Body: 1-2 paragraphs pointing at `specs/apply-skill-enforcement.md`. Restate the rule + the failure mode + the break-glass clause. Cross-reference §3.4 (self-validation gates) and §3.2 (worker/QA pairing).

- [ ] **T11 — update `specs/agentic-failures.md`**:
  - Add a new row in §2 taxonomy: `2.X apply_phase_bypass` — definition, symptoms, detector (the hook), severity (S2: violates documented workflow gate).
  - Renumber subsequent rows if the file uses sequential numbering.

- [ ] **T12 — update `specs/enforcement-status.md`**:
  - Add a new row for `apply-skill-enforcement.md` at ✅ wired with enforcement detail (script + hook + tests + pre-commit-equivalence note).
  - Update existing `runbook-bmad-openspec.md` row to mention the new spec's coverage of the apply gate.

### Phase E — Versioning + changelog

- [ ] **T13 — update `VERSION`**: `0.13.3` → `0.14.0`.

- [ ] **T14 — add `CHANGELOG.md` entry** under `[0.14.0] — 2026-05-15`:
  - Section: **Added**.
    - `scripts/openspec_apply_marker.py` — marker helper (6 subcommands, JSONL append).
    - `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` — PreToolUse hook blocking Edit/Write without marker.
    - `specs/apply-skill-enforcement.md` — new spec, invariants INV-1..INV-4.
    - Skill `openspec-apply-change` v1.1: new step 0 writes apply-session start marker.
  - Section: **Changed**.
    - `specs/runbook-bmad-openspec.md` §3.1.1 (new) — apply phase orchestration rule.
    - `specs/agentic-failures.md` §2 — new row `apply_phase_bypass`.
    - `specs/enforcement-status.md` — new row + apply-gate detail on runbook row.
    - `templates/new-project/.claude/settings.json.tmpl` — registers the new hook.
  - Section: **Migration** (for consumers).
    - 5-step adoption checklist (bump submodule, copy hook, update settings, add `apply.handler` to project schema if customised, point AGENTS.md at new spec).
    - Link to `specs/apply-skill-enforcement.md` §5.
  - Section: **Tests**.
    - 8 new tests in `test_openspec_apply_marker.py`; 7 new tests in `test_apply_enforce_hook_template.py`.

### Phase F — Manual dogfooding + PR

- [ ] **T15 — dogfooding pass**:
  - In this very branch, simulate adopting the hook: copy `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` to `.claude/hooks/openspec-apply-enforce.py` (substituting placeholders).
  - Register in `.claude/settings.json` (project-local).
  - Re-run `python -m scripts.openspec_apply_marker start --change-id enforce-apply-skill` (already done in T3, but confirm marker still present).
  - Make a synthetic `Write` to one of the slice's own write_paths; confirm hook ALLOWS (because marker exists for this session_id).
  - Make a synthetic `Write` to a write_paths file of another (fake) "applying" change without marker; confirm hook BLOCKS.

- [ ] **T16 — final review pass**:
  - Self-validation gates per §3.4 of runbook: scope, anti-duplication, traceability, TDD compliance, naming.
  - Run all tests one final time: `pytest tests/`.
  - Confirm CHANGELOG entry includes every modified file group.

- [ ] **T17 — open PR**:
  - Branch: `slice/enforce-apply-skill` → base `main`.
  - PR title: `feat(enforce-apply-skill): L1+L2+L3 apply-phase orchestration enforcement (v0.14.0)`.
  - PR body: 3 sections — Summary, Test plan, Migration (cross-link CHANGELOG migration section).
  - Request 4-layer review per [parallel-review.md](../../../specs/parallel-review.md) (Blind, Edge-case, Acceptance, Holistic).
