# taxonomy.md

> **Status**: v1.0.0.

Canonical glossary for terms used across `ai-playbook/specs/*`, consumer AGENTS.md files,
and all tooling. When a spec uses any of these words it means the definition below — no
synonyms, no drift. Cross-reference this file before inventing a new term.

---

## 1 Runtime entities

Things that exist at execution time, inside or alongside an agent session.

| Term | Definition | Example | Scope |
|---|---|---|---|
| Agent | An LLM-driven entity with a system prompt, a tool set, a session context, and a goal. | Claude Sonnet instance running via Claude Code CLI in `C:\Projects\consumer-c`. | runtime |
| Subagent | Agent spawned by another agent with a fresh context window and a bounded brief; returns a single structured result to the parent. | Reviewer invoked via the `Task` tool in `bmad-code-review` to run the Blind Hunter pass. | runtime |
| Tool | Machine-callable function with a typed JSON Schema I/O contract the agent invokes deterministically. | `Read`, `Bash`, `hindsight.recall`, `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql`. | runtime |
| MCP server | Tool-providing network service following the Model Context Protocol; exposes one or more tools over stdio or HTTP. | `hindsight` (project memory), `litellm` on `localhost:4000`, `guardrails-mcp` (planned T10). | infra |
| Session | Single continuous turn sequence between a user and an agent, sharing one context window and one transcript. | A Claude Code run from `claude` invocation to exit; preserved by `--resume`. | runtime |
| Context | The ordered list of messages, tool results, and system content the LLM sees on a given turn. | 180k tokens of prompt + history in an Opus 4.7 1M-context session. | runtime |
| Token budget | Upper bound on context-window usage before `/compact` or session split is required. | "Compact at ~50% of context" — principle #4 in `C:\Users\Arturo\.claude\CLAUDE.md`. | process |
| Trace (OTel) | Structured span emitted to an observability backend recording a single logical operation (tool call, skill run, LLM request). | Langfuse span emitted by `lib/telemetry/trace_anthropic(...)` in `consumer-d`. | infra |

## 2 Config artefacts

Files and declarative records that shape agent behavior. They exist on disk; they are
read, not executed, by the LLM.

| Term | Definition | Example | Scope |
|---|---|---|---|
| Skill | Reusable natural-language procedure spec the LLM executes step-by-step; invoked by name via the Skill tool. | `bmad-code-review`, `openspec-propose` (discoverable from the system-reminder skills block). | config |
| Command | Slash-invocable skill or action, registered under `.claude/commands/` or a plugin namespace. | `/opsx:propose`, `/init`, `/review`. | config |
| Hook | Trigger script bound by the CLI to a lifecycle event (`PreToolUse`, `PostToolUse`, `Stop`); executes deterministically without LLM involvement. | Pre-commit formatting hook declared in `settings.json` running `ruff format` after `Edit`. | infra |
| Script | Cross-platform Python tool under `ai-playbook/scripts/*.py`, runnable by humans, hooks, or CI. | `C:\Projects\ai-playbook\scripts\schema_validate.py`, `discover_projects.py`. | infra |
| Dispatcher | A markdown file an agent reads to learn how to operate in a given context; lean, pointer-heavy. | `AGENTS.md`, `C:\Projects\consumer-d\consumer-d.md`, `D:\OneDrive\BRAIN.md`. | config |
| Router | Thin (5–10 line) CLI-specific file that redirects the agent to the real dispatcher. | `C:\Users\Arturo\.claude\CLAUDE.md`, `GEMINI.md`, `.cursor/rules/00-dispatcher.mdc`. | config |
| Registry | Machine-readable index mapping logical names to resolved on-disk locations. | `~/.ai-playbook/projects.yaml` (per-dev, gitignored). | config |
| Spec | Normative document under `specs/` defining a contract, schema, or rule that consumers rely on. | `C:\Projects\ai-playbook\specs\verdict-contract.md`. | config |
| Template | Skeleton file copied on bootstrap to seed a new artefact of a known type. | `openspec/changes/<change-name>/proposal.md` template. | config |
| RFC | Request-for-Comment document under `rfcs/` proposing a breaking change or major new spec, merged before the spec lands. | `rfcs/0001-schema-v2.md` (hypothetical). | process |

## 3 Process concepts

Ritual and review mechanics used by humans and agents alike during the worker→QA loop.

| Term | Definition | Example | Scope |
|---|---|---|---|
| Verdict | The structured output of a QA pass on a worker artefact: one of `✅ APPROVED`, `⚠️ ISSUES FOUND`, `❓ CLARIFICATION NEEDED`. | QA subagent returns `⚠️ ISSUES FOUND (iter 2): S2 traceability gap`. | process |
| Severity | S0–S4 tag on each issue in a verdict. S1/S2 block approval; S3/S4 are advisory. | See `C:\Projects\ai-playbook\specs\verdict-contract.md`. S0 = must fix before merge; S4 = nit. | process |
| Rework cycle | One round of worker fix + QA re-review after a non-approving verdict. Cap is 2 cycles per artefact. | After the 2nd `⚠️ ISSUES FOUND` verdict on the same artefact, escalate to the user as a systemic issue. | process |
| Break-glass | Explicit override of an inherited rule or gate, invoked with `--force-with-reason "<justification>"` and logged. | `openspec apply --force-with-reason "prod outage; spec drift acknowledged"`. See `docs/rules/break-glass.rule.md`. | process |
| Self-validation gate | One of 5 silent checks a worker runs on its own output before invoking QA: Scope, Anti-duplication, Traceability, TDD compliance, Naming. | Worker detects the proposal references Jira PROJ-42 but fails Traceability gate when the cited issue doesn't exist; reworks before QA. | process |
| Parallel review | Multiple independent QA subagents examining the same artefact simultaneously with orthogonal briefs. | `bmad-code-review` invokes Blind Hunter + Edge Case Hunter + Acceptance Auditor in parallel. | process |
| Retro cadence | Scheduled retrospective ritual extracting lessons from completed epics or quarters. | Post-epic retro run via `bmad-retrospective` skill; frequency in `C:\Projects\ai-playbook\specs\retrospective-cadence.md`. | process |

## 4 Distinctions worth hammering

The places teams drift if these aren't kept crisp.

### Tool vs Skill
A **tool** is machine-callable with a JSON Schema contract — the agent *calls* it, gets a
deterministic typed result. A **skill** is a natural-language procedure the LLM *executes*
step by step. Tools are deterministic infra; skills are LLM behavior. `Read` is a tool.
`bmad-create-prd` is a skill.

### Hook vs Script
A **hook** is CLI-bound: registered in `settings.json`, triggered by a specific event
(`PostToolUse`, `Stop`), non-portable semantics (depends on the harness). A **script** is
portable Python under `ai-playbook/scripts/*.py` that can be reused by hooks, CI, or humans
at the command line. Hooks CALL scripts; the script is the reusable unit, the hook is the
binding.

### Subagent vs Agent
Both are agents. "Subagent" emphasizes it was *spawned* by a parent agent with a bounded
brief and a fresh context window, and that its job is to return a single structured result
(a verdict, a file, a summary) to the parent — not to hold a stateful conversation with the
user. An agent talking directly to the user in a session is not a subagent.

### Personal add-on vs Project dispatcher
A **project dispatcher** (`AGENTS.md`) is public-safe, shipped to every team dev cloning
the repo. A **personal add-on** (e.g. `consumer-d.md`) is loaded conditionally via the projects
registry (`personal: true` flag) and carries inline gotchas that are *not* universalizable
(VPS port numbers, local startup order, specific MCP auth choices). Team devs cloning a
personal repo never load the add-on — the registry on their machine lacks the flag.

### Dispatcher vs Router
A **dispatcher** is a substantive file the agent reads to learn norms, identity, and
pointers. It contains actual content (§0–§8 in AGENTS.md). A **router** is a 5–10 line
pointer file whose only job is telling a specific CLI ("when you are Claude Code / Gemini /
Cursor, go read AGENTS.md instead"). `~/.claude/CLAUDE.md` is a router. `AGENTS.md` is a
dispatcher. Never put norms in a router; never inline a router's pointer text into a
dispatcher.

---

## See also

- `C:\Projects\ai-playbook\specs\dispatcher-chain.md` — 3-level inheritance model using these terms.
- `C:\Projects\ai-playbook\specs\verdict-contract.md` — verdict + severity formal contract.
- `C:\Projects\ai-playbook\specs\agents-md-v1.schema.json` — schema whose fields reference project/owner/inherits_from.
- `C:\Projects\ai-playbook\specs\projects-registry.md` — registry as defined above.
