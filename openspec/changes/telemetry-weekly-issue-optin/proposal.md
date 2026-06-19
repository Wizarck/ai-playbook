# telemetry-weekly-issue-optin

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

`rule-event-report-weekly.yml` lived only in the playbook's own repo and ran on a
weekly cron, posting a telemetry digest as a GitHub issue. On the playbook repo
(and any consumer without committed telemetry) the digest is always `count: 0`,
and — because the `telemetry-report` label did not exist — the create-fallback
spawned a fresh unlabelled issue every week (issues #108/#109/#112/#113). PR #131
fixed the empties (skip when count==0). This change makes the whole feature a
deliberate, UI-driven opt-in instead of an always-on workflow nobody chose.

## What

Make the weekly telemetry issue **opt-in + configurable from the config UI**,
with the `telemetry-report` label created at install.

- **New global flag `telemetry_weekly_issue`** (config UI → Global flags tab,
  default OFF). Lives under `bundle.global_flags` — no bundle-schema change
  (`global_flags` accepts arbitrary boolean keys; the top level is
  `additionalProperties:false`, so a dedicated section was not an option).
- **Workflow template** `templates/new-project/.github/workflows/rule-event-report-weekly.yml.tmpl`
  (the PR #131-fixed workflow). `apply_config` **seeds** it into the consumer's
  `.github/workflows/` when the flag is ON (seed-only — never clobbers a consumer
  edit; delete the file to re-seed an updated version). When OFF/absent it is a
  no-op (existing file left as-is; removal is a documented manual step).
- **Label at install** — `bootstrap` creates the `telemetry-report` label
  (`gh label create`, best-effort, gated on the flag, graceful skip + printed
  instruction when `gh` is unavailable), and prints what it did so the user knows
  the install touched GitHub.

## Why a dedicated section, not the managed-files registry

Managed files trigger on a top-level bundle key, but the bundle schema is
`additionalProperties:false` with a fixed key set. The toggle therefore rides in
`global_flags` and is handled by a dedicated `apply_telemetry_weekly_issue`
section (a "consequence" like `apply_mcp_render`), keeping the schema untouched.

## Constraint that shaped the design

A scheduled workflow runs from the committed repo and cannot read
`feature-flags.env` / `applied-config.json` (gitignored). So the toggle controls
whether the workflow **file** exists (install-presence model), not a runtime env
read.

## Tests

- `apply_config` seeds the workflow when `global_flags.telemetry_weekly_issue`
  is true; no-ops when false/absent (real + dry-run).
- seed-only: an existing workflow file is not clobbered.
- `bootstrap` label step: best-effort create when on; graceful skip when `gh`
  absent.

## Release

`VERSION` bump at release-cut (minor — additive opt-in feature). Pull model.
