# Root folder cleanup audit (v0.17.1)

## Problem

Across 50+ releases the playbook accumulated files at the repo root whose
purpose is no longer obvious to a first-time visitor:

- `FEEDBACK.md` — append-only gripe log; never triaged since v0.1.0 (sole consumer).
- `mcp-servers-base.yaml` — base template, sitting next to `mkdocs.yml` and `pyproject.toml` with no folder grouping.
- `pricing.yaml` — runtime config sitting next to `mcp-servers-base.yaml` with no obvious owner.
- `ai_playbook.egg-info/` — `pip install -e .` build artefact accidentally tracked at some point; covered by `.gitignore` glob `*.egg-info/` already but the physical directory lingers.
- `.github/workflows/issue-sync.yml` — multi-tenant Jira/GH-Issues sync workflow; the sole consumer (Arturo) does not use it.

The v0.20.0 architectural reset (see
`~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md`) requires a
clean root for the public-showcase cut. This slice closes the audit before
slice 4 begins the filesystem reorg.

## Proposed change

For every file currently visible at the playbook root, attach an explicit
**KEEP / DELETE / MOVE** decision with a one-line rationale. Apply the
decisions in one PR. Extend `specs/zombies-manifest.yaml` so consumer
checkouts (5 sister repos) auto-clean their local copies on the next bump.

Per-file ledger lives in `docs/concepts/root-folder-audit.md` (committed
record, also referenced by the v0.17.1 CHANGELOG entry).

## Deliverables

- Per-file ledger in `docs/concepts/root-folder-audit.md` covering every root
  file + every `.github/workflows/*.yml`.
- DELETE: `FEEDBACK.md`, `ai_playbook.egg-info/`, `.github/workflows/issue-sync.yml`.
- MOVE: `mcp-servers-base.yaml` → `templates/rendered/mcp-servers-base.yaml.tmpl`;
  `pricing.yaml` → `configs/pricing.yaml`. Internal references in scripts and
  tests rewritten.
- Extend `specs/zombies-manifest.yaml` with v3 entries for each
  delete/move; bump `manifest_version`.
- VERSION → 0.17.1; CHANGELOG entry under `## [0.17.1]`.

## Out of scope

- Standalone CLIs `scripts/cost_report.py`, `scripts/lifecycle_check.py`,
  `scripts/budget_disable_check.py`, `scripts/deprecation_watcher.py`,
  `scripts/simulate_model_migration.py` — slice 6 (telemetry, v0.19.1)
  absorbs them. They continue to work standalone in v0.17.1.
- Filesystem-wide reorg under `docs/`, `scripts/`, `specs/` — slice 4
  (v0.18.0 BREAKING).
- Docs/spec cross-reference cleanup for FEEDBACK.md mentions — slice 5
  (v0.19.0 content rewrite) rewrites those docs anyway.
