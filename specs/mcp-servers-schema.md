# mcp-servers-schema.md

> **Status**: stub, v0.1.0. Populated in **T08**. Formal schema ships as `mcp-servers.schema.json` alongside the merge pipeline.

## Three layers (canonical SSOT pattern)

1. **Base** — `ai-playbook/mcp-servers-base.yaml`. Well-known server templates (hindsight, guardrails, atlassian, google-workspace, miro, …). Consumed by every project.
2. **Project** — `<repo>/mcp-servers.yaml`. Project-scoped servers (e.g., consumer-c-legacy-specific guardrails profile).
3. **Personal** — `~/.config/mcp-servers.yaml` or `consumer-d/mcp-servers.yaml`. Arturo-specific accounts (google-workspace-arturo vs google-workspace-consumer-b).

## Merge semantics (v0)

- Keys are canonical short-form IDs (`hindsight`, `guardrails-mcp`, not `consumer-c-legacy-guardrails-mcp`).
- Later layers override earlier layers **field-by-field** (not wholesale replacement).
- `scope: personal` servers from Base or Project layers are rejected with error — personal is personal-layer-only.
- `env.required` is the union across layers; validator refuses to render if any required env is unset.

## Render pipeline

`python scripts/mcp/render.py --project <name>` emits per-CLI configs:

- `<repo>/.mcp.json` (Claude Code).
- `<repo>/.gemini/settings.json` (Gemini CLI / Antigravity).
- Printed summary of which layers contributed each server.

## Populated in T08

Full JSON Schema, drift detector (`scripts/mcp/validate.py`), well-known templates with conventional env var names, and the pre-commit hook that blocks merge if render output differs from committed configs.
