# graphify-adoption-rule

> **Status**: SCRATCH (iteration notes). Canonical contract lives in the PR
> description (#114). This file exists to satisfy the `branch-name-validator`
> workflow (every `feat/<change-id>` branch must have
> `openspec/changes/<change-id>/`).

## Why

[graphify](https://github.com/safishamsi/graphify) (PyPI `graphifyy`) builds a
committed AST knowledge graph under `graphify-out/` that agents query for
structural orientation (callers, dependency chains, blast radius) at a fraction
of the tokens of raw grep/read. The graph is *meant to be committed* so the
whole team shares one map.

The trigger: a consuming repo (geeplo) committed the graph the wrong way —
one developer's absolute machine paths (`.graphify_python`,
`.graphify_uncached.txt`), per-run `cost.json`, 1814 `cache/` files, and a
duplicate ~28 MB dated snapshot — making the "shared" graph effectively
un-shareable. graphify already solves multi-machine portability upstream
(relative paths since `graphifyy>=0.8.31` + a `graph.json` union-merge driver
installed by `graphify hook install`); the gap was *adoption discipline*. The
playbook is the right home: encode that discipline once as an opt-in,
enforceable feature so every consumer adopts graphify correctly instead of
re-discovering the footgun.

## What

A first-class, **opt-in** playbook feature mirroring caveman's shape:

- **Rule** `graphify-adoption` (`activation: manual`; not-applicable when the
  repo does not commit `graphify-out/graph.json`) + paired hardrule
  (`validate`/`apply`, exit 0/1/2): gitignore the per-machine/per-run graph
  state, require the `graph.json` union-merge driver in `.gitattributes`, pin
  `graphifyy>=0.8.31` (advisory). `apply` converges `.gitignore`; the
  `.gitattributes` half is delegated to `graphify hook install` (graphify owns
  the driver name).
- **Skill** `skills/graphify/SKILL.md` — agent-facing query-first navigation.
- **Concept** `docs/concepts/graphify.md` (graphify vs RAG, multi-dev model) +
  **runbook** `docs/runbooks/graphify-setup.md`.
- **Features surface** — toggleable in the config UI like caveman: a
  `scripts/graphify` package (`toggle`/`materialise`/`cli`,
  `python -m scripts.graphify status|on|off`), `schema-graphify-toggle-v1.json`,
  `features.graphify` in the config-bundle schema, `features-inventory.json` +
  `defaults.json` entries, and an `apply_graphify` delegation section in
  `scripts/apply_config.py` (preflight + non-transactional rollback-reconcile
  parity with caveman).

## Key difference from caveman

caveman's CLI is in-repo (`python -m scripts.caveman`), so its toggle
self-applies fully. graphify wraps an **external** PyPI tool: the toggle manages
the in-repo side effects only (AGENTS.md guidance block + `.gitignore` hygiene)
and surfaces — but cannot run — the per-machine `uv tool install
graphifyy>=0.8.31` + per-clone `graphify hook install`.

## Decisions (locked)

| ID | Decision |
|---|---|
| D1 | Opt-in (`activation: manual`); NOT mandatory `applies_to: all` — graphify is heavy (28 MB graphs) + a third-party dep; not every repo needs it. |
| D2 | The rule rides the Skill + Rule surfaces AND the Features surface (full caveman-mirror) for consistency. |
| D3 | `apply` converges `.gitignore` only; `.gitattributes` merge driver is delegated to `graphify hook install` (never fabricate the driver name). |
| D4 | `graphifyy>=0.8.31` is an advisory, not a hard fail — read-only/CI envs legitimately lack the CLI. |
| D5 | State per-project at `<project>/.ai-playbook/graphify.json`, schema `graphify-toggle/v1`; no `mode` (graphify has no intensity levels). |

## Out of scope

- Installing `graphifyy` / running `graphify hook install` from the toggle —
  inherently per-machine/per-clone; surfaced as Next Steps.
- A graph-freshness pre-commit gate (left to the consumer; pointer in the rule's
  See-also).
- Upper-bounding the `graphifyy` version (floor only).

## Verification footprint

- 19 graphify tests (rule `validate`/`apply`/not-applicable + CLI on/off/
  materialise/idempotency) + 230 regression tests (caveman / apply_config /
  config-bundle) pass locally and in CI.
- `ruff` clean; `build_ui_sidecars --check` no-drift; `defaults.json` validates
  vs the config-bundle schema.
- `validate_pairing` / `check-link-integrity` / `check-doc-language` OK.
- Rules inventory regenerated (`rules_toggle inventory`) so `check-rule-schemas`
  sees the new rule.

## Risks

| Risk | Mitigation |
|---|---|
| Devs run `graphify` without `hook install` → `graph.json` merge conflicts | Rule `validate` flags the missing `.gitattributes` driver with a `graphify hook install` FIX. |
| External `graphifyy` absent on a machine | Version check is advisory; the committed graph stays readable; the toggle surfaces the install step. |
| Mixed `graphifyy` versions across devs drift the graph format | Version floor `>=0.8.31` (relative paths); runbook recommends the team bumps together. |
| Toggle `on` mutates AGENTS.md/.gitignore then a later managed-files batch rolls back | `apply_graphify` preflight + a rollback-reconcile message (parity with caveman); both files backed up first. |
