# why-these-choices.md

> Rationale for key design decisions. Populated as tracks land; v0.1.0 documents the choices already made during planning.

## Why git submodule for distribution

- Every consumer pins a specific semver tag — upgrades are explicit.
- Consumers can diverge on branches and still inherit a known-good base.
- Alternative considered: npm / PyPI package. Rejected because the playbook is dogma-driven (docs + scripts + specs), not a runtime artifact — package registries don't model "pin a tag, read the docs" well.

## Why LLM-agnostic

- Arturo uses Claude Code, Gemini CLI, Google Antigravity, and Cursor in parallel.
- A CLI-specific playbook (`CLAUDE.md`-only) forces duplication when a new CLI lands.
- Solution: one `AGENTS.md` per project + CLI-specific thin routers (~10 lines each) pointing at `AGENTS.md`.

## Why MCP for tool distribution

- MCP is the emerging standard for LLM tool use across providers.
- Consumers declare servers once in `mcp-servers.yaml` and render per-CLI configs.
- CLI hooks (Claude Code `PostToolUse`, Gemini equivalent) stay thin — they trigger, they don't enforce logic.

## Why OTel Collector paralelo a Langfuse

- Langfuse gives LLM-native views (prompt / output / cost) — great for agent-side debugging.
- OTel Collector + Tempo joins LLM traces with infra signals (logs from k3s, metrics from services) — required so Arturo can ask "review this infra problem" and get a correlated view.
- Running both adds ~1 day at MVP but unblocks Phase 5 learning loop.

## Why 3-level dispatcher (not 2)

- Team devs (future) must not see Arturo's personal add-on (`consumer-d.md`).
- Projects must stay LLM-agnostic.
- Personal overrides live at a third layer loaded only when cwd is a personal project — isolation by load-time, not by git.

More decisions land in T22 (governance) and are also captured in `rfcs/` for any breaking change.
