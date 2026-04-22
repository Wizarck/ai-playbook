# taxonomy.md

> **Status**: stub, v0.1.0. Populated in **T03c**. v0.1.0 carries the table shape and glossary entries at resolution needed for current tracks.

## Canonical terms

| Term | Definition | Example | Scope |
|---|---|---|---|
| Agent | Entity with tools + memory + goal. | Claude Sonnet running in a session. | runtime |
| Subagent | Task-spawned agent with fresh context. | Reviewer spawned via the `Task` tool. | runtime |
| Tool | Callable with a typed I/O contract. | `hindsight.recall`, `Read`, `Bash`. | runtime |
| Skill | Reusable procedure spec, LLM-executed. | `bmad-code-review`, `openspec-propose`. | config |
| Command | Slash-invocable skill. | `/opsx:propose`. | config |
| Hook | Trigger script bound to a CLI event. | `PostToolUse` formatting hook. | infra |
| Script | Portable Python tool in this repo. | `scripts/openspec_validate.py`. | infra |
| Dispatcher | File an agent reads for instructions. | `AGENTS.md`, `specs/*.md`. | config |
| MCP server | Tool-providing service. | Hindsight local MCP, guardrails-mcp. | infra |
| Router | Thin pointer file. | `~/.claude/CLAUDE.md`, `project/GEMINI.md`. | config |

## Cross-cut distinctions

- **Tool vs Skill**: a tool is machine-callable with a typed schema; a skill is a natural-language procedure the LLM executes.
- **Subagent vs Agent**: both are agents; "subagent" emphasizes that it was spawned with a fresh context and a bounded brief.
- **Hook vs Script**: a hook is CLI-event-bound (non-portable semantics); a script is Python, portable, and reused by hooks or humans.

## Populated in T03c

Additional entries (bounded contexts, SSOT, break-glass, verdict, severity) land when T03 writes the full spec. v0.1.0 intentionally under-specifies to avoid churn before universal norms are finalized.
