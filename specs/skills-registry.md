# skills-registry.md

> **Status**: v1.0.0. Defines the integration contract between
> playbook consumers and the `eligia-skills` HTTP registry.

The skills registry is the **authoritative discovery surface** for project skills.
Consumers query it at bootstrap and mid-task instead of maintaining a
copy-pasted `SKILL.md` index in `.claude/skills/`. The service lives at
`eligia-skills.palafitofood.com` behind a Cloudflare Tunnel (local port 9002 in
dev). This spec defines the HTTP contract, the scope model, caching, degraded
behaviour, and the security envelope.

---

## 1. Purpose

Prior to T20, every consumer had to `git clone` or `cp -r` the skills it wanted
available to its `.claude/skills/` directory. That model:

- **Drifts silently.** Skill X updated in eligia-skills master → stale copies
  everywhere else for weeks.
- **Mixes scopes.** A personal skill (Arturo-only, e.g. ELIGIA infra) leaking
  into a shared consumer repo is an information-leakage risk.
- **Has no catalog surface.** The agent cannot "ask what exists"; it must
  enumerate the directory manually.

The registry replaces all three failure modes with a single HTTP surface.
Consumers keep `.claude/skills/` for **locally-authored** skills only; everything
shared comes over the wire.

## 2. API contract

Authoritative contract lives at
[`eligia-skills/docs/api-contract.md`](https://github.com/Wizarck/eligia-skills/blob/master/docs/api-contract.md).
Summary below — the upstream doc wins on any conflict.

### `GET /api/v1/skills`

Query parameters:

| Param | Type | Required | Meaning |
|---|---|---|---|
| `scope` | string | no | `public` | `personal` | `<project-slug>`. Default `public`. |
| `since` | ISO-8601 | no | Return only skills added/updated after this timestamp. |

Response `200 application/json`:

```json
{
  "skills": [
    {
      "name": "bmad-code-review",
      "description": "3-layer parallel code review",
      "source": "ai-playbook/.claude/skills/bmad-code-review/SKILL.md",
      "version": "1.0.0",
      "scope": "public"
    }
  ],
  "fetched_at": "2026-04-23T12:00:00Z"
}
```

Every entry carries: `name` (kebab-case, unique within scope), `description`
(one sentence), `source` (origin-repo-relative path or URL), `version`
(semver), `scope` (same enum as the query).

Error responses:

| Code | Condition | Body |
|---|---|---|
| 400 | Invalid `scope` or malformed `since`. | `{"error": "..."}` |
| 401 | Missing / invalid bearer when scope requires auth. | `{"error": "unauthorised"}` |
| 404 | Unknown skill name (on `GET /api/v1/skills/<name>`). | `{"error": "not_found"}` |
| 5xx | Server error. | `{"error": "..."}` |

### `GET /api/v1/skills/<name>` (optional)

Returns a single envelope with one skill entry or 404. `scripts/skills_registry.py`
uses the list endpoint and filters locally when this endpoint is unavailable, so
it remains optional for minimum-viable implementations.

## 3. Scopes

| Scope | Visibility | Auth required |
|---|---|---|
| `public` | All consumers. | No (CF Tunnel already gates network access). |
| `personal` | Arturo-only (see `specs/dispatcher-chain.md` level 3). | Yes — bearer token. |
| `<project-slug>` | Callers working in a specific project. | Conditional — see projects registry. |

Scope resolution on the consumer side mirrors `dispatcher-chain.md`:

1. If cwd is inside a `personal: true` project per
   `~/.ai-playbook/projects.yaml`, the consumer MAY query `scope=personal`.
2. Otherwise `scope=public` is the default; `scope=<slug>` is explicit opt-in
   (e.g. a bmad-code-review variant specific to `palafito-b2b`).
3. The registry refuses `scope=personal` without a bearer token.

## 4. Caching

Consumers cache the fetched list per-session at
`<consumer>/.claude/skills-cache.json` with the shape:

```json
{
  "fetched_at": "2026-04-23T12:00:00Z",
  "scope": "public",
  "skills": [ /* as above */ ]
}
```

Rules:

- Cache TTL is implicit: one session. New session → refetch.
- `scripts/doctor.py --refresh-skills-cache` invalidates on demand (lands in
  T20b follow-up; not in this spec's scope).
- The cache file is **gitignored** by the consumer's `.gitignore` template.
- Never cache `scope=personal` entries on a machine whose projects registry
  lacks the `personal: true` flag. The consumer script enforces this gate.

## 5. Fallback / degraded mode

If the registry is unreachable (DNS, 5xx, timeout):

1. `scripts/skills_registry.py list` exits `2` with the canonical error shape.
2. With `--force-with-reason "<≥10 chars>"` it returns an empty list and exits
   `0` so the caller can proceed with **locally-defined skills only**.
3. The consumer agent surfaces a `DEGRADED_CONTEXT`-shaped banner in its
   session-start context (parallel to how Hindsight outages surface).
4. The agent MUST NOT fabricate skill names to fill the gap. If a task requires
   a skill that is not in `.claude/skills/` and the registry is down, the agent
   escalates with `❓ CLARIFICATION NEEDED`.

See `specs/degradation-modes.md` §1 for the state-enum semantics; the registry
counts as part of `DEGRADED_CONTEXT` alongside Hindsight.

## 6. Security

- **CF Tunnel is not sufficient auth on its own** for `scope=personal`.
  Non-local deployments require `SKILLS_REGISTRY_API_KEY` on the caller and
  bearer-token verification on the server.
- **Key rotation.** The API key lives in SOPS-encrypted env (`secrets.env`).
  Rotation follows the same cadence as Hindsight (see
  `eligia-core/docs/operations/eligia-secrets-strategy.md`).
- **Response sanitisation.** The registry must never echo caller-supplied input
  unescaped in its error messages (prevents response-splitting in a proxy).
- **No plaintext transport.** Production URL is `https://` only; the local
  `http://localhost:9002` form is accepted by the client for dev but logged as
  a `⚠️` warning when `SKILLS_REGISTRY_URL` does not start with `https://`.
- **Scope enforcement is server-side.** The client sends `scope`; the server
  authoritatively filters — never trust that the client "won't peek".

## 7. Client script

[`scripts/skills_registry.py`](../scripts/skills_registry.py) is the playbook-side
helper. CLI:

```
python -m scripts.skills_registry list [--scope SCOPE] [--since ISO]
                                       [--url URL] [--json]
                                       [--force-with-reason TEXT]
python -m scripts.skills_registry show <name> [--scope SCOPE]
```

Importable API:

```python
from scripts.skills_registry import list_skills, skill_by_name

entries = list_skills(scope="public")
entry = skill_by_name("bmad-code-review")
```

Behaviour:

- Reads `SKILLS_REGISTRY_URL` (required) and `SKILLS_REGISTRY_API_KEY`
  (optional, required when scope != `public`).
- Emits the canonical error shape on failure (`specs/error-message-standard.md`).
- `--force-with-reason` degrades to an empty list (exit 0) so consumers can
  boot in offline dev mode.

## 8. Cross-refs

- [`mcp-servers-schema.md`](mcp-servers-schema.md) — the `skills-registry` MCP
  server entry documents the auth + scope interplay.
- [`memory-hierarchy.md`](memory-hierarchy.md) — skills are a *config artefact*
  tier, distinct from the runtime memory tiers defined there.
- [`taxonomy.md`](taxonomy.md) — canonical definition of "skill".
- [`dispatcher-chain.md`](dispatcher-chain.md) — the three-level scope model
  the `scope` enum mirrors.
- [`degradation-modes.md`](degradation-modes.md) — `DEGRADED_CONTEXT` applies
  when the registry is unreachable.
- [`env-vars.md`](env-vars.md) — `SKILLS_REGISTRY_*` env var table (populated
  in the same PR).
