# env-vars.md

> **Status**: stub, v0.1.0. Populated in **T09**.

## Namespace convention

| Prefix | Owner | Example | Source |
|---|---|---|---|
| `AIPLAYBOOK_` | This repo's scripts. | `AIPLAYBOOK_DEBUG=1` | Runtime env. |
| `consumer-d_` | consumer-d (personal). | `consumer-d_CORE_DIR`, `consumer-d_VPS_HOST` | SOPS-decrypted + shell env. |
| `consumer-c-legacy_` | consumer-c-legacy consumer. | `consumer-c-legacy_DATABASE_URL` | `.env` + secret store. |
| `HINDSIGHT_` | Hindsight MCP credentials. | `HINDSIGHT_API_KEY`, `HINDSIGHT_URL`, `HINDSIGHT_BANK_ID` | SOPS-decrypted (`consumer-d/secrets/secrets.env`). |
| `LANGFUSE_` | Langfuse tracing. | `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | SOPS-decrypted. |
| `OTEL_` | OpenTelemetry SDK. | `OTEL_EXPORTER_OTLP_ENDPOINT` | Local (OTel Collector) or pointing at VPS. |

## Rules

- **No plaintext secrets in git.** Always via SOPS → decrypted at runtime.
- **No cross-prefix reads.** A playbook script does not read `consumer-d_*` or `consumer-c-legacy_*` directly; those flow through explicit CLI args.
- **Every prefix's vars are enumerated here.** Adding a new var = updating this spec.

## Populated in T09

Full enumerated table, default values, required vs optional, and the `scripts/doctor.py` check that warns on missing required vars.
