# v019-pull-model — Retire push pipeline; migrate to pull-model

## Why

The v0.18.0 public-flip rewrote the playbook for public consumption, but the centralised `propagate-playbook-bump.yml` push pipeline carried forward incompatibilities that surfaced post-rewrite:

1. **Privacy**: `consumers.yaml` enumerated real downstream repos by name. It had to be gitignored to keep the public repo free of internal-name leaks; `consumers.yaml.example` was committed as a schema-only mock.
2. **Broken CI**: with `consumers.yaml` gitignored, the propagate workflow failed on every tag push (run 26111328778 on v0.18.3 confirmed: `❌ consumers registry not found at /home/runner/.../consumers.yaml`).
3. **Coupling**: a central PAT with write access to N consumer repos breaks the decoupling a public reference repo should imply. Any fork inherits the workflow + needs its own consumers list to be useful.
4. **Architecture mismatch**: push model is appropriate for a private repo with one maintainer + a small fixed consumer set. Public reference repos are inherently many-to-many; pull belongs to each consumer.

User decision 2026-05-19: full pull-model migration (Option C of the triage choices: surgical vs partial vs full-pull).

## What Changes

- **Delete** `.github/workflows/propagate-playbook-bump.yml` (CI push workflow), `scripts/propagate_bump.py` (CI script), `consumers.yaml.example` (registry schema), `tests/test_propagate_bump.py`, `tests/test_consumers_yaml.py`, `docs/runbooks/propagate-bump-troubleshooting.md`, `docs/runbooks/skills-version-bump.md` (described retired propagate-skills workflow). Plus the `TestPropagateCrossRef` test class inside `tests/test_dev_flow_industrialization.py` (covered the removed `propagate_bump.ensure_dev_flow_cross_ref` migration).
- **Refactor** `scripts/issue_sync.py` to read `tracker_kind` + `jira_project` from each consumer's own `AGENTS.md` frontmatter instead of a central registry. Removes `_REGISTRY_CACHE`, `_registry_path`, `_load_registry`, `_reset_registry_cache`, `_registry_entry`.
- **Refactor** `scripts/init_org.py` to drop the `consumers.yaml` stub reset from the fork edit plan; root detection switches from `templates/rendered/...tmpl + consumers.yaml` to `templates/rendered/...tmpl + AGENTS.md`.
- **Update** `templates/new-project/AGENTS.md.tmpl` frontmatter to include `tracker_kind: github` (commented `jira_project: PROJ`) so new consumers nacen with the schema.
- **Update tests**: `tests/test_issue_sync.py` (helper writes AGENTS.md frontmatter, not consumers.yaml), `tests/test_init_org.py` (no consumers.yaml fixture), `tests/test_release_cut.py` (writes AGENTS.md frontmatter for jira_project test).
- **Docs**: rewrite `docs/runbooks/release.md` for the pull contract (cut tag → GitHub auto-release → consumers absorb at their own pace). Surgical edits to `docs/runbooks/onboard-new-project.md`, `docs/runbooks/rotate-secrets.md`, `docs/runbooks/coderabbit-fallback.md`, `docs/runbooks/hindsight-retain.md`, `docs/runbooks/INDEX.md`, `docs/concepts/issue-tracking.md` §4, `docs/concepts/release-management.md` §3.4 + §4.5.5, `docs/concepts/development-flow.md` ASCII diagrams §1 + §3, `docs/concepts/enforcement-status.md`, `docs/concepts/rule-use-cases-matrix.md`, `docs/concepts/skills-distribution.md`, `docs/concepts/root-folder-audit.md` (RETIRED v0.19.0 annotations), `docs/rules/update-playbook.rule.md`.
- **Meta**: `README.md` adds "Consumers: how to bump" pull-model section with Dependabot snippet; bumps tag in 60-second quickstart to v0.19.0; rewrites Status block. `VERSION` bumps 0.18.3 → 0.19.0. `CHANGELOG.md` prepends v0.19.0 entry with migration notes for forks/consumers.

## Impact

- **BREAKING for forks of the playbook** that ran the propagate pipeline: those forks lose their automated bump-PR-to-consumers behaviour. Forks should delete their local `consumers.yaml`, revoke any `PLAYBOOK_PROPAGATION_TOKEN` PAT.
- **BREAKING for consumers that declared `tracker_kind` in the playbook's `consumers.yaml`**: those keys must move to each consumer's own `AGENTS.md` frontmatter. Migration documented in CHANGELOG v0.19.0.
- **Non-breaking for consumers that already had AGENTS.md frontmatter without tracker_kind**: `scripts/issue_sync.py` now raises `RuntimeError` until they add `tracker_kind`. The error message points to the required keys. Default `tracker_kind: github` is safe for nearly all consumer setups.
- **Non-breaking for the `update-playbook` rule**: bumping `.ai-playbook` to a semver tag remains the same operation; the rule's trigger text now references Dependabot/Renovate PRs instead of the retired propagate workflow.

## Versioning

`VERSION` bumps 0.18.3 → **0.19.0**. Per the v0.18.3 STOP-FOR-REVIEW gate, v0.19.x absorbs post-review fix iterations; this is the first such iteration. v0.20.0 final cut remains gated on explicit user OK.
