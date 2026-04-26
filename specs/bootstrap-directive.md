# bootstrap-directive.md

> **Status**: v1.1.0. Aligned with the SessionStart hook reality (2026-04-25).

## Purpose

Every consumer `AGENTS.md` MUST open with a **bootstrap directive** — an imperative block that forces the agent to surface inherited norms, prior decisions, and active work **before** generating any response. Without it, agents regress to "confident first answer" behaviour regardless of how good the rest of the dispatcher is.

## Two execution surfaces (both required)

The directive's effects land via two complementary mechanisms — they are NOT alternatives:

1. **SessionStart hook** (auto, eager) — the consumer's `.claude/settings.json` runs `python .ai-playbook/scripts/inject_context.py --bank-id <project-bank>` at the very start of every Claude Code session. The script POSTs `hindsight.recall` over HTTPS, sanitises the response, and writes `<consumer>/.claude/injected-context.md`. The Claude Code bootstrap reads that file alongside `AGENTS.md`.
2. **Agent reasoning** (active, on-demand) — once running, the agent honours steps 1–4 of the canonical block below. It reads `dispatcher-chain.md`, considers the injected-context file as the result of step 2, scans `openspec/changes/*/`, and only then responds.

Mechanism 1 is enforcement (the harness fires it); mechanism 2 is contract (the agent commits to it). Both must be present — the hook delivers data, the directive in `AGENTS.md` §0 commits the agent to actually consider it.

## Canonical block (copy verbatim into AGENTS.md §0)

```
## 0. Bootstrap directive

Before responding to ANY task:

1. Read `.ai-playbook/specs/dispatcher-chain.md` — universal norms inherited
   from the pinned playbook tag.
2. Consult `.claude/injected-context.md` — populated by the SessionStart hook
   from `hindsight.recall(query="<project> <topic keywords>")`. If the file is
   absent or the recall failed (DEGRADED_CONTEXT banner), proceed without
   prior recall but announce the degradation per `degradation-modes.md`.
3. Check `openspec/changes/*/` for active OpenSpec changes that touch the same
   capability or area. Do not start parallel work on one already in flight.
4. Only then respond.

Skipping any step is a policy violation. If steps 1 or 3 are blocked
(submodule missing, openspec dir absent), announce the gap before proceeding.
```

## Why this shape

| Step | What it enforces | Mapped principle |
|---|---|---|
| 1 | Inheritance — agent reads the submodule, not its model memory of "how we work". | Universal principle #5 (framework files lean, no duplication). |
| 2 | Recall first — bound the "do not assume" rule with concrete prior decisions, delivered via the auto-fired SessionStart hook. | Universal principle #1 (do not assume) + #7 (traceability). |
| 3 | Avoid duplicate OpenSpec changes on the same capability. | Universal principle #6 (approval-gated progression). |
| 4 | Gate — refuse to respond until 1–3 are honoured. | Makes the directive enforceable, not advisory. |

## Pre-2026-04-25 wording (deprecated)

Earlier versions said step 2 was "Call MCP `hindsight.recall(query=...)`" as if the agent invoked an MCP tool mid-session. That phrasing is **deprecated**: today's deployment delivers `recall` results to the agent via `injected-context.md` written by the SessionStart hook BEFORE the session starts. Mid-session ad-hoc recall is possible (running `inject_context.py` from a shell) but is not the canonical path the directive enforces.

If a future deployment wires Hindsight as a true Claude Code MCP tool (requires launching Claude Code with `sops exec-env` or equivalent so the CF Access env is in the process), the directive can be tightened back to "call the tool". Until then, the file-based delivery is canonical.

## Enforcement

- `scripts/schema_validate.py` verifies §0 exists in `AGENTS.md` and matches the canonical semantics. It accepts paraphrases but requires the four numbered actions and a clear pointer to the SessionStart-hook-populated file at step 2.
- The SessionStart hook itself is wired in `<consumer>/.claude/settings.json` per [`docs/session-start-hook.md`](../docs/session-start-hook.md) — `bootstrap.py` ships this scaffold by default for new consumers.

## Degraded execution

If the SessionStart hook fails (Hindsight offline, SOPS key missing, sops binary not on PATH), `inject_context.py` writes a `DEGRADED_CONTEXT` banner instead of fresh recall results — see [degradation-modes.md](degradation-modes.md). The agent then:

1. Announces `⚠️ Hindsight offline — proceeding without recall` exactly once at the start of the response.
2. Adds the session to `<consumer>/.ai-playbook/overrides.log` with gate `bootstrap.recall` and reason auto-filled (`hindsight-unreachable-<timestamp>`).
3. Proceeds with steps 1, 3, 4 honoured normally.

## Per-project tailoring

The directive block is canonical; the `<project>` placeholder in step 2's query MUST be replaced with the project's slug (e.g. `consumer-c-legacy`, `consumer-d`). The Hindsight `bank_id` is resolved from `<project>/mcp-servers.project.yaml` and passed to `inject_context.py` via the `--bank-id` flag inside the hook command.

Projects MAY append project-specific pre-conditions (e.g. "also read `docs/prd.md`") **after** step 3, never before; the universal steps always run first.

## See also

- [dispatcher-chain.md](dispatcher-chain.md) — where the directive sits in the 3-level chain.
- [agents-md-v1.schema.json](agents-md-v1.schema.json) — frontmatter that pins the playbook tag referenced by step 1.
- [memory-hierarchy.md](memory-hierarchy.md) — what `injected-context.md` contains and how recall is scoped.
- [degradation-modes.md](degradation-modes.md) — what happens when step 2's data source fails.
- [mcp-servers-schema.md](mcp-servers-schema.md) — where Hindsight credentials live.
- [../docs/session-start-hook.md](../docs/session-start-hook.md) — the wiring in `.claude/settings.json`.
