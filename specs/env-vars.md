# env-vars.md

> **Status**: stub, v0.1.0. Populated in **T09**.

## Namespace convention

| Prefix | Owner | Example | Source |
|---|---|---|---|
| `AIPLAYBOOK_` | This repo's scripts. | `AIPLAYBOOK_DEBUG=1`, `AIPLAYBOOK_PROJECTS_FILE`, `AIPLAYBOOK_PROJECTS_ROOTS` | Runtime env. |
| `ELIGIA_` | eligia-core (personal). | `ELIGIA_CORE_DIR`, `ELIGIA_VPS_HOST` | SOPS-decrypted + shell env. |
| `OPENTRATTOS_` | openTrattOS consumer. | `OPENTRATTOS_DATABASE_URL` | `.env` + secret store. |
| `HINDSIGHT_` | Hindsight MCP credentials. | `HINDSIGHT_API_KEY`, `HINDSIGHT_URL`, `HINDSIGHT_BANK_ID` | SOPS-decrypted (`eligia-core/secrets/secrets.env`). |
| `LANGFUSE_` | Langfuse tracing. | `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | SOPS-decrypted. |
| `OTEL_` | OpenTelemetry SDK. | `OTEL_EXPORTER_OTLP_ENDPOINT` | Local (OTel Collector) or pointing at VPS. |

## Rules

- **No plaintext secrets in git.** Always via SOPS → decrypted at runtime.
- **No cross-prefix reads.** A playbook script does not read `ELIGIA_*` or `OPENTRATTOS_*` directly; those flow through explicit CLI args.
- **Every prefix's vars are enumerated here.** Adding a new var = updating this spec.

## Populated in T09

Full enumerated table, default values, required vs optional, and the `scripts/doctor.py` check that warns on missing required vars.

## v0.1.0 populated entries (T02-pre)

The `AIPLAYBOOK_` prefix carries these already:

| Var | Purpose | Default |
|---|---|---|
| `AIPLAYBOOK_PROJECTS_FILE` | Override registry path. | `~/.ai-playbook/projects.yaml` |
| `AIPLAYBOOK_PROJECTS_ROOTS` | Extra scan roots (comma or OS-pathsep separated). | empty; falls back to `~/Projects`, `~/projects`, `C:/Projects`, `/opt`, `/srv`. |

See `specs/projects-registry.md`.
