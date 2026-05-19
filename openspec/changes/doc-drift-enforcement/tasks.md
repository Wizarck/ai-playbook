# tasks — `doc-drift-enforcement`

> TDD-ordered implementation steps. Citations: [proposal.md](proposal.md), [design.md](design.md).

## Owns (write_paths)

* `scripts/check_doc_drift.py`
* `tests/test_check_doc_drift.py`
* `specs/co-edit-pairs.yaml`
* `specs/doc-drift-enforcement.md`
* `.github/workflows/doc-drift-check.yml`
* `specs/enforcement-status.md`
* `docs/development-flow.md`
* `README.md`
* `tests/test_apply_enforce_hook_template.py`
* `CHANGELOG.md`
* `VERSION`
* `runbooks/`

## Reads

* `scripts/cleanup_zombies.py` — argparse + exit-code convention reference
* `scripts/_break_glass.py` — canonical error shape helper
* `specs/break-glass.md` — `AIPLAYBOOK_*` env namespace + exit-code policy
* `specs/error-message-standard.md` — error message format
* `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` — root cause for 3 failing tests
* `.github/workflows/branch-name-validator.yml` — sticky-comment + CI gate precedent

## Tasks (TDD order)

### Phase A — Manifest schema + loader

- [x] **T1 — write failing tests for manifest schema validation** in `tests/test_check_doc_drift.py`:
  - `test_manifest_loads_with_required_top_level_keys` — assert `version`, `manifest_version`, `pairs` present.
  - `test_pair_requires_id_code_doc_tier_reason` — missing any field → `validate` exits 2.
  - `test_tier_must_be_1_2_or_3` — invalid tier → exit 2.
  - `test_manifest_schema_break_exits_2` — malformed YAML → exit 2.

- [x] **T2 — implement manifest loader + validator** in `scripts/check_doc_drift.py`.

### Phase B — Drift detection

- [x] **T3 — write failing tests** for `check` subcommand:
  - `test_no_changed_files_returns_zero` — empty diff → exit 0.
  - `test_unknown_file_outside_any_pair_returns_zero` — file not in any pair → exit 0.
  - `test_code_side_touched_doc_side_not_touched_returns_one` — drift detected.
  - `test_doc_side_touched_code_side_not_touched_returns_one` — drift detected.
  - `test_both_sides_touched_returns_zero` — clean.
  - `test_multi_pair_violation_lists_all` — N pairs broken → exit 1, message lists N.
  - `test_glob_pattern_on_code_side_matches_multiple_files` — `scripts/rules/*.rule.py` glob.

- [x] **T4 — implement drift detector** using `fnmatch` and `git diff`.

### Phase C — Escape hatch

- [x] **T5 — write failing tests** for escape-hatch logic:
  - `test_no_doc_impact_in_pr_title_bypasses_drift` — `[no-doc-impact]` in PR title → exit 0.
  - `test_escape_hatch_case_insensitive` — `[No-Doc-Impact]` works too.
  - `test_escape_hatch_only_in_title_not_body` — escape phrase in body alone does NOT bypass.

- [x] **T6 — implement `--pr-title` flag** + escape-hatch detection.

### Phase D — Manifest seed

- [x] **T7 — seed `specs/co-edit-pairs.yaml`** with ~10 grounded pairs based on a real `specs/` + `scripts/` audit:
  - `cleanup-zombies` pair
  - `git-worktree-bare-layout` pair
  - `auto-managed-sections` pair
  - `break-glass` pair
  - `apply-skill-enforcement` (hook template + script) pair
  - `error-message-standard` pair
  - `verdict-contract` pair
  - `release-management` pair
  - `mcp-servers-schema` pair
  - `doc-drift-enforcement` pair (self-reference)

### Phase E — Spec + workflow + audit drift fixes

- [x] **T8 — write `specs/doc-drift-enforcement.md` v1.0.0**.
- [x] **T9 — write `.github/workflows/doc-drift-check.yml`** with sticky-comment + hard-fail.
- [x] **T10 — add doc-drift row to `specs/enforcement-status.md`**.
- [x] **T11 — add doc-drift row to `docs/development-flow.md` §5**.
- [x] **T12 — fix 3 failing tests in `tests/test_apply_enforce_hook_template.py`** by tightening `_invoke_hook` env isolation.
- [x] **T13 — bump README.md status to v0.16.0**.
- [x] **T14 — audit `runbooks/` + `docs/` for 4 dead cross-refs and fix**.
- [x] **T15 — bump `VERSION` 0.15.0 → 0.16.0**.
- [x] **T16 — append v0.16.0 entry to `CHANGELOG.md`**.

### Phase F — Validation

- [x] **T17 — `pytest tests/` all green** (incl. ≥15 new tests + 3 previously-failing now green).
- [x] **T18 — `python scripts/cleanup_zombies.py validate` exit 0**.
- [x] **T19 — synthetic probe**: `python scripts/check_doc_drift.py --diff-files scripts/cleanup_zombies.py` → exit 1.
- [x] **T20 — synthetic escape-hatch probe**: same diff + `--pr-title "test [no-doc-impact]"` → exit 0.
