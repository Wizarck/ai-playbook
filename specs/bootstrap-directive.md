# bootstrap-directive.md

> **Status**: stub, v0.1.0. Populated in **T02a** (openTrattOS AGENTS.md section 0). This spec carries the canonical copy-paste block.

## Canonical block (v0 — subject to refinement in T02)

Any consumer project's `AGENTS.md` section 0 MUST render equivalent semantics:

```
Before responding to ANY task:
1. Read .ai-playbook/specs/dispatcher-chain.md — universal norms.
2. Call MCP hindsight.recall(query="<project> <topic>").
3. Check openspec/changes/*/ for active work on the topic.
4. Only then respond.
```

## Rationale

- **Step 1** enforces inheritance — the agent reads the submodule, not its memory of "how we work".
- **Step 2** surfaces prior decisions (Hindsight MCP) before generating new ones. Bounds the "do not assume" principle with recall.
- **Step 3** avoids parallel work on an existing OpenSpec change.
- **Step 4** blocks skipping any of the above.

## v0.1.0 notes

- Hindsight MCP scope (`bank_id`, URL) is per-project; defined in `mcp-servers.yaml` (T08).
- Credentials live in SOPS-encrypted `secrets.env`; decryption flow landed in T12.
