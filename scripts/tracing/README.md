# `scripts/tracing/` — telemetry pipeline

The ai-playbook emits observability data through **two complementary transports**:

| Transport | Driven by | Lives in | Best for |
|---|---|---|---|
| OpenTelemetry spans + Langfuse | `init_tracing()` + `trace_emit.span()` + `cli_emit()` | Langfuse Cloud / Tempo / Phoenix / any OTLP-compatible backend | Real-time UI, correlation across LLM calls, multi-app aggregation |
| `rule-event/v1` JSONL | `cli_emit()` → `rule_event_logger.log_event()` | `<state-dir>/rule-events.jsonl` (gitignored) | Offline ops, append-only audit, the `python -m scripts.telemetry.report` CLI |

Both transports are populated from the same call sites and are independently fail-safe — losing one (network, missing creds, disk full, OTel SDK absent) does **not** affect the other and never alters a rule's exit code.

## What is captured

- **L1 rule executions** — every `scripts/rules/<slug>.rule.py` invocation goes through `cli_emit()`, which opens an OTel span named `rule.<slug>` AND appends a JSONL row. Span attributes:
  - `ai_playbook.rule.slug`, `ai_playbook.rule.trigger`, `ai_playbook.rule.llm`
  - `ai_playbook.rule.verdict` (`allow` / `block` / `warn`)
  - `ai_playbook.rule.latency_ms`
- **Custom in-code instrumentation** — scripts can call `trace_emit.span("name", attrs)` to open a span around any block. Helpers `gen_ai_attrs`, `routing_attrs`, `degradation_attrs`, `override_attrs` produce canonical attribute dicts (see [`trace_emit.py`](trace_emit.py) for the full set).
- **Custom resource attributes** — every span carries `service.name`, `service.version`, and `ai_playbook.playbook_version`.

## Required env vars (any subset works)

| Env var | What it enables |
|---|---|
| `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | Langfuse Cloud export (LLM-native UI) |
| `LANGFUSE_HOST` | Self-hosted Langfuse (default `https://cloud.langfuse.com`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP export to any compatible backend (Tempo, Phoenix, Datadog, your own collector). Standard `OTEL_EXPORTER_OTLP_*` knobs (headers, protocol, timeout, compression) are honoured by the exporter automatically. |
| `AI_PLAYBOOK_STATE_DIR` | Override the `<cwd>/.ai-playbook-state/` default for the JSONL log location |
| `AIPLAYBOOK_TRACING_DISABLED=1` | Hard kill switch — `init_tracing()` returns a no-op tracer; JSONL still writes. Useful in CI when you don't want telemetry chatter. |

Missing Langfuse keys → Langfuse exporter silently skipped. Missing OTLP endpoint → OTLP exporter silently skipped. Missing the optional `opentelemetry-exporter-otlp-proto-http` package → one-line warning, JSONL still writes.

## Bootstrap (apps using the pipeline)

```python
from scripts.tracing import init_tracing

# Returns an opentelemetry.trace.Tracer (or no-op stand-in). Safe to call
# multiple times — subsequent calls reuse the existing process-global provider.
tracer = init_tracing("my-service")
```

Once `init_tracing` has run, **every** call to `trace_emit.span(...)` and every `cli_emit(...)`-wrapped rule fires through the configured exporters. Without `init_tracing`, those calls degrade to no-ops (and the JSONL row still writes for rules).

## Consuming the data

### Path A — Langfuse Cloud (or self-hosted)

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-xxx
export LANGFUSE_SECRET_KEY=sk-lf-xxx
# (optional) export LANGFUSE_HOST=https://langfuse.your-domain.com
```

Spans appear as Langfuse traces. `rule.<slug>` shows up as a span whose duration is the rule's wall-clock time; attributes flow through to the metadata panel.

### Path B — Local OTel collector + Tempo/Phoenix/whatever

Run a collector (any image — `otel/opentelemetry-collector-contrib` works) listening on `4318` OTLP HTTP:

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http: { endpoint: 0.0.0.0:4318 }

exporters:
  # Pick whichever backend(s) you wired up:
  otlphttp/tempo: { endpoint: http://tempo:4318 }
  otlphttp/phoenix: { endpoint: http://phoenix:6006 }

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp/tempo, otlphttp/phoenix]
```

Then point ai-playbook at it:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
# (optional) export OTEL_EXPORTER_OTLP_HEADERS="x-tenant=acme,x-team=platform"
```

Spans now flow into both Langfuse and your collector. The collector fans out to as many backends as you want **without** any change to the ai-playbook code.

### Path C — Read the JSONL directly

The JSONL log is the source of truth for the bundled monthly report and is the recommended path for any offline / desktop / forensic UI that prefers a file API over a network query. Schema is documented at the top of [`scripts/telemetry/rule_event_logger.py`](../telemetry/rule_event_logger.py). Default location:

```bash
ls .ai-playbook-state/rule-events.jsonl
# Tail-friendly:
tail -f .ai-playbook-state/rule-events.jsonl | jq .
# Built-in aggregated report:
python -m scripts.telemetry.report monthly
```

## Disable telemetry entirely

```bash
export AIPLAYBOOK_TRACING_DISABLED=1
```

`init_tracing()` returns the no-op tracer, no OTel imports happen, no Langfuse client is constructed. JSONL writes continue (the disable flag is OTel-scoped on purpose — local audit is cheap and doesn't risk any network call).

## Implementation notes

- **Explicit `Langfuse(tracer_provider=...)`** — `init_tracing` builds its own `TracerProvider` and passes it explicitly so the Langfuse SDK attaches its processor to **our** provider, not whatever happens to be installed as the process-global. This means other libraries that touch `opentelemetry.trace.set_tracer_provider` after we initialise cannot break the dual export.
- **`trace_emit.span(...)`** still uses the global provider via `trace.get_tracer("ai-playbook")`. `init_tracing` therefore sets the global as well — the two patterns coexist on purpose.
- **Both transports are independent**: a failure in the OTel side (network, missing dependency, exception in a hook) never blocks the JSONL write, and vice versa. The contract is that telemetry never alters a rule's exit code.
