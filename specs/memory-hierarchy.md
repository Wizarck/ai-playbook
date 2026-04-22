# memory-hierarchy.md

> **Status**: stub, v0.1.0. Populated in **T06**.

## Hierarchy (v0 shape)

| Tier | Store | Typical entry | Read pattern | Write pattern |
|---|---|---|---|---|
| Session | In-process context | Current file contents, partial outputs | Automatic | Automatic |
| Project | `openspec/` + repo docs | Active change artifacts, ADRs | On-task | Via OpenSpec CLI only |
| Durable / personal | Hindsight MCP `bank_id=<project>` | Prior decisions, gotchas, retros | `hindsight.recall` at bootstrap + on-demand | `hindsight.retain` after meaningful learning |
| Durable / universal | `ai-playbook/specs/` | Norms, schemas, contracts | Via submodule inheritance | RFC + PR |

## Read/write rules

- **Read before decide.** Bootstrap directive (`specs/bootstrap-directive.md`) enforces `hindsight.recall` as step 2.
- **Write on lesson, not on fact.** Retain calls capture *learnings* (why, not what). Facts live in the code.
- **Decay beats stale.** Memories that conflict with current observed state are either deleted or annotated with a date-range.

## Populated in T06

`bank_id` conventions per project, retention windows, retrieval thresholds, and the agent-contract JSON that formalizes how a subagent declares its memory scope at spawn time.
