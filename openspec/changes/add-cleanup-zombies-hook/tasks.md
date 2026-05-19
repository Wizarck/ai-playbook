# tasks — `add-cleanup-zombies-hook`

> TDD-ordered implementation steps. Each task is a worker→QA pair per [runbook-bmad-openspec.md](../../../specs/runbook-bmad-openspec.md) §3.2.
> Citations: [proposal.md](proposal.md), [design.md](design.md).

## Owns (write_paths)

* `scripts/cleanup_zombies.py`
* `tests/test_cleanup_zombies.py`
* `specs/cleanup-zombies.md`
* `specs/zombies-manifest.yaml`
* `specs/enforcement-status.md` (additive — new row)
* `docs/development-flow.md` (additive — §5 enforcement table row)
* `runbooks/release.md` (additive — checklist item)
* `templates/new-project/scripts/git-hooks/post-merge.tmpl`
* `templates/new-project/scripts/git-hooks/post-checkout.tmpl`
* `CHANGELOG.md` (additive — v0.15.0 entry)
* `VERSION`

## Reads

* `scripts/auto_managed.py` — orphan-source detection patterns; cleanup uses its `--prune-orphans` mode
* `scripts/sync_skills_local.py` (in consumer-a) — reference for the hook-invocation pattern
* `scripts/_break_glass.py` — canonical error shape helper
* `specs/break-glass.md` — `AIPLAYBOOK_*` env namespace
* `specs/error-message-standard.md` — error message format
* `specs/cross-os-validation.md` — Windows/macOS/Linux test matrix expectations

## Tasks (TDD order)

### Phase A — Manifest schema + validator (foundation)

- [ ] **T1 — write failing tests for manifest schema validation** in `tests/test_cleanup_zombies.py`:
  - `test_manifest_loads_with_required_top_level_keys` — assert `version`, `manifest_version`, `entries` present.
  - `test_entry_requires_id_path_tier_action_safety` — missing any field → `validate` exits 2.
  - `test_tier_must_be_1_2_or_3` — invalid tier → exit 2.
  - `test_safety_must_be_known_name` — unknown safety string → exit 2.
  - `test_tier2_entry_requires_rename_from_and_to` — missing rename fields → exit 2.
  - `test_tier1_file_exact_match_requires_expected_sha256` — missing sha → exit 2.
  - `test_manifest_version_must_be_monotonic_format` — `YYYY-MM-DD.N` regex.
  - Run: `pytest tests/test_cleanup_zombies.py -k manifest -x` → RED.

- [ ] **T2 — implement manifest loader + validator** in `scripts/cleanup_zombies.py`:
  - `_load_manifest(path) -> dict` — yaml.safe_load, raises ManifestError on missing keys.
  - `validate` subcommand — calls loader, prints results, exits 0/2.
  - Run: `pytest tests/test_cleanup_zombies.py -k manifest -x` → GREEN.

### Phase B — Safety checks (per-policy)

- [ ] **T3 — write failing tests for each safety check** (one test each):
  - `test_file_exact_match_only_passes_on_sha_match` / `_fails_on_sha_mismatch`.
  - `test_check_gitmodules_first_allows_when_path_absent_from_gitmodules` / `_blocks_when_present`.
  - `test_file_mtime_gt_passes_when_older_than_n_days` / `_fails_when_newer`.
  - `test_yaml_literal_rename_matches_scalar_only_not_key` (use yaml.SafeLoader round-trip).
  - `test_yaml_literal_rename_skips_invalid_yaml` (consumer has YAML syntax error).
  - `test_directory_orphan_uses_git_ls_files` (mock subprocess).
  - `test_report_only_never_passes_action_gate`.
  - Run: `pytest tests/test_cleanup_zombies.py -k safety -x` → RED.

- [ ] **T4 — implement safety check dispatcher**:
  - `SAFETY_CHECKS = {"file_exact_match_only": _check_sha, ...}`
  - Each check takes `(target: Path, entry: dict, consumer_root: Path) -> SafetyResult`.
  - `SafetyResult` is a small dataclass `(passed: bool, reason: str)`.
  - Run: `pytest tests/test_cleanup_zombies.py -k safety -x` → GREEN.

### Phase C — Decision flow + channel writers

- [ ] **T5 — write failing tests for decision flow**:
  - `test_tier1_delete_executes_only_with_apply_flag` — `--report-only` does not delete.
  - `test_tier2_rename_executes_only_with_apply_flag` — same.
  - `test_tier3_always_records_advisory_never_modifies` — even with `--apply`.
  - `test_safety_fail_downgrades_to_tier3_advisory` — Tier 1 entry with failed safety → recorded as advisory, not deleted.
  - `test_missing_target_skips_entry_silently` — no warning if zombie absent.
  - Run: RED.

- [ ] **T6 — write failing tests for channel writers**:
  - `test_stdout_summary_format` — matches "🧹 cleanup: X deleted, Y renamed, Z reports".
  - `test_stdout_suppressed_with_quiet_flag`.
  - `test_report_file_written_on_non_empty_run` — contains manifest_version, deleted list, renamed list, reports list.
  - `test_report_file_removed_on_empty_run` — clean-state signal.
  - `test_injected_context_appended_when_file_exists` — single line, no duplication on repeated runs.
  - `test_injected_context_skipped_when_file_missing` — no error.
  - Run: RED.

- [ ] **T7 — implement decision flow + channels in `cleanup_zombies.py`**:
  - `run(manifest, consumer_root, apply: bool, channels: ChannelSet) -> int`.
  - `ChannelSet` class with the 3 writers.
  - Run T5+T6: GREEN.

### Phase D — Exit code policy + break-glass

- [ ] **T8 — write failing tests for exit code policy + break-glass**:
  - `test_default_exit_zero_even_on_safety_errors`.
  - `test_default_exit_zero_when_manifest_missing`.
  - `test_default_exit_zero_when_consumer_root_not_found`.
  - `test_break_glass_env_skips_everything_exit_zero` — set `AIPLAYBOOK_CLEANUP_SKIP=1`, no file mutations.
  - `test_validate_subcommand_exits_2_on_bad_manifest` — only place non-zero exit is allowed.
  - Run: RED.

- [ ] **T9 — implement exit code policy + env handling**:
  - Wrap `main()` in try/except that catches everything except `SystemExit` and exits 0.
  - Check `AIPLAYBOOK_CLEANUP_SKIP` early.
  - Run T8: GREEN.

### Phase E — Manifest v1 data + spec doc

- [ ] **T10 — author `specs/zombies-manifest.yaml`** with 16 entries from [design.md](design.md) §4:
  - 8 × Tier 1, 1 × Tier 2 (consumer-c-legacy-rename), 7 × Tier 3.
  - For each Tier 1 `file_exact_match_only`: compute `expected_sha256` from the historical commit (`git show <commit>:<path>` → sha256).
  - Run `python scripts/cleanup_zombies.py validate` → exit 0.

- [ ] **T11 — author `specs/cleanup-zombies.md`** — the contract spec:
  - § 1 Purpose
  - § 2 Manifest schema (links to YAML)
  - § 3 Tier semantics
  - § 4 Safety checks table
  - § 5 Channels contract
  - § 6 Exit code policy
  - § 7 Break-glass clause
  - § 8 Consumer adoption checklist
  - § 9 Cross-refs to `auto-managed-sections.md`, `break-glass.md`, `error-message-standard.md`, `enforcement-status.md`.

### Phase F — Hook templates

- [ ] **T12 — author hook templates** under `templates/new-project/scripts/git-hooks/`:
  - `post-merge.tmpl` — full bash script per [design.md](design.md) §3.1.
  - `post-checkout.tmpl` — analogous, gated on `$3 == "1"`.
  - Both LF-ended (matches `.gitattributes` template).
  - Add a smoke `test_hook_template_lints_under_shellcheck` test (skip on systems without shellcheck).

### Phase G — Doc updates within scope

- [ ] **T13 — update `specs/enforcement-status.md`**:
  - New row: `cleanup-zombies.md` | ✅ wired | script + tests + hook template + manifest validator pre-commit.

- [ ] **T14 — update `docs/development-flow.md` §5 enforcement table**:
  - New row: "Consumer-side playbook zombie cleanup" | 🟡 partial (auto-fires per hook; no real consumer adopted day 1) | `scripts/cleanup_zombies.py` + hook templates.

- [ ] **T15 — update `runbooks/release.md`**:
  - Pre-cut checklist: "If this release REMOVED or RENAMED any consumer-surface file (template, script consumers invoke, frontmatter field), append an entry to `specs/zombies-manifest.yaml` and bump `manifest_version`."

- [ ] **T16 — update `CHANGELOG.md`**:
  - New `[0.15.0]` section per release.md conventions.

- [ ] **T17 — bump `VERSION`** `0.14.1` → `0.15.0`.

### Phase H — Verification

- [ ] **T18 — full pytest run** — `pytest tests/test_cleanup_zombies.py -v` → all green, ≥ 15 tests.

- [ ] **T19 — pre-commit run** — `pre-commit run --all-files` → green (ruff, schema-validate, gitleaks).

- [ ] **T20 — manual smoke** — in a sibling sandbox dir simulating a consumer:
  - Create `.ai-playbook/` (symlink to actual playbook); add `.github/workflows/release-cut.yml` matching the historical sha.
  - Run `python <playbook>/scripts/cleanup_zombies.py --apply`.
  - Verify: file deleted, `zombie-report.md` written, stdout summary printed.
  - Run again: zero zombies, report removed.
  - Run with `AIPLAYBOOK_CLEANUP_SKIP=1`: no-op exit 0.

- [ ] **T21 — commit + push + PR**.

## Self-validation checklist (per `runbook-bmad-openspec.md` §3.4)

- [ ] All `Owns (write_paths)` entries touched.
- [ ] No path outside `Owns` modified.
- [ ] Test count ≥ 15.
- [ ] `pytest` green.
- [ ] `pre-commit run --all-files` green.
- [ ] `python scripts/cleanup_zombies.py validate` exits 0 on shipped manifest.
- [ ] `python scripts/cleanup_zombies.py version` prints manifest_version.
- [ ] CHANGELOG `[0.15.0]` entry present.
- [ ] VERSION bumped.
