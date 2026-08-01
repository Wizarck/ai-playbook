# rules-gate

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

The branch ruleset could not require any of the repo-hygiene checks. Each lived
in its own workflow behind a `paths:` filter, and a required status check whose
workflow is paths-filtered never reports on a PR that misses the filter —
GitHub then blocks that PR forever, waiting for a check that will not arrive.

So the five gates ran, printed results, and enforced nothing: pytest was the
only check the ruleset could name. Discovered 2026-08-01 while fixing the
ruleset itself, where requiring any of them would have bricked future PRs.

## What

- New `.github/workflows/rules-gate.rule.yml` — one always-on job carrying all
  eight checks as steps, each guarded by `if: ${{ !cancelled() }}` so a single
  failure still reports the rest.
- Deleted `check-link-integrity`, `check-doc-language`, `check-agents-md-size`,
  `validate-pairing` and `check-rule-schemas` workflows. Verified check-for-check
  that all eight commands survive the move.
- `rule-use-cases-matrix` L3 column updated for the 38 rules that referenced the
  old shared workflow.
- Ruleset gains `rules-gate` as a required status check.

One job rather than five plus an aggregator: the job name IS the stable context,
so there is no aggregation logic to get wrong, and no second place where a
renamed job silently drops out of the gate.

## Release

`VERSION` → 0.21.0. Minor (CI surface change: five workflow files removed, one
added; no script or spec behaviour changes). Pull model.
