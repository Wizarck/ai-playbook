# notification-queue.md

> **Status**: v1.0.0. Populated in T25+.

Contract for the JSONL notification queue + email transport used by every
zero-touch playbook automation. This spec realises the *shape* of a
notification envelope; [notification-policy.md](notification-policy.md)
realises the *policy* (per-event severity matrix, channels).

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
| `trace_id` | str \| null | OTel correlation id (MUST be present for `warn`/`error`). |
| `actor` | str | git `user.email` or agent UUIDv7 — identity field. |

Example:

```json
{
  "ts": "2026-04-23T14:30:00+00:00",
  "event": "issue_sync.created",
  "severity": "info",
  "summary": "Created TRATT-42 for module-1-ingredients-impl",
  "detail": "",
  "attrs": {"tracker_id": "TRATT-42", "change_id": "module-1-ingredients-impl", "project": "openTrattOS"},
  "trace_id": "0196f34a8c7e7b2f9d013e8a9b4c2f11",
  "actor": "arturo6ramirez@gmail.com"
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

All SMTP env vars MUST be set to enable email; if any required var is missing,
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

Failures in email transport MUST NOT raise to the caller — they're logged as
`ai_playbook.notify.failed=1` JSONL breadcrumbs and stderr warnings.

## 7. Dashboard consumer (`/api/notifications`)

Owned by Subagent B (eligia-core). Contract the dashboard implements:

- Tails the JSONL file and broadcasts each new line over SSE to subscribers.
- Filters by severity (`?severity=warn,error`) and by `actor` (`?actor=<email>`).
- Retains in-memory the last 500 events for the bell-icon badge; older events
  are paginated from the file directly.
- Never modifies the file (append-only).

Subagent B is responsible for authentication, CORS, and the UI. This repo owns
the file-format guarantees.

## 8. Retention

- JSONL file retained **180 days rolling**. Rotated weekly by the dashboard
  host (or `lifecycle_check.py --rotate-notifications` when invoked).
- Rotated files live at `.ai-playbook/notifications-<YYYY-WWW>.jsonl.gz`.
- Aggregated counts per severity per week are emitted as
  `lifecycle_check.notifications_rollup` events.

## 9. Cross-references

- [notification-policy.md](notification-policy.md) — severity matrix, per-event
  policy.
- [issue-tracking.md](issue-tracking.md) — defines `issue_sync.py` and
  `release_cut.py` events.
- [break-glass.md](break-glass.md) — every `OVERRIDE APPLIED` on an `error` or
  higher-severity gate emits `warn` / `break_glass.applied`.
- [verdict-contract.md](verdict-contract.md) — QA verdict events consume the
  same transport surface.
- [env-vars.md](env-vars.md) — canonical place for SMTP + notifications env
  vars; updated in lockstep with this spec.
