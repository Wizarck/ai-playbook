# runbook-vps-down.md

> **Status**: Stub v0.1.0. Authored under OpenSpec change `complete-ir-and-model-migration-specs` (Phase 5 P5.6) on 2026-05-01. Sibling to [`specs/incident-response.md`](../specs/incident-response.md) §4 scenario #1.
>
> Stub means: the steps below capture the canonical recovery sequence, but specific commands assume the canonical consumer (consumer-d) topology. Per-consumer richer runbooks (e.g. `consumer-d/runbooks/runbook-vps-disaster-recovery.md`) link from here.

## When to use this runbook

Triggered by [incident-response.md](../specs/incident-response.md) §4 scenario #1: VPS unreachable. Detection: Uptime-Kuma probe failed ×3 OR SSH timeout > 30s.

Severity: **S1**. MTTR target: ≤ 30 min to mitigation.

## Prerequisites

- Secondary device with SSH key authorised on the VPS (laptop, MacBook, or out-of-band machine).
- Cloud-provider console access (Hetzner Cloud, AWS, etc.) for hard-reset path.
- Cloudflared tunnel control panel access for DNS-level diagnostics.

## Steps

1. **Confirm the outage from a second vantage point.**
   ```bash
   ping -c 5 <vps-ip>
   ssh -o ConnectTimeout=15 root@<vps-ip> echo ok
   curl -I https://<public-fqdn>
   ```
   If all three fail, escalate to Step 2. If only HTTPS fails, this is likely a Cloudflare tunnel issue — see `runbook-cloudflare-tunnel.md` (per-consumer).

2. **Check cloud-provider console.**
   Hetzner / AWS / etc. Confirm the VM is `Running`. If `Stopped`, restart from console. If `Running` but unresponsive, capture serial console output before any reboot — it pins the cause.

3. **Recovery via cloud console serial / KVM.**
   ```
   # Common causes with their signatures:
   # - kernel panic visible in serial output
   # - "out of memory" → OOM killer log
   # - filesystem read-only → I/O error log
   ```
   Reboot via console only after capturing the panic / log. Hard-reset is last resort.

4. **Post-reboot verification.**
   ```bash
   ssh root@<vps-ip>
   systemctl status k3s docker cloudflared
   journalctl -p err -n 200
   df -h           # check disk
   free -h         # check memory
   ```
   Any service failed → restart it; if cascading, follow per-service runbook (e.g. `runbook-litellm-down-cascade.md`).

5. **Restore external reachability.**
   ```bash
   curl -I https://<public-fqdn>
   ```
   If 502 / 503 → cloudflared tunnel did not reconnect. `systemctl restart cloudflared` on VPS, OR check tunnel status in Cloudflare Zero Trust dashboard.

6. **Log the incident.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"vps-unreachable","state":"resolved","duration_min":<n>}' >> incidents.jsonl
   ```

## Verification

- All three checks from Step 1 succeed.
- `systemctl status` shows all expected services `active (running)`.
- Uptime-Kuma probes back to green.
- No new errors in `journalctl -p err -n 50` since reboot.

## Rollback

Not applicable — this is a recovery runbook, not a change runbook. If recovery makes things worse (rare), the rollback is to power-cycle and try again from Step 2 with different diagnostics.

## Post-incident artefact required

Post-mortem if downtime > 15 min, per [post-mortem.md](../specs/post-mortem.md). Otherwise gotcha entry minimum, per [retrospective-cadence.md](../specs/retrospective-cadence.md).

## Related

- [incident-response.md](../specs/incident-response.md) §4 scenario #1.
- Per-consumer richer runbook: `<consumer>/runbooks/runbook-vps-disaster-recovery.md`.
- [post-mortem.md](../specs/post-mortem.md) — required artefact for > 15 min outages.
- [notification-policy.md](../specs/notification-policy.md) — paging during the outage.
