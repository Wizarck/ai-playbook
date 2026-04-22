# degradation-modes.md

> **Status**: stub, v0.1.0. Populated in **T04** with the full degradation matrix and UI/telemetry contract.

## States (canonical)

| State | Meaning | Behavior |
|---|---|---|
| `HEALTHY` | All primary providers responsive. | Normal operation. |
| `DEGRADED_CAPACITY` | Primary model rate-limited or slow. | Fail-over to secondary per `model-routing.md`. |
| `DEGRADED_QUALITY` | Fallback model used; quality signaled. | UI + trace tag `quality=degraded`. |
| `DEGRADED_CONTEXT` | Memory system (Hindsight) unreachable. | Agent warns at session start; writes queue locally. |
| `OFFLINE` | No provider reachable. | Agent refuses net tasks; local tools only. |

## Transitions

Degradation is observed and announced, not guessed. A provider latency or error rate that exceeds threshold (T04) triggers a state change that is emitted as an OTel span attribute and surfaced in the dashboard (T19).

## Populated in T04

Threshold numerics, provider-specific signals (OpenRouter vs direct), circuit-breaker windows, and how degradation composes with the model routing matrix.
