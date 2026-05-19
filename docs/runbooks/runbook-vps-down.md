---
schema: runbook/v1
slug: runbook-vps-down
description: Recover a VPS that is unreachable (SSH timeout, ping fail, HTTPS fail) — confirm scope, restore via cloud console, verify external reachability.
audience: operator
estimated_time: ≤30 min to mitigation
last_validated: "2026-05-19"
---

# Recover from VPS unreachable

## Outcome

The VPS is reachable again (ping, SSH, HTTPS all succeed), every expected service is `active (running)`, the public FQDN serves traffic, Uptime-Kuma probes return green, and the incident is logged in `incidents.jsonl`. If downtime exceeded 15 minutes, a post-mortem is filed within the deadline.

## When to use this

Triggered by [Concept: incident-response](../concepts/incident-response.md) §4 scenario #1: VPS unreachable. Detection: Uptime-Kuma probe failed ×3 OR SSH timeout >30 s.

Severity: **S1**. MTTR target: ≤30 min to mitigation.

Skip this runbook when:

- Only HTTPS is failing but SSH and ping succeed — that is a Cloudflare tunnel issue; use the per-consumer cloudflare-tunnel runbook.
- A specific application is down but the VPS itself is fine — use the per-application runbook.

## Prerequisites

- A secondary device with SSH key authorised on the VPS (laptop, MacBook, or out-of-band machine).
- Cloud-provider console access (Hetzner Cloud, AWS) for hard-reset and serial console paths.
- Cloudflared tunnel control panel access for DNS-level diagnostics.

## Steps

1. **Confirm the outage from a second vantage point.**
   ```bash
   ping -c 5 <vps-ip>
   ssh -o ConnectTimeout=15 root@<vps-ip> echo ok
   curl -I https://<public-fqdn>
   ```
   If all three fail, proceed to step 2. If only HTTPS fails, this is a Cloudflare tunnel issue — see the per-consumer `runbook-cloudflare-tunnel.md`.

2. **Check the cloud-provider console.**
   Hetzner, AWS, or equivalent. Confirm the VM state.
   - If `Stopped`: restart from console.
   - If `Running` but unresponsive: capture serial console output BEFORE any reboot — it pins the cause.

3. **Recover via serial / KVM console.**
   ```
   Common causes and their signatures:
   - kernel panic visible in serial output
   - "out of memory" → OOM killer log
   - filesystem read-only → I/O error log
   ```
   Reboot via console only after capturing the panic or log. Hard-reset is the last resort.

4. **Post-reboot verification.**
   ```bash
   ssh root@<vps-ip>
   systemctl status k3s docker cloudflared
   journalctl -p err -n 200
   df -h           # check disk
   free -h         # check memory
   ```
   For any service that failed, restart it. If failures cascade, follow the per-service runbook (e.g., `runbook-litellm-down-cascade.md` per [Runbook: cascade-failure-template](cascade-failure-template.md)).

5. **Restore external reachability.**
   ```bash
   curl -I https://<public-fqdn>
   ```
   If 502 / 503: cloudflared tunnel did not reconnect. Either `systemctl restart cloudflared` on the VPS, or check tunnel status in Cloudflare Zero Trust dashboard.

6. **Log the incident.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"vps-unreachable","state":"resolved","duration_min":<n>}' >> incidents.jsonl
   ```

## Verification

- All three checks from Step 1 succeed (`ping`, `ssh`, `curl -I https://...`).
- `systemctl status` shows every expected service `active (running)`.
- Uptime-Kuma probes return to green.
- `journalctl -p err -n 50` shows no new errors since the reboot.

## Troubleshooting

### Symptom: recovery makes things worse (rare)
**Cause**: serial console reboot triggered a different failure mode (e.g., disk filesystem now refuses to mount).
**Fix**: power-cycle and retry from Step 2 with different diagnostics. Capture the new serial output before any further action. Escalate to a maintainer if two cycles fail.

### Symptom: serial console output unavailable in provider UI
**Cause**: provider tier does not include serial console (rare on Hetzner; common on lower AWS tiers).
**Fix**: skip directly to hard-reset; lose the panic context. File a follow-up to capture next time (e.g., enable `kdump` if the OS supports it).

### Symptom: SSH works after reboot but services fail to start
**Cause**: a previous incident corrupted on-disk state (k3s lease file, Docker overlay).
**Fix**: per-service recovery — for k3s, `systemctl restart k3s` then `kubectl get pods -A`. For Docker, `systemctl restart docker` then `docker ps`. If the issue persists, escalate to a per-service runbook (cascade-failure-template applies when downstream consumers fail closed).

### Symptom: cloudflared reconnects but `curl -I https://<fqdn>` returns 502
**Cause**: the tunnel is up but the local upstream (nginx, traefik, etc.) is not.
**Fix**: `systemctl status nginx` (or whichever ingress is in use) and restart. If unresolved, inspect `cloudflared --hello-world` for connectivity sanity.

## Post-incident artefact required

Post-mortem if downtime >15 minutes, per [Concept: post-mortem](../concepts/post-mortem.md). Otherwise a gotcha entry minimum, per [Concept: retrospective-cadence](../concepts/retrospective-cadence.md).

## Related

- [Runbook: cascade-failure-template](cascade-failure-template.md) — author a per-service cascade runbook when one service going down triggers downstream failure.
- [Runbook: runbook-db-corruption](runbook-db-corruption.md) — when the VPS is up but the DB is corrupt.
- [Concept: incident-response](../concepts/incident-response.md) — incident-class ladder; this is §4 scenario #1.
- [Concept: post-mortem](../concepts/post-mortem.md) — required artefact for >15 min outages.
- [Concept: notification-policy](../concepts/notification-policy.md) — paging during the outage.
