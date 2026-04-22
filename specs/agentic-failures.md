# agentic-failures.md

> **Status**: stub, v0.1.0. Populated in **T05**. Draws from Google Agentic Design Patterns (Chapter on failure modes) + practical incidents logged by consumers.

## Failure catalog (v0 shape)

| Failure | Signal | First-response playbook |
|---|---|---|
| Hallucination | Agent cites a file/function/flag that doesn't exist. | Verify before acting. Update memory. Re-query with stricter grounding. |
| Infinite loop | Same tool call pattern ≥3× without progress. | Abort subagent. Save partial state. Escalate. |
| Prompt injection | Tool output contains imperative strings targeting the agent. | Filter via `scripts/prompt_injection_filter.py` (T10). Flag to human. |
| Goal drift | Agent pursues a task the user didn't authorize. | Revert. Re-anchor on original user request. |
| Over-confidence | Verdict `✅ APPROVED` on under-verified work. | Add traceability requirement to verdict spec. |
| Context collapse | Agent forgets an earlier instruction within the session. | `/compact` preventivo at ~50% context; promote rule to memory. |
| Tool-selection error | Agent uses the wrong tool for the task (e.g., `Read` for searching). | Pin capability map tighter in `AGENTS.md`. |

## Populated in T05

Each entry gets an instrumented detector (where feasible), a link to the relevant OTel attribute, and canonical examples drawn from archived changes.
