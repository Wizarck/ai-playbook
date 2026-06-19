# door-gate-mcp-render-and-guard-dispatcher

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

Two reconcile-door footguns surfaced while activating a feature on an existing
consumer:

1. Toggling a non-MCP feature through the door re-rendered the **entire MCP
   surface** (`.mcp.json` + `.gemini/settings.json` + the global
   `~/.gemini/antigravity/mcp_config.json`) because `apply_mcp_render` ran
   unconditionally — even for a bundle that says nothing about MCP.
2. The door's settings renderer wired the generic L1 dispatcher PreToolUse hook
   (`python .ai-playbook/scripts/hook_dispatcher.py PreToolUse`) **blind**. On a
   consumer whose submodule pin predates `hook_dispatcher.py`, the hook hits a
   missing file → `exit 2` → Claude Code blocks **every** Edit/Write/Bash, so the
   broken hook gates its own repair. The bare relative path also resolves against
   the hook's cwd, which can be a sibling repo if the shell has `cd`'d away.

## What

1. **Gate `apply_mcp_render` on MCP intent** (`mcps_enforce` /
   `mcp_project_servers`), in both the real and dry-run paths. No MCP section →
   the render slot is a reported **skipped** no-op. `apply_mcps_enforce` stays
   unconditional (cheap state-file no-op).
2. **Harden the dispatcher hook:** anchor the command to `$CLAUDE_PROJECT_DIR`
   (cwd-independent) and suppress injection when the consumer lacks
   `hook_dispatcher.py`. The impure `_managed_files` does the on-disk check and
   passes `DISPATCHER_AVAILABLE` via `substitutions`; the pure settings renderer
   stays filesystem-free. Template updated to the anchored command.

## Tests

- `test_mcp_render_skipped_without_mcp_intent` / `test_mcp_render_runs_with_mcps_enforce`
- `test_settings_json_skips_dispatcher_when_unavailable`
- `test_settings_json_dispatcher_anchored_to_project_dir`

## Release

`VERSION` bump at release-cut (patch — bug fix, additive). Pull model.

## Provenance

Re-do of the stale PR #110 (27 commits behind main, tests red) on current main.
