# bootstrap-directive.md

> **Status**: v1.0.0. Authored in T02a; formalised in T22-followup.

## Purpose

Every consumer `AGENTS.md` MUST open with a **bootstrap directive** — an imperative block that forces the agent to read inherited norms, recall prior decisions, and check for active work **before** generating any response. Without it, agents regress to "confident first answer" behaviour regardless of how good the rest of the dispatcher is.

## Canonical block (copy verbatim into AGENTS.md §0)

```
## 0. Bootstrap directive

Before responding to ANY task:

1. Read `.ai-playbook/specs/dispatcher-chain.md` — universal norms inherited
   from the pinned playbook tag.
2. Call MCP `hindsight.recall(query="<project> <topic keywords>")` — surface
   prior decisions, gotchas, and archived artefacts before proposing new ones.
3. Check `openspec/changes/*/` for active OpenSpec changes that touch the same
   capability or area. Do not start parallel work on one already in flight.
4. Only then respond.

Skipping any step is a policy violation. If any step is blocked (MCP offline,
submodule missing), announce the DEGRADED state per `degradation-modes.md`
before proceeding.
```

## Rationale

| Step | What it enforces | Mapped principle |
|---|---|---|
| 1 | Inheritance — agent reads the submodule, not its model memory of "how we work". | Universal principle #5 (framework files lean, no duplication). |
| 2 | Recall first — bound the "do not assume" rule with concrete prior decisions. | Universal principle #1 (do not assume) + #7 (traceability). |
| 3 | Avoid duplicate OpenSpec changes on the same capability. | Universal principle #6 (approval-gated progression). |
| 4 | Gate — refuse to respond until 1–3 are honoured. | Makes the directive enforceable, not advisory. |

## Enforcement

- `scripts/schema_validate.py` verifies §0 exists in `AGENTS.md` and matches the canonical semantics. It accepts paraphrases but requires the four numbered actions.
- Session-start hooks (Claude Code `SessionStart`, Gemini `BeforeAgent`) can pre-seed step 2 by auto-running `scripts/inject_context.py` — see [session-start-hook.md](../docs/session-start-hook.md). That is a *convenience*; the directive remains the policy.

## Degraded execution

If Hindsight is offline (step 2 fails), the agent:

1. Announces `⚠️ Hindsight offline — proceeding without recall` exactly once at the start of the response.
2. Adds the session to the `.ai-playbook/overrides.log` with gate `bootstrap.recall` and reason auto-filled (`hindsight-unreachable-<timestamp>`).
3. Proceeds with steps 1, 3, 4 honoured normally.

See [degradation-modes.md](degradation-modes.md) for the full contract.

## Per-project tailoring

The directive block is canonical; the `<project>` placeholder in step 2's query MUST be replaced with the project's slug (e.g. `consumer-c-legacy`, `consumer-d`). The Hindsight `bank_id` is resolved from `<project>/mcp-servers.yaml`, not hard-coded here.

Projects MAY append project-specific pre-conditions (e.g. "also read `docs/prd.md`") **after** step 3, never before; the universal steps always run first.

## See also

- [dispatcher-chain.md](dispatcher-chain.md) — where the directive sits in the 3-level chain.
- [agents-md-v1.schema.json](agents-md-v1.schema.json) — frontmatter that pins the playbook tag referenced by step 1.
- [degradation-modes.md](degradation-modes.md) — what happens when step 2 fails.
- [mcp-servers-schema.md](mcp-servers-schema.md) — where Hindsight credentials live.
