---
schema: agents-md/v1
version: 0.1.0
inherits_from: []
updated: 2026-04-22
project: ai-playbook
owner: arturo6ramirez@gmail.com
capabilities_map: true
---

# ai-playbook — self-hosted dispatcher

This file is read by agents working **ON** this repo (not consumers). Consumers read their own project's `AGENTS.md`, which inherits from this playbook via `.ai-playbook/specs/*`.

## 0 Bootstrap directive

Any agent editing this repo MUST:
1. Read `specs/dispatcher-chain.md` — inheritance model and override semantics.
2. Read `specs/agents-md-v1.schema.json` — frontmatter contract before editing any `AGENTS.md`.
3. Read `specs/verdict-contract.md` — verdict + severity rubric before QA.
4. Only then act.

## 1 Project identity

`ai-playbook` is the universal norms + tooling repo consumed via git submodule by every Wizarck project. LLM-agnostic. Dogfoods its own pre-commit and schema.

## 2 Dispatcher index

| Topic | Pointer |
|---|---|
| Inheritance model | [specs/dispatcher-chain.md](specs/dispatcher-chain.md) |
| AGENTS.md schema | [specs/agents-md-v1.schema.json](specs/agents-md-v1.schema.json) |
| Taxonomy (agent/tool/skill/hook/…) | [specs/taxonomy.md](specs/taxonomy.md) |
| Verdict + severity contract | [specs/verdict-contract.md](specs/verdict-contract.md) |
| Degradation modes | [specs/degradation-modes.md](specs/degradation-modes.md) |
| Agentic failure catalog | [specs/agentic-failures.md](specs/agentic-failures.md) |
| Model routing matrix | [specs/model-routing.md](specs/model-routing.md) |
| Prompt caching rules | [specs/prompt-caching.md](specs/prompt-caching.md) |
| Parallel review discipline | [specs/parallel-review.md](specs/parallel-review.md) |
| Memory hierarchy | [specs/memory-hierarchy.md](specs/memory-hierarchy.md) |
| Agent contract (I/O) | [specs/agent-contract.md](specs/agent-contract.md) |
| Error message standard | [specs/error-message-standard.md](specs/error-message-standard.md) |
| Break-glass (`--force-with-reason`) | [specs/break-glass.md](specs/break-glass.md) |
| Env var namespace | [specs/env-vars.md](specs/env-vars.md) |
| MCP servers schema | [specs/mcp-servers-schema.md](specs/mcp-servers-schema.md) |
| Notification policy | [specs/notification-policy.md](specs/notification-policy.md) |
| Migration guide (v0→v1) | [specs/migration-guide.md](specs/migration-guide.md) |
| Retrospective cadence | [specs/retrospective-cadence.md](specs/retrospective-cadence.md) |

## 3 Active work

Tracked in the project plan outside this repo. Current version: `0.1.0` (scaffold). Most `specs/*.md` and `scripts/*.py` are stubs populated by downstream tracks — see each file's `TODO: populated in TXX` banner.

## 4 Hard rules (this repo only)

- **Never edit `specs/*.md` without first verifying `agents-md-v1.schema.json` doesn't enforce structure** — breaking schema = breaking every consumer.
- **Scripts are cross-platform Python 3.11+.** No bash-isms. Use `pathlib`, not `os.path.join` with hardcoded separators.
- **Every script has a matching `tests/test_*.py`.** PR merges block if coverage drops.
- **Conventional commits** on this repo (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **Semver.** Breaking changes (schema bump, dispatcher semantics) = major. RFC under `rfcs/` first.

## 5 Capability map

| Need | How |
|---|---|
| Validate an `AGENTS.md` frontmatter | `python scripts/schema_validate.py <path>` |
| Render MCP configs for a consumer | `python scripts/mcp/render.py --project <name>` |
| Scan for leaked secrets | `python scripts/secrets_scan.py` |
| Run pre-commit locally | `pre-commit run --all-files` |
| Emit a trace event | `python scripts/log_event.py` (see `scripts/tracing/`) |
| Rollback to pre-refactor state | `git checkout baseline` |

## 6 MCP sources

No MCP servers are specific to this repo (it's a spec/tooling repo, not a runtime). Consumers declare MCP servers in their own `mcp-servers.yaml`, validated against `specs/mcp-servers-schema.md`.

## 7 Overrides inherited from playbook

N/A — this IS the playbook.

## 8 Gotchas

Empty at v0.1.0. Populated as operational knowledge accrues.
