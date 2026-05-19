# cascade-failure-template.md

> **Status**: v1.0.0 (new in v0.11.0). Template runbook for **service-dependency cascade failures** — when one service going down triggers exponential downstream impact and the root cause is masked by cascade depth. Cross-validated by consumer-d `runbook-litellm-down-cascade.md` (LiteLLM → Hindsight → Hermes memory → Paperclip cascade) and consumer-b's gotchas (LiteLLM startup ordering + Paperclip port-mapping confusion). Use this template to author per-service cascade runbooks for any consumer with non-trivial service-dependency graphs.

## When to use this template

Author a per-service cascade runbook when:

1. The service has **≥2 downstream consumers** that fail closed (refuse to serve when the dep is down).
2. Recovery from a partial outage is **non-trivial** (not "restart and pray" — there's a sequence of checks).
3. The service's failure has a **history of cascading impact** in retros / postmortems.

Don't author one for:

- Idempotent leaf services (a stateless cache that downstream callers tolerate missing).
- Services with auto-failover that's been verified in DR drills.

---

## Template structure

Replace `<SERVICE>` with the service name. Keep all five sections; they map to the failure-mode taxonomy below.

```markdown
# runbook-<service>-down-cascade.md

> **Status**: v1.0.0. Cascade-failure runbook for `<SERVICE>` — what
> downstream is impacted, how to confirm scope, and the recovery
> sequence.

## 1. Symptom list (what the operator sees first)

The operator typically discovers the cascade via a downstream
notification. Common surface symptoms:

- **<symptom 1>**: e.g. "Hermes message replies with `503 Service
  Unavailable` for any LLM-touching tool call".
- **<symptom 2>**: e.g. "Paperclip POST /webhooks returns immediately
  with HMAC validation failure" (because the secret cache is empty).
- **<symptom 3>**: e.g. "Dashboard shows N consecutive `agent.error`
  events of class `ConnectError`".

The list is empirical: every retro / postmortem touching this cascade
adds one row.

## 2. Precondition check (is it really <SERVICE>?)

Before triaging the cascade, confirm `<SERVICE>` itself is the root
cause:

```bash
# Health probe (HTTP)
curl -fsS https://<service-host>/health || echo "DOWN"

# Process check (k8s)
kubectl -n <namespace> get pods -l app=<service> -o wide

# Recent error log (last 100 lines)
kubectl -n <namespace> logs -l app=<service> --tail=100 | grep -i "error\|fatal\|panic"

# Network connectivity from a known consumer
kubectl -n <namespace> exec -it <consumer-pod> -- curl -fsS https://<service-host>/health
```

**If `<SERVICE>` is up**: the cascade is somewhere else. Walk
downstream from the operator-visible symptom; this runbook does not
apply.

**If `<SERVICE>` is down**: continue.

## 3. Downstream impact map

Document the cascade dependency graph as a YAML or tree. Each
downstream consumer's behaviour-on-failure is explicit:

```yaml
service: <SERVICE>
downstream:
  - name: <consumer-1>
    impact: "fails closed; clients see 503"
    proof_of_life: "GET /<consumer-1>/health returns 200 only when <SERVICE> is up"

  - name: <consumer-2>
    impact: "degrades to last cached value; clients see stale data for <TTL> seconds"
    proof_of_life: "log line 'CACHE_MISS_FALLBACK <SERVICE> last_value=...'"

  - name: <consumer-3>
    impact: "infinite restart loop; PVC fills with crash dumps"
    proof_of_life: "kubectl get pods -l app=<consumer-3> shows CrashLoopBackOff"
```

Every consumer added by a future slice extends this section. Keep it
in sync; cascade depth grows silently otherwise.

## 4. Recovery sequence (in order)

> **Each step is gated**: do not advance until the prior step's proof
> succeeds. Cascade recovery is not parallel.

1. **<step 1>** — bring `<SERVICE>` itself back. Cite the specific
   recovery command (`kubectl rollout restart`, `helm upgrade`,
   `systemctl restart`) and the proof:
   ```bash
   kubectl rollout restart deployment/<service> -n <namespace>
   kubectl rollout status deployment/<service> -n <namespace> --timeout=120s
   curl -fsS https://<service-host>/health  # MUST return 200
   ```

2. **<step 2>** — for each downstream that fails closed, force a
   reconnect or restart in dependency order (closest to `<SERVICE>`
   first):
   ```bash
   kubectl rollout restart deployment/<consumer-1> -n <namespace>
   # Wait for ready; then
   kubectl rollout restart deployment/<consumer-2> -n <namespace>
   ```

3. **<step 3>** — for stateful consumers (caches, message queues),
   verify state coherence:
   ```bash
   # E.g. drain the consumer's stale-value cache
   kubectl exec -it <consumer-2-pod> -- redis-cli FLUSHDB
   ```

4. **<step 4>** — verify proof-of-life on every downstream listed in
   §3. Each `proof_of_life` line in §3 is a check command.

5. **<step 5>** — emit a `<SERVICE>.recovered` telemetry event with
   the operator's runbook-execution timestamp + the duration. Feeds
   the postmortem.

## 5. Postmortem trigger

If recovery took >15 minutes OR if any downstream's data was lost (not
just delayed): file a postmortem in `docs/postmortems/<YYYY-MM-DD>-<service>-cascade.md`
per [post-mortem.md](../docs/concepts/post-mortem.md). Include:

- Cascade depth (how many services restarted).
- Operator-time to detect (T_detect = first symptom → confirmed root).
- Operator-time to recover (T_recover = root identified → all green).
- Did the recovery sequence in §4 work as written? If not, file an
  amendment to this runbook.
```

---

## Anti-patterns

- **Restarting the entire stack as the first step**: forbidden. Walk
  the cascade in dependency order; restarting a healthy downstream can
  mask the real problem.
- **Skipping the precondition check**: forbidden. The operator may be
  responding to a downstream alert that has nothing to do with
  `<SERVICE>` (different root cause, same symptom).
- **Cascade runbook with no `proof_of_life` per downstream**: forbidden.
  Without proof-of-life commands, recovery verification is "did the
  pod come up" — which may be true even when the consumer's contract
  with `<SERVICE>` is broken.
- **Hardcoding hostnames / namespaces in the runbook**: forbidden.
  Parameterise via env vars or CLI flags so the runbook works across
  staging / prod / DR environments.

---

## Reference implementations

| Project | Runbook | Cascade depth | Notes |
|---|---|---|---|
| consumer-d | [`runbook-litellm-down-cascade.md`](https://github.com/Wizarck/consumer-d/blob/master/runbooks/runbook-litellm-down-cascade.md) | 4 (LiteLLM → Hindsight → Hermes memory → Paperclip) | Original; this template extracted from its structure |
| consumer-b | (gotchas.md captures startup ordering) | 2 | Promote to runbook when cascade depth grows |
| consumer-e | (TBD; deployment-foundation slice will introduce) | TBD | Likely candidates: `litellm-down`, `ibkr-down`, `openbb-down` |

When a project adopts this template, link the resulting runbook back to this template via `> See [cascade-failure-template.md](../../.ai-playbook/docs/runbooks/cascade-failure-template.md) for the structure rationale.`

---

## Cross-references

- [post-mortem.md](../docs/concepts/post-mortem.md) — postmortem ritual triggered by §5.
- [degradation-modes.md](../docs/concepts/degradation-modes.md) — the canonical
  taxonomy of how services degrade; the cascade map's `impact` field
  picks values from this taxonomy.
- [incident-response.md](../docs/concepts/incident-response.md) — incident-class
  ladder; cascades are typically S2 unless data loss → S1.
- [hitl-approval-pattern.md](../docs/rules/hitl-approval-pattern.rule.md) — when
  a recovery step requires HITL gating (e.g. failover to backup) the
  approval pattern applies.
