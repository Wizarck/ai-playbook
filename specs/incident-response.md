# incident-response.md

> **Status**: deferred — activates when a paying client lands. Populated in T22a as a placeholder so downstream specs can cross-reference the contract; real runbook content is gated on the trigger conditions below.

Incident Response (IR) is the contract that coordinates humans and tooling during a user-visible outage or data-corruption event. At v0.1.0 the playbook runs personal projects only, so the full runbook is intentionally unwritten — it would be fiction, not a contract. This file documents the current (personal-only) practice, the triggers that flip IR on, and the scope the full runbook must cover once it does.

---

## What "incident" means here

A user-visible outage or a data-corruption event on a service running under Arturo's infra:

- **Hermes** — notification/egress service.
- **Paperclip** — attachment processor.
- **Hindsight** — memory MCP (data-corruption class: a bad retain corrupts subsequent recalls).
- **LiteLLM** — model router.
- **Dashboard** — observability UI.

Scope excludes routine local dev glitches, flaky tests, CI pipeline hiccups that do not affect a running service — those live in each service's runbook. An "incident" here is by definition observable from outside the box.

---

## Current (personal-only) practice

No SLA, no on-call rotation, no status page. The full contract below is deferred.

1. **Paging.** Monitoring (`OTel Collector → Tempo` + Langfuse health-probes) emits a Telegram alert to Arturo's personal channel when a critical probe fires. Alerts are best-effort; missed alerts are tolerated.
2. **Triage.** Arturo reads the alert, opens the Langfuse trace, and decides whether to intervene.
3. **Recovery.** Remediation goes through `consumer-d-ops suggest_remediation` in **propose-mode** (per T16): the tool drafts a recovery action, Arturo reads, Arturo applies manually. No auto-apply during incidents.
4. **Follow-up.** For anything that touched prod state, a short note in `gotchas.md` or a new ADR. Post-mortems (see [post-mortem.md](post-mortem.md)) are NOT currently written — that too is deferred with IR.

Actors for the personal stance: Arturo (sole responder, sole post-mortem author, sole reviewer). No delegation.

---

## Triggers for activating the full runbook

IR flips from "deferred" to "active" when **any** of the following is true:

- **First paying SaaS customer.** The moment a user's money transits, "best-effort Telegram" is no longer honest.
- **First non-Arturo operator.** A second human with production access implies coordination rules.
- **First security incident** (confirmed unauthorised access, confirmed secret leak outside the contributor's own environment, confirmed prod data exfiltration). Regardless of customer status, this forces the full contract on.

Whichever trigger fires first activates IR. The retro cadence in [retrospective-cadence.md](retrospective-cadence.md) §4 surfaces proximity to these triggers on every monthly.

---

## Full runbook scope when activated

The bullets below name what the full runbook must cover when it is written. **This list is intentionally scope-only — no implementation here.** The real runbook lives in a separate RFC and a new document (likely `docs/runbooks/incident-response.md` in the relevant consumer repo).

- **On-call rotation** — who is paged when; primary + secondary; handoff cadence.
- **Escalation ladder** — primary → secondary → maintainer → founder; timings; no-response fallbacks.
- **Paging infrastructure** — PagerDuty (or OpsGenie) wiring; escalation policy; schedule export to OTel so the dashboard shows who is on call.
- **Severity matrix + MTTR targets** — per-severity (SEV0..SEV3) response, containment, and resolution targets.
- **Status page** — public vs internal; update cadence during an incident; post-incident close note.
- **Post-mortem requirement** — every SEV0/SEV1 produces a post-mortem within 7 days per [post-mortem.md](post-mortem.md); blameless review; action items tracked.
- **Blameless review** — explicit anti-blame language in the template; systems-focus contract.
- **Communication discipline** — who speaks to customers; canned lines; internal vs external channels.
- **Runbook cross-links** — per-service runbooks (Hermes / Paperclip / Hindsight / LiteLLM / Dashboard) remain the first point of contact for "how to fix the bug"; IR is the coordination layer on top.

---

## Cross-references

- [post-mortem.md](post-mortem.md) — the artefact IR produces after SEV0/SEV1 or a SYSTEMIC escalation.
- [notification-policy.md](notification-policy.md) — what paging channels IR uses and at what level.
- [degradation-modes.md](degradation-modes.md) — the "announced degradation" path that is IR-adjacent but not the same thing; a degraded service is not automatically an incident.
- [role-matrix.md](role-matrix.md) — who has rights to page, triage, declare recovered.
- [retrospective-cadence.md](retrospective-cadence.md) — retro surface for every incident.
- [break-glass.md](break-glass.md) — `--force-with-reason` usage during an incident is logged but not blocked.

---

## What NOT to put here

- **Generic "fix the bug" advice.** That belongs in the service-level runbook (e.g. `docs/runbooks/hermes.md`).
- **Runtime playbooks for known failure modes.** Same reason — service-scoped.
- **Post-mortem prose.** The template lives at [../templates/post-mortem.md.tmpl](../templates/post-mortem.md.tmpl) and instances land under `reports/post-mortems/`.
- **Access credentials, SSH jumpbox details, secrets-store URIs.** Those live in the operations doc inside the consumer repo (e.g. `consumer-d/docs/operations/*`) and never in the public ai-playbook.

When the first trigger fires, split this file: keep the "trigger / scope" contract here in the playbook, move the actual runbook into the consumer repo that owns the service.
