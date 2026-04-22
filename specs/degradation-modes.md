# degradation-modes.md

> **Status**: v1.0.0. Supersedes T02-pre stub. Populated in T04b.

Degradation is **observed and announced, never guessed**. Every playbook-driven agent exposes a degradation state to the rest of the stack via OTel span attributes, and the dashboard (T19) surfaces the current state. This spec defines the state enum, the transitions, the circuit-breaker windows, and how degradation composes with the model-routing matrix.

## 1. States (canonical enum)

| State | Meaning | Behavior contract |
|---|---|---|
| `HEALTHY` | All primary providers for the current task class are responsive within thresholds. | Normal operation. No user-visible warning. `ai_playbook.degradation.state="HEALTHY"` still emitted on every span. |
| `DEGRADED_CAPACITY` | Primary model is rate-limited, queueing, or exceeding the P95 latency baseline. Quality is assumed unchanged. | Router fails over to the next element in the chain per `model-routing.md`. One-step fallback is silent; deeper fallback triggers `DEGRADED_QUALITY`. |
| `DEGRADED_QUALITY` | Router has fallen back ≥2 steps, or has demoted to a model whose tier is lower than the primary's tier for this task class. | User-visible notification per `notification-policy.md`. Trace tags `quality=degraded` on all subsequent spans in the session until either restoration or session end. Retrospective (T14i) lists the affected task classes. |
| `DEGRADED_CONTEXT` | Memory system (Hindsight MCP, or whatever the active memory plane is) is unreachable or heartbeat-dead. | Agent warns at session start: "Memory is unavailable — I will not recall prior sessions." Writes are queued locally and reconciled on recovery. This state is **orthogonal** to the model-capacity states: a session can be `DEGRADED_CONTEXT` + `HEALTHY` simultaneously. |
| `OFFLINE` | No remote LLM provider reachable at all (every primary and every chained fallback has failed). | Agent refuses net-dependent tasks with a clear, actionable error (`error-message-standard.md`). Local-only tools (Ollama, shell, read-only file ops) remain available. Task classes whose chain does not terminate in a local model block entirely. |

State enum is additive — new states may be added in future versions under `additionalProperties: true`. Consumers MUST tolerate an unknown state by treating it as `DEGRADED_CAPACITY` (conservative default) and emitting a warning.

## 2. Transition triggers and thresholds

Thresholds are deliberately conservative; the goal is to avoid thrashing. All windows are **rolling**, not fixed calendar buckets.

| From → To | Trigger | Threshold |
|---|---|---|
| `HEALTHY` → `DEGRADED_CAPACITY` | Error rate on primary (5xx, rate-limit, or timeout past per-call budget) | **≥3 errors in a 5-minute rolling window** on the same primary for the same task class. |
| `HEALTHY` → `DEGRADED_CAPACITY` | P95 latency on primary vs. baseline | **P95 > 2× rolling 1-hour baseline**, sustained for 5 minutes. Baseline is recomputed continuously; no hardcoded ms numbers. |
| `HEALTHY` → `DEGRADED_CAPACITY` | Provider-reported availability | Provider sends a `Retry-After` header, `x-ratelimit-remaining: 0`, or an explicit "degraded" status in its health endpoint. Single signal is enough. |
| `DEGRADED_CAPACITY` → `DEGRADED_QUALITY` | Fallback depth | Router reports `ai_playbook.routing.fallback_depth ≥ 2` OR a demotion to a lower-tier task class (e.g., Opus-tier task served by a Sonnet-tier model). |
| Any → `DEGRADED_CONTEXT` | Heartbeat miss on memory plane (Hindsight MCP) | **2 consecutive heartbeat misses** at the memory client's configured interval, OR an explicit `connection refused` / DNS failure. |
| Any → `OFFLINE` | Total provider exhaustion | Every element in the chain for every active task class has failed within the last 2 minutes. |
| `DEGRADED_*` → `HEALTHY` | Probe success | A single successful probe request to the primary, with latency within baseline, after the minimum cool-down has elapsed. See §3. |
| `OFFLINE` → `DEGRADED_*` | Probe success to any primary | First probe that completes successfully moves us to `DEGRADED_CAPACITY` (not directly to `HEALTHY`; we require sustained healthy traffic before clearing entirely). |

Thresholds are tunable via env vars (prefixed `AIPLAYBOOK_DEGRADATION_*`) — enumerated in `env-vars.md` as they land. Defaults live in `scripts/degradation.py`.

## 3. Circuit-breaker windows

When a transition out of `HEALTHY` fires, the circuit breaker prevents thrashing:

- **Minimum cool-down: 30 seconds.** After opening the breaker on a primary, do not probe it again for at least 30s, regardless of how tempting. A `Retry-After: N` header from the provider overrides this floor when `N > 30`.
- **Exponential backoff, capped at 5 minutes.** Cool-downs double on each consecutive failed probe (30s, 60s, 120s, 240s, 300s — capped there). Reset the counter on first success.
- **Probe is a single, low-cost request.** A ping-style call (e.g., a 10-token classification for Haiku/Flash tier primaries, or a 1-token completion for larger ones). Never use a probe to "get real work done" — that couples recovery detection to a user-visible turn and causes flapping.
- **State restoration requires sustained success.** Move out of `DEGRADED_QUALITY` to `HEALTHY` only after **2 consecutive successful real calls** (not just probes) within the normal latency baseline.

## 4. Composition with model routing

Degradation and routing are **tightly coupled but separate concerns**. The rule of composition:

1. **`DEGRADED_CAPACITY` on primary** ⇒ router consults the fallback chain from `model-routing.md`. The router does this per-call; the degradation state just removes the primary from consideration until the breaker closes.
2. **`DEGRADED_QUALITY`** ⇒ the router continues to serve from the chain, but callers that requested an Opus-tier task class are notified and may choose to queue the work instead of accepting the demotion. The retrospective lists every task class that ran in this state.
3. **Whole provider is `OFFLINE`** (not just one model on that provider) ⇒ the task class itself is demoted one tier **only if the chain explicitly contains a lower-tier model**. Example: an Architecture-proposal task whose chain is `Opus → Gemini-pro-thinking → Sonnet` may serve from Sonnet with a visible `DEGRADED_QUALITY` warning. A Retrospective task whose chain terminates with "block" simply blocks — the retro is queued.
4. **Automatic demotion is always visible.** Silent quality drops are the single worst failure mode, because they break trust with the user. Every demotion produces a notification and a span.
5. **`DEGRADED_CONTEXT`** does not trigger any routing change. It changes memory behavior only.

## 5. OpenTelemetry attributes

Every agent turn emits at minimum:

| Attribute | Type | Semantics |
|---|---|---|
| `ai_playbook.degradation.state` | string enum | One of `HEALTHY`, `DEGRADED_CAPACITY`, `DEGRADED_QUALITY`, `DEGRADED_CONTEXT`, `OFFLINE`. |
| `ai_playbook.degradation.reason` | string | Present when state ≠ `HEALTHY`. Short enum-ish string: `error_rate`, `latency`, `provider_signal`, `fallback_depth`, `memory_unreachable`, `total_exhaustion`. |
| `ai_playbook.degradation.started_at` | RFC3339 timestamp | When the current non-healthy state began. Absent in `HEALTHY`. |
| `ai_playbook.degradation.ttl_estimate` | int seconds | Best-guess cool-down remaining. If provider sent `Retry-After`, use that value; otherwise, the next exponential-backoff tick. `-1` if unknown. |

These attributes compose with the `gen_ai.*` and `ai_playbook.routing.*` attributes from `model-routing.md` — a single span carries both families.

## 6. Dashboard surface (T19)

The dashboard (scoped in T19) surfaces:

- Current top-level degradation state, color-coded (green/yellow/orange/red/grey).
- The set of task classes in `DEGRADED_QUALITY`, with their most recent `reason`.
- Open circuit breakers with remaining `ttl_estimate`.
- A 24-hour sparkline per primary of `fallback_depth` so operators can spot quiet chronic degradation.

This spec does not define the widget implementation — it defines the **contract** the widget reads from. T19 owns rendering.

## 7. Break-glass interaction

A user can force a specific model in the face of active degradation using:

```
--force-model=<id> --force-with-reason="accept quality drop, have to ship"
```

Semantics:

- The router honors the forced model; the breaker's cool-down does not block it (this is the point of break-glass).
- The degradation state **does not flip to HEALTHY** because of a forced call; the forced call is not a probe.
- The override writes a `break-glass.md`-compliant audit entry, and the retrospective (T14i) lists every force event in its window.
- Forcing a model that is **completely unreachable** (hard DNS failure, 401, etc.) still fails — break-glass overrides policy, not physics.

## See also

- [model-routing.md](model-routing.md) — the fallback chains this state machine composes with.
- [notification-policy.md](notification-policy.md) — how `DEGRADED_QUALITY` notifications reach the user.
- [break-glass.md](break-glass.md) — `--force-with-reason` contract referenced in §7.
- [error-message-standard.md](error-message-standard.md) — the error shape returned when `OFFLINE` blocks a task.
- [retrospective-cadence.md](retrospective-cadence.md) — T14i surfaces overrides and prolonged degradation windows.
