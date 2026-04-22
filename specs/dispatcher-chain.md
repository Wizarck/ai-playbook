# dispatcher-chain.md

> **Status**: stub, v0.1.0. Populated in **T02h** (data-flow diagrams) and cross-referenced from **T03** (schema). Consumers should treat the v0.1.0 version as directional intent, not contract.

## Purpose

Define the 3-level dispatcher inheritance model so any agent (Claude Code, Gemini CLI, Antigravity, Cursor) resolves the same rules regardless of which CLI invoked it.

## Levels

1. **Universal** — `ai-playbook/` (this repo). Consumed via git submodule at `.ai-playbook/` inside each consumer project.
2. **Project** — `<repo>/AGENTS.md` at the root of every consumer repo. Inherits from playbook via `inherits_from` frontmatter. Adds project identity, active work, hard rules, and capability map. Must NOT duplicate universal content.
3. **Personal add-on** (Arturo only) — `consumer-d/consumer-d.md`. Loaded by `~/.claude/CLAUDE.md` when cwd is a personal project. Never shipped to team devs.

CLI-specific routers (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/00-dispatcher.mdc`) are thin 5–10 line pointers that tell the CLI to read `AGENTS.md`.

## Override semantics

TODO: populated in T02h. Will specify precedence (project > playbook, local overrides documented in `AGENTS.md` section "Overrides inherited from playbook"), conflict detection, and how break-glass (`--force-with-reason`) interacts with inherited rules.

## See also

- [agents-md-v1.schema.json](agents-md-v1.schema.json)
- [taxonomy.md](taxonomy.md)
- [migration-guide.md](migration-guide.md)
