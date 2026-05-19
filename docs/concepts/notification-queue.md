---
schema: concept/v1
slug: notification-queue
title: Notification Queue
summary: |
  Contract for the JSONL notification queue + email transport + durable
  SQLite-backed retry queue used by every zero-touch playbook automation. This
  spec realises the *shape* of a notification envelope and the *transports*
  that ship it; notification-policy.md realises the
last_validated: "2026-05-19"
---

# Notification Queue

Contract for the JSONL notification queue + email transport + durable
SQLite-backed retry queue used by every zero-touch playbook automation. This
spec realises the *shape* of a notification envelope and the *transports*
that ship it; [notification-policy.md](notification-policy.md) realises the
*policy* (per-event severity matrix, channels).

### Layer overview

```
notify(event, severity, summary, ...)
   │
   ├─► §3 JSONL append  (always; source-of-truth audit)
   │
   ├─► severity ∈ {warn, error}:
   │     ┌──────────────────────────────────────────────────┐
   │     │ §8 Durable queue   (when consumer opts in via    │
   │     │   CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED=1 AND        │
   │     │   `notifications.queue` package importable —     │
   │     │   consumer-d only at v1)                         │
   │     │   → SQLite enqueue → worker → Telegram/WhatsApp  │
   │     └──────────────────────────────────────────────────┘
   │     ┌──────────────────────────────────────────────────┐
   │     │ §6 SMTP fallback  (queue disabled OR             │
   │     │   not vendored — consumer-b, consumer-c,      │
   │     │   consumer-e, livekit, dev laptops)            │
   │     └──────────────────────────────────────────────────┘
   │
   └─► severity ∈ {silent, info}: JSONL only.
```

The two §6 / §8 paths are mutually exclusive per emission — when the queue
claims a row, SMTP is skipped to avoid double delivery.

---

## 1. Purpose

Every playbook automation (currently `issue_sync.py`, `release_cut.py`;
future `drift_detector.py`, `break_glass.py` observer, `lifecycle_check.py`
aggregator) emits a structured notification **at every step**. The notifications
are written to a single JSONL file per consumer repo so:

- The dashboard (Subagent B, `/api/notifications`) can stream them via SSE.
- The retro (`lifecycle_check.py`) can aggregate counts.
- Email transport can surface `warn` / `error` severities to the maintainer.
- No script ever has to "remember" whether it already notified humans —
  the dedup + rate-limit logic lives in one helper.

## 2. Entry shape

Every line is a self-contained JSON object (no arrays). Keys:

| Field | Type | Meaning |
|---|---|---|
| `ts` | ISO 8601 with tz | UTC-anchored emission timestamp. |
| `event` | str | `<emitter>.<verb>` convention (see §4). |
| `severity` | enum | `silent` \| `info` \| `warn` \| `error`. |
| `summary` | str | One-line human-readable. Fits in a dashboard card. |
| `detail` | str | Optional multi-paragraph detail; can be empty. |
| `attrs` | object | Structured payload (change_id, tracker_id, fixVersion…). |
| `trace_id` | str \| null | OTel correlation id (must be present for `warn`/`error`). |
| `actor` | str | git `user.email` or agent UUIDv7 — identity field. |

Example:

```json
{
  "ts": "2026-04-23T14:30:00+00:00",
  "event": "issue_sync.created",
  "severity": "info",
  "summary": "Created TRATT-42 for module-1-ingredients-impl",
  "detail": "",
  "attrs": {"tracker_id": "TRATT-42", "change_id": "module-1-ingredients-impl", "project": "consumer-c"},
  "trace_id": "0196f34a8c7e7b2f9d013e8a9b4c2f11",
  "actor": "23051550+Wizarck@users.noreply.github.com"
}
```

No secrets, no credentials, no raw API payloads. `scripts/secrets_scan.py`
sanitisation applies to `summary` / `detail` / `attrs.*` string values before
write. (Sanitisation is wired in a follow-up; today the emitters are careful
at source.)

## 3. Path resolution

Resolution order for the JSONL file:

1. `AIPLAYBOOK_NOTIFICATIONS_FILE` env var (absolute path).
2. `<repo-root>/.ai-playbook/notifications.jsonl` where repo-root is the nearest
   ancestor with `.git/` or `pyproject.toml`.

The file is **gitignored**. The dashboard consumer mounts `.ai-playbook/` via
the same path and streams the tail.

## 4. Event-name convention

`<emitter>.<verb>`. The emitter is the script basename without `.py`. The verb
is lowercase-snake. Plural verbs are forbidden (use one notification per item).

Canonical emitters registered as of v1.0.0:

| Emitter | Verbs |
|---|---|
| `notify` | `burst` (rate-limit summary), `failed` (helper self-failure) |
| `issue_sync` | `scan_start`, `skipped`, `created`, `failed`, `complete`, `queue_dropped` |
| `release_cut` | `start`, `changes_collected`, `github_released`, `jira_fixversion_created`, `failed`, `complete` |
| `drift_detector` | `heartbeat`, `drift_found`, `drift_cleared` (Subagent B / future) |
| `break_glass` | `applied`, `refused` (future — from `scripts/_break_glass.py` wiring) |
| `lifecycle_check` | `systemic`, `orphan`, `retro_ready` (future) |

A new emitter or verb lands via RFC; adding it requires updating this table AND
[notification-policy.md](notification-policy.md) §4 with the default severity.

## 5. Severity mapping

Inherits [notification-policy.md](notification-policy.md) §1. Shortcut table:

| Severity | JSONL? | Email by default? | Dashboard? |
|---|---|---|---|
| `silent` | yes | no | no |
| `info` | yes | no (unless `AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY=info`) | yes |
| `warn` | yes | yes (threshold default `warn`) | yes |
| `error` | yes | yes | yes (highlighted) |

Rate limits apply at the emitter (5/min/event+actor for `info`). When rate limit
triggers, a single `notification.burst` (severity `warn`) summary is emitted
that includes the drop count so the retro sees it.

Dedup window: 60s. Same `event` + `summary` + `trace_id` within 60s collapses
to a single record.

## 6. SMTP transport

All SMTP env vars must be set to enable email; if any required var is missing,
email is silently disabled and only JSONL is written.

| Var | Default | Required |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | no |
| `SMTP_PORT` | `587` | no |
| `SMTP_USER` | `$GIT_AUTHOR_EMAIL` | yes |
| `SMTP_PASSWORD` | — (SOPS-decrypted) | yes |
| `AIPLAYBOOK_NOTIFICATIONS_FROM` | `$SMTP_USER` | no |
| `AIPLAYBOOK_NOTIFICATIONS_TO` | `$SMTP_USER` | no |
| `AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY` | `warn` | no |

Email format:

- **Subject**: `[ai-playbook] <SEVERITY-UPPER> <event> — <summary-first-60chars>`.
- **Body**: `Severity`, `Time`, `Event`, `Actor`, `Summary`, optional `Detail`,
  pretty-JSON `Attrs`, and a footer explaining
  `AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY=never` turns emails off.

Failures in email transport must not raise to the caller — they're logged as
`ai_playbook.notify.failed=1` JSONL breadcrumbs and stderr warnings.

## 7. Dashboard consumer (`/api/notifications`)

Owned by Subagent B (consumer-d). Contract the dashboard implements:

- Tails the JSONL file and broadcasts each new line over SSE to subscribers.
- Filters by severity (`?severity=warn,error`) and by `actor` (`?actor=<email>`).
- Retains in-memory the last 500 events for the bell-icon badge; older events
  are paginated from the file directly.
- Never modifies the file (append-only).

Subagent B is responsible for authentication, CORS, and the UI. This repo owns
the file-format guarantees.

## 8. Durable queue layer (Phase 5 Change B — opt-in, consumer-d)

The JSONL+SMTP layers above guarantee audit but NOT delivery: if Telegram is
down for 30 s during a `request_approval` emission, the user never sees the
message and the workflow's poll loop times out without ever asking the human.
Phase 5 Change B (`add-durable-notification-queue`) closes this gap with a
SQLite-backed retry layer that wraps the channel adapters and replays failed
sends until they land or the TTL expires.

### Activation

Two AND-gated conditions:

1. `CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED=1` is set in the consumer's environment
   (default: unset → legacy SMTP path).
2. The consumer-side Python package `notifications.queue` is importable.
   Today this means **only consumer-d** at v1 — the queue lives at
   `langgraph-aiops/notifications/` in that repo and is wired into
   `langgraph-aiops/watchdogs.py::run_continuous` as an `asyncio.Task`
   sibling to the watchdog loop.

When either condition is missing, `notify()` falls through to the legacy
SMTP path (§6) without raising. Other consumers (consumer-b, consumer-c,
consumer-e, livekit) are unaffected by this change.

### Storage

SQLite at `~/.consumer-d/state/notifications-queue.db` (host-writer pattern;
overridable via `CONSUMER_D_NOTIFICATIONS_DB`). Schema (full DDL in
`scripts/db/migrations/notifications-queue-001.sql`):

```sql
CREATE TABLE pending (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  envelope_json TEXT NOT NULL,    -- the §2 envelope shape verbatim
  channel TEXT NOT NULL,           -- "telegram" | "whatsapp" | "dashboard"
  severity TEXT NOT NULL,          -- "info" | "warn" | "error"
  created_at TIMESTAMP NOT NULL,
  next_retry_at TIMESTAMP NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  delivered_at TIMESTAMP,
  dropped_at TIMESTAMP,
  ttl_seconds INTEGER NOT NULL DEFAULT 86400  -- 24h default
);
CREATE INDEX idx_pending_due ON pending (next_retry_at)
    WHERE delivered_at IS NULL AND dropped_at IS NULL;
```

The `envelope_json` field stores the §2 shape verbatim — no field flattening,
no schema drift between queue rows and the JSONL audit log.

### Worker

A single `asyncio.Task` (no multi-worker — D2.2). Polling cycle every 10 s:

1. `SELECT * FROM pending WHERE delivered_at IS NULL AND dropped_at IS NULL
   AND next_retry_at <= NOW() ORDER BY id LIMIT 50`.
2. For each row: dispatch to `channels.<channel>.send_envelope(envelope)`.
3. On success: `UPDATE pending SET delivered_at = NOW() WHERE id = ?`;
   emit `notification.delivered` (severity `silent`) to `events.jsonl`.
4. On failure: bump `attempt_count`, store `last_error`, recompute
   `next_retry_at` per the backoff schedule below; emit
   `notification.retry_scheduled` (severity `silent`).
5. If a row exceeds `ttl_seconds` past `created_at`, set `dropped_at = NOW()`
   and emit `notification.dropped` (severity `error`, includes the full
   envelope + `last_error`).

Disable the worker (e.g. for unit tests of just the watchdog) via
`CONSUMER_D_NOTIFICATIONS_WORKER_DISABLED=1`.

### Backoff schedule

Explicit, no improvisation:

| Attempt | Wait before retry |
|---|---|
| 1 | 30 s |
| 2 | 2 min |
| 3 | 10 min |
| 4 | 1 h |
| 5 | 6 h |
| 6+ | parked far in the future; `drop_expired()` reclaims at TTL boundary |

Cumulative wait through attempts 1-5 ≈ 7 h 42 min — comfortably inside the
24 h default TTL, so each row gets at least 5 delivery attempts before drop.

### Channel routing

Per `notification-policy.md` §3.1 + Change B proposal:

- `silent` → JSONL only. Not enqueued.
- `info` → JSONL only (D2.5 — queue cost > delivery value at this severity).
  Not enqueued.
- `warn` → JSONL + queue → channel adapter (Telegram for Arturo at v1).
- `error` → JSONL + queue → channel adapter (Telegram + future PagerDuty).

`notify.py` selects the channel via `_QUEUE_CHANNEL_BY_SEVERITY` (default
`telegram` for warn/error). To target multiple channels, fan out at
the emitter — the queue does NOT auto-broadcast a single envelope to N
channels.

### MCP outbox tool

`langgraph-aiops/consumer-d_ops/tools.py::recent_undelivered_notifications(limit=10)`
exposes the pending rows as an MCP tool — used by the dashboard "outbox"
widget and by Hermes to answer "did anything fail to deliver?". Returns
`channel`, `severity`, `attempt_count`, `next_retry_at`, `last_error`, and a
trimmed `summary` for each pending envelope.

### Observability

Every queue state transition emits a `gen_ai.notification.<verb>` event to
`events.jsonl`:

| Event | Severity | When |
|---|---|---|
| `notification.enqueued` | `silent` | row inserted |
| `notification.delivered` | `silent` | row marked delivered |
| `notification.retry_scheduled` | `silent` | row marked failed; backoff reset |
| `notification.dropped` | `error` | row exceeded TTL; envelope included |

`scripts/telemetry/report.py (absorbed in Slice 6)` and the consumer-d dashboard already aggregate
`events.jsonl` — no new metrics infrastructure required.

### Restart survival

Container/process restart (`docker compose restart consumer-d-aiops`,
`systemctl restart`) must not lose pending rows. Validated by a unit test
that reimports `notifications.queue` after enqueue and verifies the row is
still readable from the SQLite file (host-writer pattern guarantees the file
outlives the container).

## 9. Retention

- JSONL file retained **180 days rolling**. Rotated weekly by the dashboard
  host (or `lifecycle_check.py --rotate-notifications` when invoked).
- Rotated files live at `.ai-playbook/notifications-<YYYY-WWW>.jsonl.gz`.
- Aggregated counts per severity per week are emitted as
  `lifecycle_check.notifications_rollup` events.

## 10. Cross-references

- [notification-policy.md](notification-policy.md) — severity matrix, per-event
  policy.
- [issue-tracking.md](issue-tracking.md) — defines `issue_sync.py` and
  `release_cut.py` events.
- [break-glass.md](../rules/break-glass.rule.md) — every `OVERRIDE APPLIED` on an `error` or
  higher-severity gate emits `warn` / `break_glass.applied`.
- [verdict-contract.md](../rules/verdict-contract.rule.md) — QA verdict events consume the
  same transport surface.
- [env-vars.md](env-vars.md) — canonical place for SMTP + notifications env
  vars; updated in lockstep with this spec.
