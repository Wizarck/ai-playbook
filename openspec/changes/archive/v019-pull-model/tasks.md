# v019-pull-model — Tasks

## Group 1 — Delete push pipeline (mechanical)

- [x] 1.1 Delete `.github/workflows/propagate-playbook-bump.yml`
- [x] 1.2 Delete `scripts/propagate_bump.py`
- [x] 1.3 Delete `consumers.yaml.example`
- [x] 1.4 Delete `tests/test_propagate_bump.py`
- [x] 1.5 Delete `tests/test_consumers_yaml.py`
- [x] 1.6 Delete `docs/runbooks/propagate-bump-troubleshooting.md`
- [x] 1.7 Delete `docs/runbooks/skills-version-bump.md` (described retired propagate-skills workflow)

## Group 2 — Refactor issue_sync.py to read AGENTS.md frontmatter

- [x] 2.1 Remove `_REGISTRY_CACHE`, `_registry_path`, `_load_registry`, `_reset_registry_cache`, `_registry_entry` from `scripts/issue_sync.py`
- [x] 2.2 Add `_read_tracker_config(consumer_root)` helper that parses AGENTS.md frontmatter via the existing `parse_frontmatter`
- [x] 2.3 Refactor `jira_project_for(consumer_root)` to consult the frontmatter helper
- [x] 2.4 Refactor `decide_surface(consumer_root)` to consult the frontmatter helper; preserve the `personal: true` short-circuit
- [x] 2.5 Update module docstring §"Surface choice" to reference AGENTS.md frontmatter as the source of truth
- [x] 2.6 Update error messages: "consumers.yaml" → "AGENTS.md frontmatter" with explicit `tracker_kind` / `jira_project` keys in the FIX hint

## Group 3 — Refactor init_org.py + templates

- [x] 3.1 Update `_detect_playbook_root` to look for `templates/rendered/...tmpl + AGENTS.md` (was + `consumers.yaml`)
- [x] 3.2 Drop the `consumers.yaml` FileEdit from `build_edit_plan`; remove `_consumers_stub`
- [x] 3.3 Update the `__RESET_CONSUMERS__` branch in `apply_edits` (now dead code) and the "Next steps" message
- [x] 3.4 Remove `docs/runbooks/propagate-bump-troubleshooting.md` from the runbook-substitution loop (file deleted in 1.6)
- [x] 3.5 Update `templates/new-project/AGENTS.md.tmpl` frontmatter to include `tracker_kind: github` (commented `# jira_project: PROJ`) with explanatory inline comment
- [x] 3.6 Bump the template's `inherits_from:` pin from v0.13.2 to v0.19.0

## Group 4 — Tests

- [x] 4.1 `tests/test_issue_sync.py`: replace `_make_registry()` with parametrised `_make_consumer(..., tracker_kind=..., jira_project=...)`; update all `test_decide_surface_*` and `test_jira_project_for_*` to write AGENTS.md frontmatter instead of consumers.yaml
- [x] 4.2 Remove `_reset_registry_cache()` calls (function no longer exists)
- [x] 4.3 Update assertions to match new error strings ("no tracker_kind", "no jira_project" in AGENTS.md)
- [x] 4.4 `tests/test_init_org.py`: update `_make_fake_playbook` (drop consumers.yaml + propagate-bump-troubleshooting.md, add AGENTS.md as the detection anchor); fix `test_apply_replaces_wizarck_with_acme` to no longer assert on consumers.yaml
- [x] 4.5 `tests/test_release_cut.py::test_run_release_private_dry_run_skips_api`: write AGENTS.md with `tracker_kind: jira` + `jira_project: consumer-a` instead of a consumers.yaml fixture
- [x] 4.6 `tests/test_dev_flow_industrialization.py`: delete the `TestPropagateCrossRef` class (its target `propagate_bump.ensure_dev_flow_cross_ref` was deleted in 1.2); update module docstring with a NOTE on Opción 1 retirement
- [x] 4.7 `python -m pytest tests/ -q` → 981 passed, 2 skipped, 0 failed

## Group 5 — Docs

- [x] 5.1 Rewrite `docs/runbooks/release.md` for the pull contract (cut tag → consumers absorb at their own pace)
- [x] 5.2 `docs/runbooks/onboard-new-project.md`: drop the consumers.yaml registration step + the `--register-in` flag from the bootstrap.py example; add an optional "Configure submodule-bump automation" section with a Dependabot snippet
- [x] 5.3 `docs/runbooks/rotate-secrets.md`: remove section A (PAT rotation for the retired `PLAYBOOK_PROPAGATION_TOKEN`); add a top-of-table note about the retirement; renumber sections B/C/D
- [x] 5.4 `docs/runbooks/coderabbit-fallback.md`: drop the dead "Related" link to propagate-bump-troubleshooting.md
- [x] 5.5 `docs/runbooks/hindsight-retain.md`: replace the `PLAYBOOK_PROPAGATION_TOKEN` rotation example with `GITHUB_TOKEN`; drop the dead "Related" link
- [x] 5.6 `docs/runbooks/INDEX.md`: remove the rows for the two deleted runbooks
- [x] 5.7 `docs/concepts/issue-tracking.md`: update §4 to declare AGENTS.md frontmatter as the configuration source; add the YAML schema snippet
- [x] 5.8 `docs/concepts/release-management.md`: update §3.4 (supersede now applies within each consumer's own CI); §4.5.5 (signoff contract applies to whichever bump-bot a consumer adopts); §4.5 (reference impl annotation); §6.7 (drop consumer-side bump narrative); §10 (workflow inventory annotation)
- [x] 5.9 `docs/concepts/development-flow.md`: rewrite the ASCII flow diagrams in §1 + §3 to reflect the pull lifecycle; annotate §5 "industrialisation" matrix row for the dev-flow cross-ref migration
- [x] 5.10 `docs/concepts/enforcement-status.md`: update the rollout-strategy row to reflect the pull contract
- [x] 5.11 `docs/concepts/skills-distribution.md`: replace the dead skills-version-bump.md cross-ref with release.md
- [x] 5.12 `docs/concepts/rule-use-cases-matrix.md`: update the update-playbook trigger text
- [x] 5.13 `docs/concepts/root-folder-audit.md`: annotate the consumers.yaml + propagate-playbook-bump.yml rows with "RETIRED v0.19.0" without deleting the historical decision rationale
- [x] 5.14 `docs/rules/update-playbook.rule.md`: update the Trigger text from "merges a propagate-playbook-bump PR" to "Dependabot/Renovate submodule-update PR"

## Group 6 — Meta + release

- [x] 6.1 `VERSION`: 0.18.3 → 0.19.0
- [x] 6.2 `CHANGELOG.md`: prepend v0.19.0 entry with BREAKING / Removed / Changed sections + Migration notes for forks and consumers
- [x] 6.3 `README.md`: bump 60-second quickstart tag pin to v0.19.0; add "Consumers: how to bump" section with Dependabot snippet; rewrite Status block; update the prior-milestones list
- [x] 6.4 `specs/zombies-manifest.yaml`: add a header comment explaining why the v0.19.0 deletions are NOT consumer-side fossils (so they belong in the CHANGELOG, not in this manifest)
- [x] 6.5 Run full local CI: pytest, ruff, mkdocs --strict, validate_pairing, check_link_integrity, check_doc_language, check_agents_md_size, cleanup-zombies validate
- [x] 6.6 Open PR; add `[no-doc-impact]` to title for the two co-edit-pairs that touch one side without the other (materialise-skills link update; zombies-manifest comment-only edit)
- [ ] 6.7 Merge PR after CI green + AI-reviewer signoff
- [ ] 6.8 Tag v0.19.0 + push tag; GitHub auto-creates Release from the CHANGELOG section
