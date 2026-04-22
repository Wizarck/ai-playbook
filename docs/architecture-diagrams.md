# architecture-diagrams.md

> **Status**: stub, v0.1.0. Populated in **T02h**.

## Planned diagrams (Mermaid)

1. **Prompt → response flow** — dev types a prompt → CLI reads project `AGENTS.md` → inherits `.ai-playbook/specs/*` → Hindsight recall → LLM call (routed per model-routing matrix) → response.
2. **`/opsx:propose` flow** — propose → specs || design → tasks → apply → archive, with gates and QA handoffs.
3. **Pre-commit flow** — git commit → trailing-whitespace → gitleaks → schema_validate → mcp_validate → block_manual_spec_edit → success/fail.

Diagrams land in T02h; skeleton here so cross-references already resolve.
