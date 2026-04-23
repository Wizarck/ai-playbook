# env-vars.md

> **Status**: v1.0.0. Supersedes the T02-pre stub. Populated in T09.

Single source of truth for every env var the playbook (or a playbook script) reads. Adding a new var = updating this spec in the same commit.

---

## Namespace convention

| Prefix | Owner | Example | Source |
|---|---|---|---|
| `AIPLAYBOOK_` | This repo's scripts. | `AIPLAYBOOK_PROJECTS_FILE` | Runtime env. |
| `consumer-d_` | consumer-d (personal). | `consumer-d_CORE_DIR`, `consumer-d_VPS_HOST` | SOPS-decrypted + shell env. |
| `consumer-c-legacy_` | consumer-c-legacy consumer. | `consumer-c-legacy_DATABASE_URL` | `.env` + secret store. |
| `HINDSIGHT_` | Hindsight MCP credentials. | `HINDSIGHT_API_KEY` | SOPS-decrypted. |
| `LANGFUSE_` | Langfuse tracing. | `LANGFUSE_HOST` | SOPS-decrypted. |
| `OTEL_` | OpenTelemetry SDK. | `OTEL_EXPORTER_OTLP_ENDPOINT` | Local Collector or VPS pointer. |
| `ANTHROPIC_` | Anthropic SDK (playbook scripts read a subset). | `ANTHROPIC_API_KEY` | SOPS-decrypted. |
| `GIT_*` | Standard git env (read-only; playbook uses for actor resolution). | `GIT_AUTHOR_EMAIL` | Git. |

## Rules

- **No plaintext secrets in git.** Always via SOPS -> decrypted at runtime.
- **No cross-prefix reads.** A playbook script does not read `consumer-d_*` or `consumer-c-legacy_*` directly; those flow through explicit CLI args.
- **Every prefix's vars are enumerated below.** Adding a new var = updating this spec in the same PR.
- **Canonical name wins over alias.** Where a var has a back-compat alias (see `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` below), the canonical name is preferred; `scripts/doctor.py` emits a warning when the alias is the only value set.

---

## `AIPLAYBOOK_*` (this repo)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `AIPLAYBOOK_PROJECTS_FILE` | `AIPLAYBOOK_` | Override the projects-registry YAML path. | no | `~/.ai-playbook/projects.yaml` | `scripts/discover_projects.py::resolve_registry_path` |
| `AIPLAYBOOK_PROJECTS_ROOTS` | `AIPLAYBOOK_` | Extra scan roots (comma- or OS-pathsep-separated). | no | empty (falls back to `~/Projects`, `~/projects`, `C:/Projects`, `/opt`, `/srv`) | `scripts/discover_projects.py::get_default_roots` |
| `AIPLAYBOOK_DEBUG` | `AIPLAYBOOK_` | Verbose trace logging from playbook scripts. Truthy = on. | no | unset (off) | any script's logger (T07c) |
| `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` | `AIPLAYBOOK_` | Minimum tokens per `cache_control` breakpoint before prompt caching is activated (see `specs/prompt-caching.md`). **Canonical name.** | no | `1024` | `scripts/tracing/*` + `scripts/prompt_injection_filter.py` |
| `ANTHROPIC_CACHE_TOKENS_MIN` | *(bare, alias)* | **Back-compat alias** for `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN`. Accepted but `scripts/doctor.py` warns and recommends renaming. | no | inherits from canonical default | same sites as the canonical var |

### Resolution order

When both canonical and alias are set, the canonical value wins and the alias is ignored. When only the alias is set, the alias value is used and `scripts/doctor.py` emits a `⚠️ warning` verdict recommending `export AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN=$ANTHROPIC_CACHE_TOKENS_MIN`.

> **Why this alias exists.** The Anthropic SDK ecosystem historically reads `ANTHROPIC_*`-prefixed vars. When the playbook added a cache-tuning knob in T04, the initial draft used the bare name. T09 canonicalises on the `AIPLAYBOOK_` prefix (per the Rules section above: no cross-prefix reads). The alias gives existing consumers one playbook-major of runway. Removal is targeted for v2.0.0.

---

## `consumer-d_*` (consumer-d, personal)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `consumer-d_CORE_DIR` | `consumer-d_` | Path to consumer-d checkout. | yes (if consumer-d consumer) | unset | consumer-d dispatchers, not playbook scripts |
| `consumer-d_VPS_HOST` | `consumer-d_` | SSH target for VPS k3s. | yes (consumer-d ops) | unset | consumer-d runbooks |

Playbook scripts MUST NOT read these directly — they flow through the consumer-d dispatcher (see `C:\Projects\consumer-d\consumer-d.md`).

---

## `HINDSIGHT_*`

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `HINDSIGHT_API_KEY` | `HINDSIGHT_` | API key for Hindsight memory MCP server. | yes (if hindsight MCP enabled) | unset | MCP server at connect-time |
| `HINDSIGHT_URL` | `HINDSIGHT_` | Base URL of Hindsight deployment. | yes (if hindsight MCP enabled) | unset | MCP server at connect-time |
| `HINDSIGHT_BANK_ID` | `HINDSIGHT_` | Project-scoped memory bank id. | recommended | derived from `project` slug | MCP server at connect-time |

---

## `SKILLS_REGISTRY_*`

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `SKILLS_REGISTRY_URL` | `SKILLS_REGISTRY_` | Base URL of the consumer-d-skills HTTP registry. | yes (if `skills-registry` MCP enabled) | unset | `scripts/skills_registry.py::_load_credentials` |
| `SKILLS_REGISTRY_API_KEY` | `SKILLS_REGISTRY_` | Bearer token for `scope=personal` / `scope=<project>` queries. | conditional (required for non-`public` scope) | unset | `scripts/skills_registry.py::_load_credentials` |

See `specs/skills-registry.md` for scope semantics and the degraded-mode path.

---

## `LANGFUSE_*`

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `LANGFUSE_HOST` | `LANGFUSE_` | Langfuse instance base URL. | yes (for LLM tracing) | unset | `scripts/tracing/*` |
| `LANGFUSE_PUBLIC_KEY` | `LANGFUSE_` | Public key for project. | yes | unset | `scripts/tracing/*` |
| `LANGFUSE_SECRET_KEY` | `LANGFUSE_` | Secret key (SOPS). | yes | unset | `scripts/tracing/*` |

---

## `OTEL_*`

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `OTEL_` | OTLP collector endpoint. | recommended | `http://localhost:4318` | `scripts/tracing/setup.py` (T07c) |
| `OTEL_SERVICE_NAME` | `OTEL_` | Service name attribute on spans. | no | `ai-playbook` | `scripts/tracing/setup.py` |
| `OTEL_RESOURCE_ATTRIBUTES` | `OTEL_` | Comma-separated resource attributes. | no | unset | `scripts/tracing/setup.py` |

---

## `ANTHROPIC_*`

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | `ANTHROPIC_` | Anthropic API key (SOPS-decrypted). | yes (if the playbook calls Anthropic) | unset | Anthropic SDK at call-time |
| `ANTHROPIC_CACHE_TOKENS_MIN` | *(alias)* | See `AIPLAYBOOK_*` table row. | no | see alias row | alias of canonical var |

---

## `SMTP_*` (email notifications from `scripts/notify.py`)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `SMTP_HOST` | `SMTP_` | SMTP server host. | no | `smtp.gmail.com` | `scripts/notify.py` |
| `SMTP_PORT` | `SMTP_` | SMTP server port (STARTTLS). | no | `587` | `scripts/notify.py` |
| `SMTP_USER` | `SMTP_` | SMTP username. | yes (to enable email) | `$GIT_AUTHOR_EMAIL` | `scripts/notify.py` |
| `SMTP_PASSWORD` | `SMTP_` | SMTP password (SOPS-decrypted; Gmail requires app-password). | yes (to enable email) | unset | `scripts/notify.py` |

When any of `SMTP_USER` / `SMTP_PASSWORD` is unset, email delivery is **silently disabled**; the JSONL queue still writes and the dashboard bell still surfaces every event.

### Notification tuning (under `AIPLAYBOOK_*`)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `AIPLAYBOOK_NOTIFICATIONS_FILE` | `AIPLAYBOOK_` | Override the JSONL queue path. | no | `<repo>/.ai-playbook/notifications.jsonl` | `scripts/notify.py` |
| `AIPLAYBOOK_NOTIFICATIONS_FROM` | `AIPLAYBOOK_` | Email `From:` header. | no | `$SMTP_USER` | `scripts/notify.py` |
| `AIPLAYBOOK_NOTIFICATIONS_TO` | `AIPLAYBOOK_` | Email `To:` recipient. | no | `$SMTP_USER` | `scripts/notify.py` |
| `AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY` | `AIPLAYBOOK_` | Lowest severity that triggers email. Values: `silent \| info \| warn \| error \| never`. | no | `warn` | `scripts/notify.py` |

---

## `ATLASSIAN_*` (Jira automation via `scripts/issue_sync.py` / `scripts/release_cut.py`)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `ATLASSIAN_URL` | `ATLASSIAN_` | Jira Cloud base URL (e.g. `https://consumer-a.atlassian.net`). | yes (for private-repo tracker sync) | unset | `scripts/issue_sync.py`, `scripts/release_cut.py` |
| `ATLASSIAN_USERNAME` | `ATLASSIAN_` | Atlassian account email (for REST basic auth). | yes | unset | same |
| `ATLASSIAN_API_TOKEN` | `ATLASSIAN_` | Personal API token (SOPS-decrypted). | yes | unset | same |
| `AIPLAYBOOK_JIRA_DEFAULT_PROJECT` | `AIPLAYBOOK_` | Jira project key for private consumers without an explicit mapping. | no | `consumer-a` | `scripts/issue_sync.py` |
| `AIPLAYBOOK_JIRA_DEFAULT_ISSUE_TYPE` | `AIPLAYBOOK_` | Jira issue type for auto-created stories. | no | `Story` | `scripts/issue_sync.py` |

---

## `AIPLAYBOOK_GH_*` (GitHub automation)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `AIPLAYBOOK_GH_PROJECT_NUMBER` | `AIPLAYBOOK_` | GitHub Project (v2) number to auto-add new Issues to for public repos. | no (Issue-only if unset) | unset | `scripts/issue_sync.py` |

Uses the standard `GH_TOKEN` / `GITHUB_TOKEN` for authentication — pulled from Actions context automatically, or from local `gh auth status` in human runs.

---

## Standard `GIT_*` (read-only)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `GIT_AUTHOR_EMAIL` | `GIT_` | Actor identity for break-glass audit trail. | no | falls through to `git config user.email` | `scripts/_break_glass.py::apply_break_glass` |
| `GIT_COMMITTER_EMAIL` | `GIT_` | Alternate actor source. | no | same fallback chain | `scripts/schema_validate.py::_guess_owner_email` |

---

## Pre-commit env vars (read by hooks, set by the pre-commit framework)

| Var | Prefix | Purpose | Required? | Default | Where read |
|---|---|---|---|---|---|
| `PRE_COMMIT_COMMIT_MSG_FILE` | `PRE_COMMIT_` | Path to the staged commit message file during the `commit-msg` stage. | no (set by pre-commit) | unset outside the `commit-msg` stage | `scripts/block_manual_spec_edit.py::read_commit_message` |

---

## See also

- `specs/projects-registry.md` — consumer of `AIPLAYBOOK_PROJECTS_FILE` and `AIPLAYBOOK_PROJECTS_ROOTS`.
- `specs/break-glass.md` — consumer of `GIT_AUTHOR_EMAIL` via `scripts/_break_glass.py`.
- `specs/prompt-caching.md` — consumer of `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` (and its alias).
- `scripts/doctor.py` — emits warnings when required vars are missing or when deprecated aliases are set.
