# notification-policy.md

> **Status**: stub, v0.1.0. Populated in **T14e**.

## Levels

| Level | Who sees it | Example |
|---|---|---|
| `silent` | Trace/log only. | Successful routine tool call. |
| `info` | Dashboard + daily digest. | New OpenSpec change proposed. |
| `warn` | Dashboard + Slack/Telegram (Arturo). | Degradation triggered; break-glass used. |
| `error` | Dashboard + Slack/Telegram + on-call (future). | CI drift-check failed; secret leaked. |

## Rules

- Default level is `silent` — if you add a notification, justify why it beats the noise floor.
- `warn` and `error` carry the OTel `trace_id` so the recipient can jump directly to the trace.
- No `info` or `warn` bursts > 5/min per actor — rate-limit in the emit helper.

## Populated in T14e

Concrete channels (Telegram chat IDs, Slack webhook), rate-limiter implementation, and the retro query surfacing notifications-per-week-per-actor.
