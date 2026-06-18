# runbook-migration-cmd

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

CodeRabbit on PR #123 flagged the v0.19.18 migration snippet in
upgrade-playbook-pin.md: the `git rm --cached` command fails (non-zero) if a
consumer never tracked `.mcp.json`/`.gemini/settings.json`, and the fence lacked
a language tag (MD040).

## What

- Add `--ignore-unmatch` to the `git rm --cached` migration command (idempotent).
- Tag the fenced block `bash`.

## Release

`VERSION` → 0.19.19. Patch (docs). Pull model.
