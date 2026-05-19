# runbook-db-corruption.md

> **Status**: Stub v0.1.0. Authored under OpenSpec change `complete-ir-and-model-migration-specs` (Phase 5 P5.6) on 2026-05-01. Sibling to [`docs/concepts/incident-response.md`](../docs/concepts/incident-response.md) §4 scenario #2.
>
> Stub means: the steps below capture the canonical recovery sequence for Hindsight (the canonical SQLite-backed memory MCP); the same shape applies to other SQLite-backed services with adjustments.

## When to use this runbook

Triggered by [incident-response.md](../docs/concepts/incident-response.md) §4 scenario #2: Hindsight DB corruption. Detection: `_hindsight.py::HttpResult.reason == "degraded:retain_failed"` rate > 5%/min in `events.jsonl`. Or: explicit `database disk image is malformed` errors in service logs.

Severity: **S1** (data integrity class). MTTR target: ≤ 30 min to mitigation; ≤ 4 h to durable fix.

## Prerequisites

- SSH access to the VPS hosting the affected service.
- Backup of the DB file (Velero snapshot, file-level cron, or per-consumer convention).
- The service's JSONL queue file (e.g. `hindsight-queue.jsonl`) — replay source if backup is stale.

## Steps

1. **Stop write traffic.**
   ```bash
   kubectl scale deploy/hindsight --replicas=0 -n consumer-d
   # Or for Docker:
   docker stop hindsight
   ```
   Reads-only state is acceptable; the goal is to prevent further bad writes from compounding the corruption.

2. **Snapshot the broken DB.**
   ```bash
   ssh root@<vps-ip>
   cp /opt/consumer-d/data/hindsight.db /opt/consumer-d/backups/hindsight-broken-$(date +%Y%m%d-%H%M%S).db
   ```
   Snapshot is for forensic analysis post-incident — do NOT delete even after recovery.

3. **Diagnose the corruption.**
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight.db "PRAGMA integrity_check;"
   # Common outputs:
   # - "ok" → false alarm, recheck detection signal
   # - "*** in database main *** ..." → real corruption, proceed
   ```

4. **Choose recovery path.**

   **Path A — restore from latest clean backup** (preferred if backup is < 24h old):
   ```bash
   cp /opt/consumer-d/backups/hindsight-<ts>.db /opt/consumer-d/data/hindsight.db
   ```

   **Path B — sqlite recovery** (if backup is > 24h old; preserves more recent state):
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight-broken-<ts>.db ".recover" | sqlite3 /opt/consumer-d/data/hindsight-recovered.db
   mv /opt/consumer-d/data/hindsight-recovered.db /opt/consumer-d/data/hindsight.db
   ```

   **Path C — replay from JSONL queue** (if both backup and recovery fail):
   ```bash
   # Stop all services that retain to Hindsight.
   # Replay the queue:
   python -m scripts.replay_jsonl --source hindsight-queue.jsonl --target /opt/consumer-d/data/hindsight.db
   ```
   Path C loses any retains that happened between the last queue flush and the corruption window.

5. **Verify recovery.**
   ```bash
   sqlite3 /opt/consumer-d/data/hindsight.db "PRAGMA integrity_check;"  # expect "ok"
   sqlite3 /opt/consumer-d/data/hindsight.db "SELECT COUNT(*) FROM memories;"  # sanity row count
   ```

6. **Resume traffic.**
   ```bash
   kubectl scale deploy/hindsight --replicas=1 -n consumer-d
   # Watch logs for retain failures recurring:
   kubectl logs -f deploy/hindsight -n consumer-d | grep -E "retain|corrupt"
   ```

7. **Log the incident.**
   ```bash
   echo '{"ts":"<iso>","incident_id":"INC-<n>","severity":"S1","scenario":"db-corruption","recovery_path":"<A|B|C>","state":"resolved"}' >> incidents.jsonl
   ```

## Verification

- `PRAGMA integrity_check` returns `ok`.
- Service log shows no `retain_failed` for ≥ 10 min after resume.
- `events.jsonl gen_ai.usage` rate returns to baseline.
- A test retain via `_hindsight.py` succeeds end-to-end.

## Rollback

If the recovery itself made things worse (e.g. Path B `.recover` produced an inconsistent state visible only after some time):

1. Stop traffic again.
2. Restore the snapshot from Step 2 (the broken DB is the rollback target — it had data, even if corrupt).
3. File a `❓ CLARIFICATION NEEDED` and escalate. This branch is rare and warrants a maintainer.

## Post-incident artefact required

**Post-mortem mandatory** (data integrity class), per [post-mortem.md](../docs/concepts/post-mortem.md). The artefact must name the corruption signature, the recovery path used, and any data loss window.

## Related

- [incident-response.md](../docs/concepts/incident-response.md) §4 scenario #2.
- [memory-hierarchy.md](../docs/concepts/memory-hierarchy.md) — Hindsight is Tier 3.
- [degradation-modes.md](../docs/concepts/degradation-modes.md) — `degraded:retain_failed` taxonomy.
- [post-mortem.md](../docs/concepts/post-mortem.md) — mandatory artefact.
- Per-consumer richer runbook: `<consumer>/runbooks/runbook-hindsight-recovery.md` (when written).
