# bootstrap-direct-invoke-and-markerless-guard

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

Dogfooding the v0.19.15/16 upgrade flow surfaced that `bootstrap.py` lacked the
sibling-import sys.path shim, so the documented
`python .ai-playbook/scripts/bootstrap.py --update` (printed by the
upgrade-playbook-pin runbook AND by `update-playbook --execute`) failed with
`ModuleNotFoundError: No module named 'scripts'`.

## What

- Add the canonical `sys.path.insert(0, <repo root>)` shim to `bootstrap.py`
  (matches retain_memory.py et al.) so direct-path invocation works. The
  documented commands now run as printed; `--update` defaults its target to cwd.
- Regression test: `bootstrap.py --help` via direct path from a foreign cwd
  exits 0.

## Deferred

`render_agents_md` rendering OVER a hand-authored / markerless consumer
AGENTS.md (blanking its `inherits_from` pin + duplicating static sections) is a
real but deeper issue: a naive "return verbatim if markerless" guard breaks the
intended marker-seeding path (10 test_managed_files cases). The correct fix —
preserve consumer frontmatter + de-dup on seed — warrants its own focused change.

## Release

`VERSION` → 0.19.17. Patch (bugfix). Pull model.
