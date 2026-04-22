# agent-contract.md

> **Status**: stub, v0.1.0. Populated in **T06**.

## Intent

Every Task-spawned subagent carries an explicit identity and scope so traces, memory, and RBAC can correlate. This spec defines the I/O JSON shape.

## Input shape (v0)

```json
{
  "agent_id": "<UUIDv7>",
  "agent_type": "reviewer|builder|doctor|advisor|...",
  "parent_agent_id": "<UUIDv7 or null>",
  "trace_id": "<OTel trace id>",
  "scope": {
    "project": "consumer-c-legacy",
    "change_id": "module-1-ingredients-implementation",
    "read_paths": ["apps/api/src/**"],
    "write_paths": []
  },
  "memory": {
    "bank_id": "consumer-c-legacy",
    "recall_depth": 5
  },
  "brief": "<free-form task description>",
  "budget": {
    "max_tokens": 50000,
    "max_wall_seconds": 300,
    "max_tool_calls": 40
  }
}
```

## Return shape

Always a JSON document containing a `verdict` per [verdict-contract.md](verdict-contract.md), the findings list, and telemetry attributes the parent should carry forward.

## Populated in T06

Formal JSON Schema in `specs/agent-contract.schema.json`, worked examples per `agent_type`, and the linkage to k8s RBAC (`scope` maps to ServiceAccount at deploy time per T18).
