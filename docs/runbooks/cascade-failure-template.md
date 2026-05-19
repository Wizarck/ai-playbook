---
schema: runbook/v1
slug: cascade-failure-template
description: Template for authoring a per-service cascade-failure recovery runbook when one service going down triggers exponential downstream impact.
audience: developer
estimated_time: 30-60 min (authoring); 5-15 min (recovery, when instantiated)
last_validated: "2026-05-19"
---

# Author a per-service cascade-failure runbook

## Outcome

A new `runbook-<service>-down-cascade.md` exists in the consumer's runbooks tree, structured around the five canonical sections below. Operators discovering a cascade involving `<SERVICE>` can walk the recovery sequence without re-deriving the dependency graph each incident.

## When to use this

Author a per-service cascade runbook when all three hold:

1. The service has ≥2 downstream consumers that fail closed (refuse to serve when the dependency is down).
2. Recovery from a partial outage is non-trivial (more than a single restart).
3. The service's failure has a history of cascading impact captured in retros or postmortems.

Skip authoring for:

- Idempotent leaf services downstream callers tolerate missing.
- Services with auto-failover verified in DR drills.

## Prerequisites

- Write access to the consumer's `runbooks/` directory: `ls <consumer>/runbooks/`.
- A list of every downstream of `<SERVICE>`, derived from service mesh or code grep: `grep -rl "<SERVICE>" --include='*.py' --include='*.yaml' .`.
- At least one prior incident report or retro entry that the new runbook can cite as its evidence base.

## Steps

1. **Copy the template structure.** Create `<consumer>/runbooks/runbook-<service>-down-cascade.md` with the five sections below pre-stubbed.

2. **Author §1 Symptom list — what the operator sees first.**
   The cascade is typically discovered via a downstream notification, not via the root service. Examples to seed:
   ```markdown
   - **<symptom 1>**: e.g. "Hermes message replies with `503 Service Unavailable` for any LLM-touching tool call".
   - **<symptom 2>**: e.g. "Paperclip POST /webhooks returns immediately with HMAC validation failure".
   - **<symptom 3>**: e.g. "Dashboard shows N consecutive `agent.error` events of class `ConnectError`".
   ```
   The list is empirical: every retro or postmortem touching this cascade adds a row.

3. **Author §2 Precondition check — is it really `<SERVICE>`?**
   Before triaging the cascade, confirm `<SERVICE>` itself is the root cause:
   ```bash
   curl -fsS https://<service-host>/health || echo "DOWN"
   kubectl -n <namespace> get pods -l app=<service> -o wide
   kubectl -n <namespace> logs -l app=<service> --tail=100 | grep -i "error\|fatal\|panic"
   ```
   If `<SERVICE>` is up, the cascade root is elsewhere; the runbook does not apply.

4. **Author §3 Downstream impact map.** Document the cascade as YAML. Each consumer's behaviour-on-failure must be explicit and observable:
   ```yaml
   service: <SERVICE>
   downstream:
     - name: <consumer-1>
       impact: "fails closed; clients see 503"
       proof_of_life: "GET /<consumer-1>/health returns 200 only when <SERVICE> is up"
     - name: <consumer-2>
       impact: "degrades to last cached value; clients see stale data for <TTL>s"
       proof_of_life: "log line 'CACHE_MISS_FALLBACK <SERVICE> last_value=...'"
     - name: <consumer-3>
       impact: "infinite restart loop; PVC fills with crash dumps"
       proof_of_life: "kubectl get pods -l app=<consumer-3> shows CrashLoopBackOff"
   ```
   Every consumer added by a future slice extends this section.

5. **Author §4 Recovery sequence — in order, gated.**
   ```bash
   # 4.1 Bring <SERVICE> back.
   kubectl rollout restart deployment/<service> -n <namespace>
   kubectl rollout status deployment/<service> -n <namespace> --timeout=120s
   curl -fsS https://<service-host>/health   # MUST return 200

   # 4.2 Restart each downstream that fails closed, in dependency order.
   kubectl rollout restart deployment/<consumer-1> -n <namespace>
   kubectl rollout restart deployment/<consumer-2> -n <namespace>

   # 4.3 For stateful consumers, drain stale state.
   kubectl exec -it <consumer-2-pod> -- redis-cli FLUSHDB

   # 4.4 Verify proof-of-life on every consumer (one check per §3 row).

   # 4.5 Emit a <SERVICE>.recovered telemetry event with operator timestamp + duration.
   ```
   Each step is gated: do not advance until the prior step's proof succeeds.

6. **Author §5 Postmortem trigger.** If recovery took >15 minutes OR any downstream lost data, the runbook MUST require a postmortem in `docs/postmortems/<YYYY-MM-DD>-<service>-cascade.md` per the [post-mortem](../concepts/post-mortem.md) concept. Mandatory fields: cascade depth, T_detect, T_recover, did §4 work as written.

7. **Link the new runbook back to this template** in its first paragraph. Example wording: a blockquote stating "Structure rationale: Runbook cascade-failure-template (in `.ai-playbook/docs/runbooks/cascade-failure-template.md`)". The exact link target depends on the consumer's submodule layout.

## Verification

The new runbook satisfies all five gates:

- §1 lists ≥3 symptoms with concrete log lines or HTTP responses.
- §2 contains an executable health probe whose exit code distinguishes up/down.
- §3 has a `proof_of_life` row for every downstream consumer.
- §4 lists every command an operator runs, in order, with gating between steps.
- §5 names the postmortem trigger thresholds explicitly.

## Troubleshooting

### Symptom: cascade depth keeps growing as new consumers ship
**Cause**: §3 was not updated alongside the new consumer's PR.
**Fix**: add a checklist item to the consumer's PR template requiring §3 update when a new dependency on `<SERVICE>` is introduced. Track the depth in retros.

### Symptom: recovery sequence in §4 worked once and now fails
**Cause**: a downstream service changed its startup contract (e.g., now requires `<SERVICE>` warm cache, not just liveness).
**Fix**: re-run the recovery on a staging incident, update §4 to reflect the new ordering, and file an amendment PR. Cite the incident.

### Symptom: operator restarts the entire stack as the first step
**Cause**: §2 precondition check was skipped or unclear.
**Fix**: rewrite §2 as a single shell command whose output makes the decision (no human interpretation). Add a "do not restart downstream first" warning at the top of §4.

### Symptom: hostnames or namespaces are hardcoded in the runbook
**Cause**: original author copied from one environment without parameterising.
**Fix**: replace literals with env vars (`<SERVICE>`, `<NAMESPACE>`) and document the substitution at the top. The runbook must work across staging, prod, and DR.

## Related

- [Runbook: runbook-vps-down](runbook-vps-down.md) — VPS-class outage; cascade is often a downstream effect.
- [Concept: post-mortem](../concepts/post-mortem.md) — postmortem ritual triggered by §5.
- [Concept: degradation-modes](../concepts/degradation-modes.md) — canonical taxonomy the §3 `impact` field draws from.
- [Concept: incident-response](../concepts/incident-response.md) — incident-class ladder; cascades are S2 unless data loss → S1.
- [Rule: hitl-approval-pattern](../rules/hitl-approval-pattern.rule.md) — when a recovery step requires HITL gating.

### Reference implementations

| Project | Runbook | Cascade depth | Notes |
|---|---|---|---|
| consumer-d | `runbook-litellm-down-cascade.md` | 4 (LiteLLM → Hindsight → Hermes memory → Paperclip) | Original; this template extracted from its structure. |
| consumer-b | `gotchas.md` captures startup ordering | 2 | Promote to runbook when cascade depth grows. |
| consumer-e | TBD (deployment-foundation slice) | TBD | Likely candidates: `litellm-down`, `ibkr-down`, `openbb-down`. |
