# consumer-upgrade-ux

> **Status**: SCRATCH (iteration notes). Canonical contract lives in the PR
> description (#119). This file exists to satisfy the `branch-name-validator`
> workflow (every `feat/<change-id>` branch must have
> `openspec/changes/<change-id>/`). `openspec/changes/` is gitignored — this is
> force-added, mirroring the graphify-adoption-rule precedent.

## Why

Bumping a consumer's `.ai-playbook` pin to a new tag and re-activating it
required multi-step **discovery**: which scripts reconcile the working tree,
where the hard Python deps come from, and how to install graphify's external
`graphifyy` CLI. None of it was documented end-to-end, so every consumer
re-derived it. The reconcile half already exists (`bootstrap.py --update`); the
gaps were an executable bump, dep self-heal, graphify install automation, and a
runbook tying them together — plus a `.gitignore` regression that dirtied the
submodule root when ponytail/graphify were enabled.

## What

Additive consumer-UX improvements, reusing existing machinery (no duplicate
upgrade script):

- `graphify setup` subcommand — automates `uv tool install "graphifyy>=0.8.31"`
  + `graphify hook install` (mirrors caveman's external-tool probe).
- `doctor --install-deps` — editable-install self-heal for missing
  jsonschema/pyyaml (with `ensurepip` fallback).
- `update-playbook.rule.py apply --execute` — performs the bump (fetch +
  checkout latest + re-pin `inherits_from` + stage); plan-only stays default.
- New runbook `docs/runbooks/upgrade-playbook-pin.md` — bump → `bootstrap.py
  --update` → `doctor`.
- Fix: `.gitignore` anchors `/graphify.json` + `/ponytail.json` beside
  `/caveman.json`.

## Release

`VERSION` → 0.19.15 + CHANGELOG entry. Additive patch; pull model — consumers
bump at their own pace.
