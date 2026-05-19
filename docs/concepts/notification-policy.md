# notification-policy.md

> **Status**: v1.0.0.

Canonical policy for every user-visible notification a playbook-driven agent or script emits. Levels are abstract; channels are pluggable. The contract protects Arturo's (and future team devs') attention budget and keeps the audit trail uniform across projects.

---

## 1. Levels

Exactly four levels. Any notification emitted by a playbook-driven actor MUST declare one.

| Level | Definition | Who sees it | Example trigger | Default channel |
|---|---|---|---|---|
| `silent` | Successful routine signal; for machine audit only. | Trace/log only (OTel span, JSONL append). No human surface. | `qa.verdict.approved`, tool call ok. | OTel backend, local JSONL. |
| `info` | Normal progress worth recording but not interrupting. | Dashboard card + daily digest. | `qa.verdict.issues_found`, new OpenSpec change proposed, FEEDBACK.md bullet appended. | Dashboard (T19) + `reports/digest-<YYYY-MM-DD>.md`. |
| `warn` | Abnormal but recoverable; action within 24h. | Dashboard + Slack/Telegram (Arturo personal initially). | `break-glass.applied`, `degradation.transition.DEGRADED_QUALITY`, `lifecycle_check.systemic`. | Dashboard + Telegram chat @arturo-playbook. |
| `error` | Safety / correctness / data loss; action immediate. | Dashboard + Slack/Telegram + (future) on-call page. | `secrets_scan.match`, `degradation.transition.OFFLINE`, `credential_exposure` detected. | Dashboard + Telegram + (T22) PagerDuty. |

`silent` is the default. If you are adding a notification, you must justify why it beats the noise floor. "It might be useful someday" is not a justification.

### 1.1 Level escalation

A notification's level is set at emit-time and **does not escalate automatically**. If an `info` event repeats ≥10 times in a 5-minute window, the emit helper is supposed to suppress further instances and emit a single `warn`-level `notification.burst` summary event. Burst suppression is implemented in the helper, not by humans.

---

## 2. Rules

- **Rate limit.** No `info` or `warn` bursts greater than **5 per minute per actor**. The helper short-circuits excess and records the drop count as a single `info` summary event.
- **Trace ID correlation.** Every `warn` and `error` notification MUST carry the emitting OTel `trace_id` so the recipient can jump directly to the trace. `info` SHOULD; `silent` always does.
- **Actor identity.** Every notification carries `ai_playbook.notification.actor` — the git `user.email` or the agent UUIDv7 that emitted it. Retro aggregates use this field; see §5.
- **Structured payload first.** Notifications are emitted as JSON envelopes and rendered to human-readable text by the channel adapter, not formatted ad hoc in the emitting script. Shape:
  ```json
  {
    "level": "warn",
    "event": "break-glass.applied",
    "trace_id": "0196f34a-8c7e-7b2f-9d01-3e8a9b4c2f11",
    "actor": "23051550+Wizarck@users.noreply.github.com",
    "project": "acme-shop",
    "detail": {"gate": "schema_validate", "reason": "bootstrapping, submodule missing"},
    "ts": "2026-04-23T14:05:12+02:00"
  }
  ```
- **English only.** Notifications are machine-parseable first; localization happens at the UI layer, not in the emitting payload.
- **No secrets.** A notification payload MUST NOT include any value that `secrets_scan.py` would flag. Redaction happens in the helper before transport.

---

## 3. Channels

Channels are an **abstract surface**. This spec defines the contract; concrete wiring (webhooks, chat IDs) lives outside the repo.

### 3.1 Initial channels (v1.0.0)

| Channel | Handles | Transport | State |
|---|---|---|---|
| OTel backend | `silent`, `info`, `warn`, `error` | OTel Collector → Tempo/Langfuse | Always on (subject to `degradation-modes.md`). |
| Local JSONL | `silent`, `info`, `warn`, `error` | Append to `.ai-playbook/notifications.jsonl` (gitignored) | Always on. Diagnostic surface for retros. |
| Dashboard | `info`, `warn`, `error` | Dashboard widget (T19) queries OTel backend | Lands T19. |
| Daily digest | `info` | Markdown file at `reports/digest-<YYYY-MM-DD>.md` | Lands alongside T19. |
| Telegram (personal) | `warn`, `error` | Bot → chat @arturo-playbook | Arturo only at v1; team channels lands T22. |
| Slack (team) | `warn`, `error` | Webhook → `#playbook-ops` | Lands T22. |
| On-call page (PagerDuty or OpsGenie) | `error` | Webhook | Lands T22 with SLO contract. |

### 3.2 Contract for new channels

A channel adapter lives under `scripts/notifications/<name>.py` and MUST:

1. Accept the JSON envelope above unmodified.
2. Filter by level (configured per-channel in env vars, prefix `AIPLAYBOOK_NOTIFY_`).
3. Apply channel-side rate limiting (on top of the emit helper's global cap).
4. Fail open — a broken channel MUST NOT block the emit. Log the channel failure at `error` to JSONL so the retro catches it.
5. Never hardcode webhooks, chat IDs, tokens in source. Read from env or SOPS-encrypted secrets (see [break-glass.md](break-glass.md) and the secrets strategy).

Channel selection is configuration, never code: flip `AIPLAYBOOK_NOTIFY_TELEGRAM=on` to enable, off to disable. The default for a fresh consumer is `silent`/`info` to JSONL + OTel only. `warn`/`error` surfaces require explicit opt-in.

---

## 4. Per-event policy

Canonical events and their required level. New events added via RFC.

| Event | Level | Notes |
|---|---|---|
| `qa.verdict.approved` | `silent` | Trace only. A clean approval is not news. |
| `qa.verdict.issues_found` | `info` | Dashboard surfaces per-iter count; retro reads from JSONL. |
| `qa.verdict.clarification_needed` | `warn` | Blocks a track; needs human attention within 24h. |
| `break-glass.applied` | `warn` | Per [break-glass.md](break-glass.md) §4; rate-limited globally at 5/min. |
| `secrets_scan.match` | `error` | Per [agentic-failures.md](agentic-failures.md) §2.11. `OVERRIDE: none`. |
| `degradation.transition.DEGRADED_CAPACITY` | `silent` | Routine fallback; one-step. |
| `degradation.transition.DEGRADED_QUALITY` | `warn` | User-visible per [degradation-modes.md](degradation-modes.md) §1. |
| `degradation.transition.DEGRADED_CONTEXT` | `warn` | Memory plane unreachable; agents warn at session start. |
| `degradation.transition.OFFLINE` | `error` | Provider exhaustion. |
| `lifecycle_check.systemic` | `warn` | Monthly script flags a gate overridden ≥3× in 30 days. |
| `feedback.bullet_appended` | `info` | Weekly retro triages. |
| `openspec.archive.completed` | `info` | Triggers post-archive retro template. |
| `agentic_failure.detected` | Severity-mapped | `S1` → `error`, `S2` → `warn`, `S3`/`S4` → `info`. |
| `notification.burst` | `warn` | Emitted by the helper when rate limit fires. |

Events not in this table emit `silent` by default. Adding a row requires an RFC.

---

## 5. Retro surface

`scripts/lifecycle_check.py` queries the notifications log per actor per week and produces:

- Count per level per actor per project per week. Anomalies (±2σ from the 4-week rolling baseline) flagged in the monthly retro.
- Top-N `event` types by volume — a chronic `info` spammer is usually a miscalibrated emit site, fix the emitter.
- Top-N `warn`/`error` events unresolved >24h/1h respectively — flagged as SLO breaches once T22 SLOs land.

Retros are cross-referenced from [retrospective-cadence.md](retrospective-cadence.md) §3 (monthly output).

---

## 6. Cross-references

- [error-message-standard.md](error-message-standard.md) — notifications that carry an error payload use the WHY/WHERE/FIX/OVERRIDE shape inside `detail.error`.
- [break-glass.md](break-glass.md) §4 — every `OVERRIDE APPLIED` on an `error`-shape gate emits `warn`-level `break-glass.applied`.
- [verdict-contract.md](verdict-contract.md) — verdict events (`qa.verdict.*`) map to levels per §4 above.
- [degradation-modes.md](degradation-modes.md) — every degradation state transition maps to an event in §4.
- [agentic-failures.md](agentic-failures.md) — detected failures notify per severity (S1→error, S2→warn).
- [retrospective-cadence.md](retrospective-cadence.md) — where retro aggregates are produced.
