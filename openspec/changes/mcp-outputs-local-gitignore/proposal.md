# mcp-outputs-local-gitignore

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

Rendered MCP configs (`.mcp.json`, `.gemini/settings.json`) were committed in
consumer repos with the **personal** layer baked in (e.g. tenant google-workspace
+ atlassian servers). The playbook must stay agnostic to a user's local MCP
config; personal/tenant servers must never land in a committed work artifact.
The render already merges personal>project>base and omits personal when absent —
so the rendered output is correctly a per-machine artifact, not a committed file.

## What (Phase 1 of the agnostic-playbook plan)

- `.gitignore.tmpl` playbook-patterns block now ignores `.mcp.json` +
  `.gemini/settings.json` (LOCAL build artifacts). Committed SoT stays
  `mcp-servers.project.yaml` (no personal) + `~/.config/mcp-servers.yaml`
  (personal, local-only).
- AGENTS.md.tmpl §6 + upgrade-playbook-pin runbook document the local-render
  model + the one-time `git rm --cached` migration + fresh-clone render step.
- Genericise the one personal-flavoured example in mcp-servers-schema.md
  (`google-workspace-arturo` → `google-workspace-<you>`).
- Regression test: the shipped `.gitignore.tmpl` ignores both rendered outputs.

## Deferred to later phases

Lossless adoption (backup + absorb existing config into layers; fixes the
markerless AGENTS.md render) and the generic personal `pack/unpack` bundle.

## Release

`VERSION` → 0.19.18. Patch (additive). Pull model.
