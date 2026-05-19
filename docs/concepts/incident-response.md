---
schema: concept/v1
slug: incident-response
title: Incident Response
summary: |
  Incident Response (IR) is the contract that coordinates humans and tooling
  during a user-visible outage or a data-corruption event. This spec is the
  coordination layer; per-service "how do I fix Hermes" content stays in
  service-scoped runbooks (see §8). Every section below is…
last_validated: "2026-05-19"
---

# Incident Response

Incident Response (IR) is the contract that coordinates humans and tooling during a user-visible outage or a data-corruption event. This spec is the **coordination layer**; per-service "how do I fix Hermes" content stays in service-scoped runbooks (see §8). Every section below is something a 3am responder needs and a service-level runbook does not provide.

---

## 1. Scope

A user-visible outage or a data-corruption event on a service running under playbook-driven infra. As of v1.0.0, in-scope services for the canonical consumer (consumer-d):

- **Hermes** — notification/egress gateway.
- **Paperclip** — attachment/issue processor.
- **Hindsight** — memory MCP. Data-corruption class: a bad retain corrupts subsequent recalls.
- **LiteLLM** — model gateway (per [model-routing.md](model-routing.md)).
- **Dashboard** — observability UI.

Out of scope: routine local dev glitches, flaky tests, CI hiccups that do not affect a running service. Those live in service-scoped runbooks. **An incident is by definition observable from outside the box.**

---

## 2. Trigger event definition (machine-checkable)

IR flips from `wired-pending-trigger` to `active` on the **first** of any of:

- **First paying SaaS customer.** Detection: an entry in `consumers.yaml` (per-consumer file at consumer-repo root) with `paying_tier: <enterprise|smb|other>` AND `sla_signed: <iso-date>` set within the last 30 days. Surfaced by [`scripts/telemetry/report.py (absorbed in Slice 6)`](../../scripts/telemetry/report.py (absorbed in Slice 6)) check `first_paying_client_detected`. State stored in `~/.ai-playbook/state/triggers.json` to avoid double-fire on subsequent runs.
- **First non-Arturo operator.** Detection: a second entry under `consumers.yaml` with `oncall_eligible: true`. Treated as a soft trigger — flips on-call shape from "solo" to "family-of-3" path (§4) but leaves IR `active` only after the maintainer manually flips `enforcement-status.md`.
- **First confirmed security incident.** Definition: confirmed unauthorised access, confirmed secret leak outside the contributor's own environment, confirmed prod data exfiltration. No automated detection — declared by Arturo (or successor) via `secrets_scan.py` exit ≥ 1 + manual confirmation. Forces full activation regardless of customer status.

**Activation is mechanical, not editorial.** When the lifecycle detector fires, `enforcement-status.md` row flips `wired-pending-trigger` → ✅ in the same PR that retires the trigger condition (e.g. the PR that adds the `paying_tier` row). See [enforcement-status.md](enforcement-status.md) row.

---

## 3. Severity matrix + MTTR targets

| Sev | Definition | Detection lead time | MTTR target | Post-mortem |
|---|---|---|---|---|
| **S1** | User-visible total outage OR confirmed data corruption OR confirmed security incident. | ≤ 2 min (probe) | ≤ 30 min to mitigation; ≤ 4 h to durable fix. | Mandatory ≤ 7 days. |
| **S2** | Partial degradation (one service down, fallbacks holding) OR non-blocking data integrity warning OR imminent capacity exhaustion. | ≤ 5 min | ≤ 2 h to mitigation; ≤ 24 h to durable fix. | Optional; gotcha entry mandatory. |
| **S3** | Performance regression OR rate-limit cascade OR third-party degraded but recovering. | ≤ 15 min | ≤ 1 business day. | None; incident note in `incidents.jsonl`. |
| **S4** | Cosmetic / observability-only / non-customer-affecting. | When noticed. | Best-effort. | None. |

MTTR clock starts at first probe failure (§4 detection signals) and stops at "responder confirms steady state" (`incidents.jsonl` event with `state: resolved`).

---

## 4. Scenario table (S1–S4 starter set)

Eight concrete scenarios across availability / data / security / capacity. Each has a detection signal (machine-checkable when possible), an immediate action ≤ 5 min, an escalation chain (solo today; family-of-3 path documented in §5), and the post-incident artefact required.

| # | Scenario | Sev | Detection signal | Immediate action (≤ 5 min) | Escalation | Artefact required |
|---|---|---|---|---|---|---|
| 1 | **VPS unreachable** | S1 | Uptime-Kuma probe failed ×3 OR SSH timeout > 30s. | SSH from secondary device. If unreachable, check Hetzner console + `journalctl -p err -n200`. | Solo (Arturo). | Post-mortem if downtime > 15 min. Runbook: [runbook-vps-down.md](../runbooks/runbook-vps-down.md). |
| 2 | **Hindsight DB corruption** | S1 | `_hindsight.py::HttpResult.reason == "degraded:retain_failed"` rate > 5%/min in `events.jsonl`. | Stop retain workers (`kubectl scale deploy/hindsight --replicas=0`). Snapshot DB to `/opt/consumer-d/backups/hindsight-<ts>.db`. Replay from JSONL queue. | Solo. | Post-mortem mandatory (data integrity class). Runbook: [runbook-db-corruption.md](../runbooks/runbook-db-corruption.md). |
| 3 | **Secrets leak in commit** | S1 | `secrets_scan.py` post-push CI fail OR external report (vendor email, GH advisory). | Rotate every leaked credential within 1h (per [rotate-secrets.md](../runbooks/rotate-secrets.md)). Force-push history rewrite. File CISA-style note. | Solo today; legal notify if customer data implicated. | Security post-mortem ≤ 48h. Runbook: [runbook-secrets-leak-containment.md](../runbooks/runbook-secrets-leak-containment.md). |
| 4 | **Container OOM cascade** | S2 | Docker restart count > 3 in 5 min for any service (Docker stats). | Identify culprit via `docker stats --no-stream`. Either bump memory limit + recreate OR roll back the deploy that triggered it. | Solo. | Gotcha entry minimum. |
| 5 | **Certificate expiry imminent** | S2 | Caddy probe reports any cert with `< 7d to expire`. Surfaced by Uptime-Kuma cert-monitor or `caddy validate` cron. | Trigger Caddy reload to fetch fresh ACME (`docker exec caddy caddy reload --config /etc/caddy/Caddyfile`). | Solo. | Gotcha entry. |
| 6 | **Third-party LLM provider outage** | S2 | LiteLLM proxy logs `5xx` rate > 10%/min for one provider for ≥ 3 min. | Verify with provider status page. If confirmed, fallback fires automatically per [model-routing.md](model-routing.md) §3 fallback chain. Confirm via `scripts/_llm.py` smoke ping. | Solo. | Incident note in `incidents.jsonl`. |
| 7 | **Rate-limit cascade (LLM)** | S3 | `429` rate > 20%/min from one provider sustained ≥ 5 min. | Identify caller via `consumer` metadata in `events.jsonl gen_ai.usage` events. Throttle or pause that consumer. Surface degraded banner via [degradation-modes.md](degradation-modes.md). | Solo. | Incident note. |
| 8 | **Capacity degradation (disk)** | S3 | VPS disk > 85% used. Surfaced by `vps_maintainer.py` probe (Phase 5 Change A). | Run `vps_maintainer.py --apply cleanup` (Helm CronJob; HITL gate per [apply-fix-contract.md](../rules/apply-fix-contract.rule.md)). | Solo. | Gotcha entry. |

Scenarios are starter set, not exhaustive. New scenarios land in this table in the same PR that introduces the detection rule. The simulator (`scripts/simulate_incident_response.py`) walks one scenario end-to-end as a smoke test.

---

## 5. On-call rotation contract

Three documented states. The system today is **solo**; family-of-3 and team-of-N paths are wired in spec only — they activate when the trigger fields populate.

### 5.1 Solo (current state)

- Primary responder: Arturo (`23051550+Wizarck@users.noreply.github.com`).
- Paging channel: Telegram bot (per [notification-policy.md](notification-policy.md) levels `error` and `warn`).
- Acknowledgement: explicit reply `/ack <incident-id>` to the Telegram alert OR an `incidents.jsonl` event with `state: acknowledged, responder: <email>`.
- Handoff: not applicable.
- Schedule export: none (no second person to schedule against).

### 5.2 Family-of-3 (activates when ≥ 2 entries in `consumers.yaml` have `oncall_eligible: true`)

- Primary + secondary on a weekly rotation (Sunday 18:00 UTC handoff).
- Secondary paged automatically if primary does not `/ack` within 10 min.
- Schedule lives in `consumers.yaml :: oncall_schedule` (array of week-anchored rotations).
- Tertiary (third person) is escalation-only: paged at 30 min if neither primary nor secondary acked.
- Handoff protocol: outgoing primary writes ≤ 5-line "in-flight" note in `runbooks/oncall-log.md` listing open incidents + open watchpoints.

### 5.3 Team-of-N (activates when ≥ 4 entries in `consumers.yaml` have `oncall_eligible: true`)

- Migrate to a real paging vendor (PagerDuty / Opsgenie). Until then, the family-of-3 protocol scales by adding rotations.
- Schedule export to OTel: `oncall.who_is_on_call{}` gauge updated by a CronJob reading `consumers.yaml`. Dashboard surfaces "current on-call" tile.
- Per D4.5 (§Decisions): no automated paging-vendor integration is wired today. The trigger to wire one is "≥ 4 oncall_eligible entries" — not earlier.

### Handoff non-negotiables (all states)

- Outgoing primary clears their alert-acknowledgement queue before handoff.
- Open incidents (any sev) get a one-line entry in `runbooks/oncall-log.md`.
- Any deferred runbook authoring (gotchas, post-mortems) gets an issue with the incoming primary as assignee.

---

## 6. 7-day post-mortem trigger (automated)

Detector lives in [`scripts/telemetry/report.py (absorbed in Slice 6)`](../../scripts/telemetry/report.py (absorbed in Slice 6)) under check `post_mortem_overdue`:

- Scans `incidents.jsonl` for entries with `severity: S1` OR `severity: S2`.
- For each, checks for a corresponding `runbooks/post-mortems/<incident-id>.md` (or per-consumer equivalent path).
- If absent and `now - incident_ts > 7 days`: emit `warn` notification per [notification-policy.md](notification-policy.md). Idempotent — same incident does not re-fire within the same calendar week (state in `~/.ai-playbook/state/triggers.json`).

S1 post-mortems are mandatory; the detector blocks the monthly retro from closing if any S1 is overdue. S2 post-mortems are optional; the detector emits `notice`, does not block.

Post-mortem template: `templates/post-mortem.md.tmpl`. Contract: [post-mortem.md](post-mortem.md).

---

## 7. Communication templates

### 7.1 Customer-facing status updates (3 levels)

Used when there is a public status page OR a customer Slack channel. Each level is a single Markdown block, self-contained.

**Investigating** — first acknowledgement, before mitigation:

```
[INVESTIGATING — <UTC HH:MM>] <service> degraded.
Symptoms: <one-line user-visible symptom>.
Impact: <who/what is affected; "limited" / "full" / "intermittent">.
Updates every <N> min. Ack: <responder>.
```

**Mitigated** — workaround in place, not yet root-caused:

```
[MITIGATED — <UTC HH:MM>] <service> restored to nominal via <one-line mitigation>.
Root cause investigation in progress. No further user impact expected.
Next update at <UTC HH:MM> OR on resolution.
```

**Resolved** — durable fix shipped:

```
[RESOLVED — <UTC HH:MM>] <service> stable.
Root cause: <one-line>. Fix: <one-line, link to PR if public>.
Duration: <HH:MM>. Post-mortem: <link or "due by <date>">.
```

### 7.2 Internal escalation messages

Used Telegram-internal or future Slack-internal. Concise, parseable.

**Initial page**:

```
🚨 S<n> — <service>. <signal that fired>. Trace: <link>. Ack with /ack <incident-id>.
```

**Escalation to secondary** (family-of-3+ only):

```
⚠ Primary <responder> not acked in 10m. Paging secondary. Incident: <incident-id>. Trace: <link>.
```

**Resolution**:

```
✅ <incident-id> resolved. Sev <n>. Duration <HH:MM>. Post-mortem due: <date or n/a>.
```

Templates are starter values — the canonical copy lives in `templates/incident-comms/` once a real S1 surfaces refinements.

---

## 8. Recovery runbook indices

The runbooks named below are stubs as of v1.0.0 (acceptance of OpenSpec change `complete-ir-and-model-migration-specs` requires they exist; content fleshes out as scenarios are encountered). All paths are playbook-relative.

| Scenario class | Runbook | Status |
|---|---|---|
| VPS unreachable | [runbook-vps-down.md](../runbooks/runbook-vps-down.md) | Stub v0.1.0 |
| DB corruption (Hindsight) | [runbook-db-corruption.md](../runbooks/runbook-db-corruption.md) | Stub v0.1.0 |
| Key rotation emergency | [runbook-key-rotation-emergency.md](../runbooks/runbook-key-rotation-emergency.md) | Stub v0.1.0 |
| Secrets leak containment | [runbook-secrets-leak-containment.md](../runbooks/runbook-secrets-leak-containment.md) | Stub v0.1.0 |

Per-consumer richer runbooks (consumer-specific topology, e.g. `consumer-d/runbooks/runbook-vps-disaster-recovery.md`) cross-link from these stubs; the playbook stub names what every consumer must address, the consumer runbook fills in their own infra.

---

## 9. Cross-references

- [post-mortem.md](post-mortem.md) — the artefact IR produces after S1 (mandatory) or S2 escalation (optional).
- [notification-policy.md](notification-policy.md) — what paging channels IR uses and at what level.
- [degradation-modes.md](degradation-modes.md) — announced-degradation path; a degraded service is not automatically an incident.
- [role-matrix.md](role-matrix.md) — who has rights to page, triage, declare recovered.
- [retrospective-cadence.md](retrospective-cadence.md) — retro surface for every S1/S2.
- [break-glass.md](../rules/break-glass.rule.md) — `--force-with-reason` usage during an incident is logged but not blocked.
- [apply-fix-contract.md](../rules/apply-fix-contract.rule.md) — HITL gate for any prod-mutating recovery action.
- [model-routing.md](model-routing.md) §3 — fallback chain consumed by scenario #6.
- [enforcement-status.md](enforcement-status.md) — row for this spec; flips to ✅ when trigger fires.

---

## 10. What does NOT live here

- **Generic "fix the bug" advice.** Service-scoped runbooks own that.
- **Runtime playbooks for known failure modes.** Same — service-scoped.
- **Post-mortem prose.** Template at `templates/post-mortem.md.tmpl`; instances under `runbooks/post-mortems/` (or per-consumer equivalent).
- **Access credentials, SSH jumpbox details, secrets-store URIs.** Per-consumer ops doc; never in the public playbook.
- **Vendor-specific paging integration.** Deferred per D4.5.

When the activation trigger fires, **do not split this file** — keep the spec here, the runbooks in `runbooks/`, the per-consumer specifics in the consumer repo. Splitting causes drift that costs more than it saves.

---

## Decisions

- **D4.1** v1.0.0 ships in `wired-pending-trigger` state. Status flips to ✅ only after the lifecycle detector fires. Rationale: a runbook never executed against a real incident is honest as `wired-pending-trigger`, not as ✅.
- **D4.2** Activation trigger is a `consumers.yaml` field, not a manual flip in `enforcement-status.md`. Rationale: automated > human memory.
- **D4.4** Solo → family-of-3 → team-of-N path documented but not wired beyond solo. Family-of-3 trigger is explicit (`oncall_eligible: true` count ≥ 2). Rationale: documenting the path now is cheap; wiring it to a system that doesn't yet have a second human is premature.
- **D4.5** No automated paging-vendor integration (PagerDuty, Opsgenie). Telegram from `notification-policy.md` is enough at solo and family-of-3 scale. Rationale: every additional vendor is a secret to rotate, an outage to monitor, and a bill. Defer until ≥ 4 `oncall_eligible` entries.
- **D4.6** Post-mortems are S1-mandatory, S2-optional. Rationale: forcing a post-mortem on every S2 produces ritual writing that crowds out S1 lessons. Optional + `gotcha` entry mandatory captures the durable bit without the ceremony.
