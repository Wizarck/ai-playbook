# mcp-servers-schema.md

> **Status**: v1.0.0. Formal JSON Schema (`mcp-servers.schema.json`) tracks this
> doc verbatim.

Single-source-of-truth contract for the 3-layer MCP server configuration
stack that all Wizarck-org consumers render from. Defines file shape, merge
semantics, validator rules, render rules, and the well-known-server extension
recipe.

---

## 1. Three layers (canonical SSOT pattern)

| # | Layer | Location | Owner | Committed to repo? |
|---|---|---|---|---|
| 1 | **Base** | `ai-playbook/mcp-servers-base.yaml` | This repo. Templates for well-known servers. | Yes — public. |
| 2 | **Project** | `<consumer>/mcp-servers.yaml` | Each consumer. Project-specific servers or per-project tuning. | Yes — consumer repo. |
| 3 | **Personal** | `$AIPLAYBOOK_PERSONAL_MCP_FILE`, else `~/.config/mcp-servers.yaml`, else `<HOME>/Projects/consumer-d/mcp-servers.yaml` (legacy). | Individual developer. OAuth tokens, tenant-specific credentials. | **No** — gitignored. |

Every layer uses the same v1 schema (`schema: mcp-servers/v1`). The only
difference is the `layer:` field (`base` | `project` | `personal`) which the
validator cross-checks.

## 2. Merge semantics

- **Keys are canonical short-form IDs** (`hindsight`, `guardrails-mcp`,
  `skills-registry`). Never prefixed with a consumer name.
- **Precedence**: personal > project > base. Later layers override earlier
  layers **field-by-field** (deep merge), not wholesale replacement.
  - Example: `base` declares `skills-registry` with `endpoint: null`; `personal`
    sets `endpoint: https://consumer-d-skills.consumer-bfood.com`. The merged record
    keeps everything else from base (description, env, auth, scope) and uses
    the personal `endpoint`.
- **Union semantics for list-valued fields**:
  - `env.required`: union across layers (additive — a project may declare extra
    required env vars beyond what base specifies; the merged set is the union).
  - `env.optional`: union across layers, minus any names that appear in the
    merged `env.required` (so you cannot "demote" a required var to optional).
  - `capabilities_hint`: union across layers (dedup preserving first-occurrence
    order).
- **`scope: personal` servers are REJECTED at base or project layers.** The
  validator raises a canonical error and exits 1. Personal-scope entries only
  live in the personal layer.
- **Duplicate canonical IDs within a single layer are REJECTED.** Splitting a
  server into two entries is a schema violation.
- **Cross-layer duplicate IDs are the expected case** — that is how
  precedence-based override works.

## 3. Per-server field contract

```yaml
<canonical-id>:
  id: <canonical-id>                    # MUST equal the map key.
  description: <single sentence>        # Human-readable intent. LLM-friendly.
  transport: stdio | http | sse | streamable-http
  endpoint: <URL>                       # Required when transport == http/sse/streamable-http.
  command: <shell command>              # Required when transport == stdio.
  env:
    required: [<ENV_VAR_NAME>, ...]     # Render refuses if any unset at merge time.
    optional: [<ENV_VAR_NAME>, ...]
  auth: none | bearer | oauth | cf-access
  scope: personal | project | universal
  capabilities_hint: [<short-token>, ...]  # Router / health check semantics.
```

Field rules:

| Field | Required | Rule |
|---|---|---|
| `id` | yes | Must equal the map key; validator rejects mismatch. |
| `description` | yes | Non-empty, ≤200 chars, one sentence. |
| `transport` | yes | Enum above. `stdio` for local processes; `http`/`sse`/`streamable-http` for network services. |
| `endpoint` | conditional | Required iff `transport != stdio`. Must start with `http://` or `https://` (validator warns on `http://` for non-localhost). |
| `command` | conditional | Required iff `transport == stdio`. Shell-safe; the renderer quotes appropriately. |
| `env.required` | no | If unset, treated as `[]`. |
| `env.optional` | no | If unset, treated as `[]`. |
| `auth` | yes | Enum above. `cf-access` implies CF Tunnel + Access policy. |
| `scope` | yes | `personal` only allowed in personal layer. `project` scope declares the server is meaningful only inside the project layer. `universal` means the template is reusable. |
| `capabilities_hint` | no | Free-form short tokens. Used by the router/health checks and dashboards, not by MCP itself. |

## 4. `skills-registry` server — deep-dive

The `skills-registry` entry deserves special call-out because its auth and
scope interplay is more nuanced than the other well-known servers. See
[`skills-registry.md`](skills-registry.md) for the full contract.

Base-layer entry (from `mcp-servers-base.yaml`):

```yaml
skills-registry:
  id: skills-registry
  description: Central skills discovery + catalog service — agents query it before planning.
  transport: http
  endpoint: null                           # resolved per-environment in project/personal layer
  command: null
  env:
    required: [SKILLS_REGISTRY_URL]
    optional: [SKILLS_REGISTRY_API_KEY]
  auth: none                               # base template; upgraded per-layer (see below).
  scope: universal
  capabilities_hint: [skills-list, skills-describe, skills-search]
```

Layer-specific overrides:

- **Project layer (e.g. `consumer-c-legacy/mcp-servers.yaml`)**: MAY pin
  `endpoint` to the production URL and leave `auth: none` if only
  `scope=public` skills are consumed. `env.required` MAY add
  `SKILLS_REGISTRY_API_KEY` if the project needs `scope=<project-slug>` entries.
- **Personal layer (e.g. `consumer-d/mcp-servers.yaml`)**: upgrades `auth` to
  `bearer` and adds `SKILLS_REGISTRY_API_KEY` to `env.required` because the
  personal layer queries `scope=personal` entries.

The server authoritatively enforces scope — the client-side script
(`scripts/skills_registry.py`) only *declares* the intended scope in the
query string. The registry returns 401 if the declared scope requires auth
that the caller did not provide.

## 5. Validator rules (`scripts/mcp/validate.py`)

The validator runs on every project via pre-commit and in CI. It enforces:

1. **Schema declaration present.** Every YAML layer starts with
   `schema: mcp-servers/v1` and `version: <semver>`.
2. **Layer marker matches filename.** `layer: base` must live in
   `mcp-servers-base.yaml`; `layer: project` in `<repo>/mcp-servers.yaml`;
   `layer: personal` in the personal file path.
3. **No `scope: personal` outside the personal layer.** Canonical error
   `❌ scope:personal declared in layer:<layer>` with `OVERRIDE: none` (safety
   invariant — not overridable).
4. **No duplicate canonical IDs in a single layer.**
5. **Required fields present.** `id`, `description`, `transport`, `auth`,
   `scope` on every server.
6. **Transport-conditional fields.** `endpoint` iff http/sse; `command` iff
   stdio.
7. **Env vars resolved at render time.** After 3-layer merge, every
   `env.required` name must exist in the process environment. Missing vars
   emit canonical error; `--force-with-reason` is permitted for dev.
8. **No secret-like values inline in YAML.** The secrets scanner runs on the
   merged YAML (not just individual files); any match exits 3 (`OVERRIDE:
   none`).
9. **Drift check.** If `<repo>/.mcp.json` or `<repo>/.gemini/settings.json`
   exists, the validator recomputes the rendered form in-memory and refuses
   on any diff.

## 6. Render rules (`scripts/mcp/render.py`)

The renderer emits per-CLI configs from the merged YAML:

| Output | Consumer | Shape |
|---|---|---|
| `<repo>/.mcp.json` | Claude Code | Claude-style `{ "mcpServers": { "<id>": { ... } } }`. |
| `<repo>/.gemini/settings.json` | Gemini CLI / Antigravity | Gemini extension format (same server list, Gemini-specific field names). |
| `<repo>/.cursor/mcp.json` | Cursor | Cursor's MCP config shape. Emitted only when the project opts in. |

Each rendered file carries a banner:

```
// AUTO-GENERATED by scripts/mcp/render.py. DO NOT EDIT.
// Sources: base (ai-playbook/mcp-servers-base.yaml), project (mcp-servers.yaml),
//          personal ($AIPLAYBOOK_PERSONAL_MCP_FILE).
// Run `python -m scripts.mcp.render --project <name>` to regenerate.
```

Per-server, the renderer interpolates env vars at render time only if the
target CLI supports env-var references directly (Claude Code does; Gemini
CLI expects expanded values). For CLIs that require expansion, the render
step reads the current process env — which means **render is not
reproducible across machines unless the same SOPS env is decrypted first.**
This is by design: the rendered artefact is gitignored on the personal
layer; the project layer's rendered `.mcp.json` IS committed (and the CI
render step re-validates it).

The summary output lists which layer contributed each server:

```
✅ Rendered .mcp.json (11 servers)
   hindsight          base
   guardrails-mcp     base
   skills-registry    base + project + personal
   google-workspace-arturo  base + personal
   ...
```

## 7. Extension recipe — adding a new well-known server

1. **Pick a canonical ID.** Short kebab-case; no tenant prefix. Example:
   `twenty-crm`, not `consumer-d-twenty-crm`.
2. **Draft the base entry** in `ai-playbook/mcp-servers-base.yaml`. Required
   fields: `id`, `description`, `transport`, `auth`, `scope: universal`,
   `capabilities_hint`. Endpoints and OAuth tokens stay null at the base layer.
3. **Document env vars** in `specs/env-vars.md` in the same PR. Every new
   env var required by the template gets a row in the relevant
   prefix-table.
4. **Add a deep-dive section** to this file if the auth/scope interplay is
   non-obvious (pattern: `skills-registry` §4 above).
5. **Bump `version:` field** in `mcp-servers-base.yaml` using semver:
   - Patch: description or capabilities_hint wordsmithing only.
   - Minor: added server or added optional env var.
   - Major: renamed canonical ID, removed server, changed required env.
6. **CI re-renders all consumer `.mcp.json` files** and fails if any drift
   emerges — consumers pull the new base via submodule, re-render, commit.

## 8. Anti-patterns

These will be rejected by the validator, or by review:

- **Hardcoding tenant-specific URLs in base.** Base is for templates; any
  URL that names a specific tenant (consumer-b, consumer-d, arturo) lives in
  personal or project.
- **Using `scope: personal` at the base layer.** Mechanically blocked; a
  canonical error with `OVERRIDE: none`.
- **Duplicate canonical IDs across layers.** This is not a duplicate — this
  is override. But two servers with the same ID in a **single** layer is a
  schema violation.
- **Prefixing IDs with a consumer name** (`consumer-c-legacy-guardrails-mcp`).
  The point of the 3-layer model is that the canonical ID stays the same;
  the project layer overrides fields, not the name.
- **Inlining secrets in YAML.** Secrets live in SOPS-encrypted `secrets.env`
  and are injected via env vars. The validator's secrets scanner will reject
  inline keys, `OVERRIDE: none`.
- **Bypassing the renderer.** Hand-editing `.mcp.json` or
  `.gemini/settings.json` after render causes drift. The drift check
  catches this on pre-commit; `--force-with-reason` is disallowed (these
  files are generated artefacts, not sources).
- **Mixing `transport: stdio` with `endpoint`**, or `http` with `command`.
  Validator rejects.

## 9. See also

- [`skills-registry.md`](skills-registry.md) — deep-dive on the
  `skills-registry` server's auth + scope model.
- [`env-vars.md`](env-vars.md) — every env var the renderer may interpolate.
- [`break-glass.md`](break-glass.md) — `--force-with-reason` contract for
  validator and renderer overrides.
- [`error-message-standard.md`](error-message-standard.md) — canonical error
  shape the validator/renderer emits.
- [`dispatcher-chain.md`](dispatcher-chain.md) — 3-level inheritance model
  the layer semantics mirror.
- `mcp-servers-base.yaml` — the base layer itself; authoritative for
  server templates.
