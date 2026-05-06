# agent-telemetry.md

> **Status**: v1.0.0. New in ai-playbook v0.10.0. Companion to
> [project-board-sync.md](project-board-sync.md) — defines layer L5 of the
> 7-layer enforcement contract and the broader pattern for emitting
> agent-runtime telemetry from a Claude Code session into a project's existing
> observability stack.
>
> **Enforcement**: 📋 spec-only — see [enforcement-status.md](enforcement-status.md).
> The pattern is plug-and-play (4 environment variables) but adoption is
> opt-in per consumer; no harness validates that traces are actually being
> emitted today.

## 1. Why this spec

Three forces converged in early 2026 that change the cost-benefit of
agent telemetry from "nice to have" to "default-on":

1. **Claude Code native OTLP support**: Anthropic shipped first-class
   OpenTelemetry export from Claude Code via four environment variables
   (per [Claude Code monitoring docs](https://code.claude.com/docs/en/monitoring-usage)).
   Every tool call (Bash, Edit, Read, Grep, Agent, …), every LLM turn, and
   every metric becomes an OTel span/log/metric without any code changes
   inside the agent.

2. **OpenTelemetry GenAI semantic conventions stable**: per
   [OpenTelemetry blog Apr 2025](https://opentelemetry.io/blog/2025/ai-agent-observability/)
   and [Uptrace 2026 guide](https://uptrace.dev/blog/opentelemetry-ai-systems),
   the `gen_ai.*` namespace (model, token counts, finish reason, tool calls,
   conversation events) landed stable in early 2026. Spans emitted by Claude
   Code carry the same attribute names a backend like Langfuse / Phoenix /
   Uptrace expects natively.

3. **Langfuse OTLP ingestion endpoint mature**: per
   [Langfuse OTel integration](https://langfuse.com/integrations/native/opentelemetry),
   Langfuse exposes `/api/public/otel` with regional variants and accepts
   HTTP/protobuf or HTTP/JSON. A consumer with an existing Langfuse project
   (Cloud or self-hosted) can ingest Claude Code traces with **zero new
   infrastructure** — the existing project, dashboards, alerts, and cost
   widgets all work as-is.

The previous reasonable answer ("write our own audit log to JSONL") is no
longer the cost-minimum. **Reuse over reinvent** is now the canonical answer.

## 2. The pattern

### 2.1 Four-env-var configuration

Claude Code emits OTLP when the following are set in the session
environment:

```bash
# 1. Enable telemetry
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# 2. Pick exporter for metrics + logs (traces is opt-in via OTEL_TRACES_EXPORTER)
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_TRACES_EXPORTER=otlp        # beta but stable enough for 2026 use

# 3. OTLP endpoint (HTTP/protobuf — Langfuse does not support gRPC)
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel

# 4. Langfuse Basic Auth header (base64 of "pk-lf-...:sk-lf-...")
LANGFUSE_AUTH=$(printf "%s:%s" "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${LANGFUSE_AUTH}"
```

Set these in the consumer project's `.envrc` (with `direnv allow`) or in
the consumer's preferred secret-loading shell hook. The values for
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` come from the consumer's
SOPS-encrypted secrets store.

### 2.2 Resource attributes (slice / wave tagging)

To make traces searchable per slice, set `OTEL_RESOURCE_ATTRIBUTES` before
invoking Claude Code at the start of an `/opsx:apply` session:

```bash
export OTEL_RESOURCE_ATTRIBUTES="service.name=claude-code,project=<consumer>,slice=<change-id>,wave=N,phase=apply"
```

The `slice=<id>` tag is what Langfuse's UI session/trace filters key off; a
consumer can search "all spans for slice `risk-engine-protections`" and see
the full timeline of the AI's tool calls during that slice's apply phase.

The companion script `scripts/opsx_apply_companion.py` (per
`release-management.md` §6.5) is the canonical place to set these — it already
runs at slice start, has the change-id in scope, and can read `wave` from the
slicing artefact. v0.10.1 will extend the companion to emit the `export`
lines as stdout for shell-eval.

### 2.3 What gets traced (Claude Code OTLP semantic mapping)

| Concept | OTel signal | Notes |
|---|---|---|
| `/opsx:apply` invocation | One **trace** | Root span: `claude_code.session`, attributes include `slice` from §2.2 |
| Each tool call (Bash, Edit, Read, Grep, Agent, …) | One **span** | Span name `claude_code.tool.<tool_name>`; attributes include tool input hash + duration + outcome |
| LLM turns (the AI's own thinking) | **Generations** under the trace | OTel `gen_ai.*` attributes per the stable 2026 conventions: `gen_ai.system=anthropic`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, etc. |
| Subagent spawns | Child trace, parent-link to root | The Agent tool's `isolation: "worktree"` mode is preserved as a span attribute for diagnostic queries |
| Metrics (sessions, tool calls, tokens, costs) | OTLP **metrics** stream | Time-series for dashboards (queries-per-minute, p95 latency per tool, token throughput per slice) |
| Errors / failures | OTLP **logs** stream | Tool-call non-zero exits, hook blocks, rate-limit hits |

### 2.4 What gets *answered* by the trace

Three concrete questions that were "trust the AI" before this spec are now
post-hoc queries:

1. **"Did the AI run `opsx_apply_companion.py` before its first task commit
   on slice X?"** → Langfuse query: filter by `slice=X`, look for a span
   with name matching `claude_code.tool.Bash` and an attribute matching the
   companion script's invocation. If absent, L6's pre-flight rebase didn't
   fire — the slice is in undefined state.

2. **"How long did Wave 2 take? Where was the bottleneck?"** → Langfuse
   sessions view filtered by `wave=2`, sorted by total trace duration. The
   trace with the most tool spans is the slice with the most rework.

3. **"Did the AI hallucinate a `gh project item-list` claim?"** → Langfuse
   trace inspector: find the verdict message's parent trace; check whether
   any `gh project` invocation appears as a tool span. If not, the claim
   was fabricated (per `verification-before-completion.md` §4.1's
   tool-exit-code-over-text rule).

## 3. Reuse over reinvent (default pattern)

If the consumer project (or a sibling project under the same maintainer) has
an existing Langfuse instance, **reuse it**. Specifically:

| Existing artefact | Reuse strategy |
|---|---|
| Langfuse Cloud project keys | Use the existing public/secret pair; tag traces with `project=<consumer>` to namespace |
| Self-hosted Langfuse | Point `OTEL_EXPORTER_OTLP_ENDPOINT` at the self-hosted URL (e.g. `https://langfuse.example.com/api/public/otel`) |
| Existing dashboards / cost widgets | Work as-is once traces start landing — Langfuse's per-project filters do the namespacing |
| Existing post-response tracers (e.g. `lib/telemetry/anthropic_tracer.py`) | Continue using them for non-Claude-Code call sites (Hindsight, internal LLM workflows). Claude Code OTLP and post-response tracers can coexist and feed the same Langfuse project |

For the Arturo-personal stack: the consumer-d infrastructure already operates a
Langfuse Cloud project with keys in
`C:/Projects/consumer-d/secrets/secrets.env` (`LANGFUSE_PUBLIC_KEY` /
`LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`). Every Arturo-owned consumer
(consumer-e, consumer-c-legacy, consumer-b, consumer-d-rag, consumer-d-skills) reuses
that project. The `consumer-d/dashboard` already renders 4 Langfuse-backed
widgets (`cost-estimate`, `top-models`, `traces-today`, `error-rate`); these
widgets surface Claude Code agent activity once OTLP export is enabled,
**without dashboard code changes** — the widgets query Langfuse's public API
generically.

## 4. Minimum viable path for projects without an existing Langfuse

Consumer projects that lack any observability stack still need an audit
trail (per `release-management.md` §5.5 base-SHA traceability + EU AI Act
forward-looking compliance per [project-board-sync.md](project-board-sync.md)
§4.5). The minimum viable path:

1. Sign up for Langfuse Cloud free tier (20K observations/month).
2. Set the four env vars from §2.1 + the resource attributes from §2.2.
3. Done. Free tier is enough for a single-developer-AI workflow at the
   typical OpenSpec slice cadence (one slice ≈ 100-500 spans).

Self-hosted Langfuse (Docker / k3s) is an option for projects with stricter
data-residency constraints; the OTLP ingestion endpoint is the same shape.
See [Langfuse self-hosting docs](https://langfuse.com/self-hosting).

## 5. Anti-patterns

### 5.1 Standing up a custom OTLP collector

Do **not** stand up an OpenTelemetry Collector (otelcol) just to receive
Claude Code traces. The collector is justified when:
- You need to fan-out to multiple backends (Langfuse + Datadog + Honeycomb).
- You need to scrub / redact attributes before they leave the host.
- You need to batch / buffer for offline-first hosts.

For the typical ai-playbook consumer (single Langfuse backend, no PII in
agent telemetry, online dev environment), the collector is yak-shaving.
Send directly to Langfuse's `/api/public/otel`.

### 5.2 Inventing a custom audit log format

Do **not** write a project-specific JSONL audit log (`/var/log/agent.jsonl`,
`.ai-trace.json`, etc.) when OTLP + Langfuse is available. The custom format
forces:
- Custom dashboards to inspect it.
- Custom retention policies.
- Custom search tooling.
- Future migration to OTel anyway.

The OTel + Langfuse pattern in §2 obviates all four.

### 5.3 Logging agent telemetry to the project's `data/` directory

Some early experiments wrote agent traces to project-checked-in JSONL files
(`data/agent-runs/<date>.jsonl`). This is **rejected** because:
- Trace data grows linearly with usage; commits balloon.
- Secrets embedded in tool inputs (env vars, file paths under `~/.secrets/`)
  leak into git history.
- Searchability is grep-only.

OTel + Langfuse keeps trace data outside the repo entirely.

### 5.4 Disabling telemetry "for performance"

The Claude Code OTLP exporter is asynchronous and batched (per
[Claude Code monitoring docs](https://code.claude.com/docs/en/monitoring-usage)
default `OTEL_METRIC_EXPORT_INTERVAL=60s`, `OTEL_LOGS_EXPORT_INTERVAL=5s`).
The performance overhead in steady-state is well under 50ms per tool call.

If a developer disables telemetry to "make Claude Code faster", they are
trading auditability for an unmeasurable speedup; the trade is forbidden by
this spec for any work falling under `release-management.md` §4.5
(slice-branch PR work). Disabling for ad-hoc scratch sessions is fine.

## 6. Cross-references

- [project-board-sync.md](project-board-sync.md) §2 (this spec is L5 of that contract)
- [release-management.md](release-management.md) §6.5 (companion script integration point)
- [verification-before-completion.md](verification-before-completion.md) §4.1 (tool-exit-code-over-text rule that L5 enables auditing of)
- [data-retention.md](data-retention.md) (L5 trace retention expectations)
- [env-vars.md](env-vars.md) (canonical names for the 4 OTLP env vars)
- External: [Claude Code monitoring docs](https://code.claude.com/docs/en/monitoring-usage)
- External: [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- External: [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)
- External: [OpenTelemetry blog: AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- External: [Uptrace 2026 OpenTelemetry for AI Systems](https://uptrace.dev/blog/opentelemetry-ai-systems)
