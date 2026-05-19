---
schema: runbook/v1
slug: runbook-db-corruption
description: Recover from Hindsight (SQLite-backed memory MCP) database corruption — pick the right recovery path (backup, sqlite recovery, JSONL replay) and verify.
audience: operator
estimated_time: ≤30 min to mitigation; ≤4 h to durable fix
last_validated: "2026-05-19"
---

# Recover from Hindsight DB corruption

## Outcome

The Hindsight DB is back to `PRAGMA integrity_check == ok`, the service is serving writes again, no further `retain_failed` events appear for 10 minutes, and the broken DB is preserved as a forensic snapshot for the mandatory post-mortem.

## When to use this

Triggered by [Concept: incident-response](../concepts/incident-response.md) §4 scenario #2. Detection signals:

- `_hindsight.py::HttpResult.reason == "degraded:retain_failed"` rate > 5%/min in `events.jsonl`.
- Explicit `database disk image is malformed` errors in service logs.

Severity: **S1** (data integrity class). MTTR target: ≤30 min to mitigation; ≤4 h to durable fix.

Skip this runbook when:

- `PRAGMA integrity_check` returns `ok` (false alarm — recheck the detection signal).
- The service is fully down with no DB writes occurring (use [Runbook: runbook-vps-down](runbook-vps-down.md) first).

## Prerequisites

- SSH access to the VPS hosting Hindsight: `ssh root@<vps-ip> echo ok`.
- A backup of the DB file (Velero snapshot, file-level cron, or per-consumer convention).
- The service's JSONL queue file (`hindsight-queue.jsonl`) — replay source if the backup is stale.

## Steps

1. **Stop write traffic.**
   ```bash
   kubectl scale deploy/hindsight --replicas=0 -n consumer-d
   # Or for Docker:
   docker stop hindsight
   ```
   Reads-only state is acceptable. The goal is to prevent further bad writes from compounding the corruption.

2. **Snapshot the broken DB before touching it.**
   ```bash
   ssh root@<vps-ip>
   cp /opt/consumer-d/data/hindsight.db \
      /opt/consumer-d/backups/hindsight-broken-$(date +%Y%m%d-%H%M%S).db
   ```
   This snapshot is for forensic analysis post-incident. Do NOT delete even after recovery succeeds.

3. **Diagnose the corruption.**
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight.db "PRAGMA integrity_check;"
   ```
   Expected outputs:
   - `ok` → false alarm. Stop here, recheck the detection signal.
   - `*** in database main *** ...` → real corruption. Proceed to step 4.

4. **Pick a recovery path.**

   **Path A — restore from latest clean backup** (preferred when backup is <24 h old):
   ```bash
   cp /opt/consumer-d/backups/hindsight-<ts>.db /opt/consumer-d/data/hindsight.db
   ```

   **Path B — sqlite recovery** (when backup is >24 h old; preserves more recent state):
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight-broken-<ts>.db ".recover" \
     | sqlite3 /opt/consumer-d/data/hindsight-recovered.db
   mv /opt/consumer-d/data/hindsight-recovered.db /opt/consumer-d/data/hindsight.db
   ```

   **Path C — replay from JSONL queue** (when A and B both fail):
   ```bash
   # Stop all services that retain to Hindsight first.
   python -m scripts.replay_jsonl --source hindsight-queue.jsonl \
       --target /opt/consumer-d/data/hindsight.db
   ```
   Path C loses retains that happened between the last queue flush and the corruption window.

5. **Verify recovery integrity.**
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight.db "PRAGMA integrity_check;"   # expect "ok"
   sqlite3 /opt/consumer-d/data/hindsight.db "SELECT COUNT(*) FROM memories;"  # sanity row count
   ```

6. **Resume traffic.**
   ```bash
   kubectl scale deploy/hindsight --replicas=1 -n consumer-d
   kubectl logs -f deploy/hindsight -n consumer-d | grep -E "retain|corrupt"
   ```
   Watch for new `retain_failed` events; none should appear.

7. **Log the incident.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"db-corruption","recovery_path":"<A|B|C>","state":"resolved"}' >> incidents.jsonl
   ```

## Verification

- `PRAGMA integrity_check` returns `ok`.
- Service logs show no `retain_failed` for ≥10 minutes after resume.
- `events.jsonl gen_ai.usage` rate returns to baseline.
- A test retain via `_hindsight.py` succeeds end-to-end (use [Runbook: hindsight-retain](hindsight-retain.md) §step 4 verification).

## Troubleshooting

### Symptom: `PRAGMA integrity_check` returns `ok` after the alert
**Cause**: false alarm — the detection threshold may be too tight, or a transient was reported.
**Fix**: do not proceed with recovery. Investigate the `events.jsonl` window that produced the `retain_failed` rate. Often a short-lived disk-full event or a temporary lock.

### Symptom: Path B `.recover` produces a file that opens but is missing rows
**Cause**: `.recover` extracts whatever it can; rows in damaged pages are dropped.
**Fix**: if row loss is unacceptable, abort Path B and try Path C with the JSONL queue. If both fail, escalate per "Recovery makes things worse" below.

### Symptom: recovery makes things worse (Path B produced an inconsistent state visible only after some time)
**Cause**: `.recover` may rebuild indexes against partial data.
**Fix**:
1. Stop traffic again.
2. Restore the snapshot from Step 2 (the broken DB is the rollback target — it had data, even if corrupt).
3. File a `❓ CLARIFICATION NEEDED` and escalate. This branch is rare and warrants a maintainer.

### Symptom: queue replay (Path C) skips items
**Cause**: schema drift between the queued JSONL entries and the current DB schema.
**Fix**: inspect the skipped lines (the script logs `skipped: <reason>` per drop). Adjust the schema migration or transform the queue items before replay.

## Post-incident artefact required

**Post-mortem mandatory** (data integrity class), per [Concept: post-mortem](../concepts/post-mortem.md). The artefact must name the corruption signature, the recovery path used (A/B/C), and any data-loss window.

## Related

- [Runbook: runbook-vps-down](runbook-vps-down.md) — when the DB host itself is unreachable.
- [Runbook: hindsight-retain](hindsight-retain.md) — the write path; smoke test post-recovery.
- [Concept: incident-response](../concepts/incident-response.md) — incident-class ladder; this is §4 scenario #2.
- [Concept: memory-hierarchy](../concepts/memory-hierarchy.md) — Hindsight as Tier 3.
- [Concept: degradation-modes](../concepts/degradation-modes.md) — `degraded:retain_failed` taxonomy.
- [Concept: post-mortem](../concepts/post-mortem.md) — mandatory artefact.
