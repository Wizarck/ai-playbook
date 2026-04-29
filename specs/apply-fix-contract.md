# apply-fix-contract.md

> **Status**: v1.0.0. Authored under change `add-hitl-channels-and-apply-fix` (2026-04-29) as part of bringing forward Phase 5 work originally deferred at v0.2.0 (see `consumer-d/docs/openspec-slice-phase5.md`).
>
> Sibling to [break-glass.md](break-glass.md). break-glass governs **CLI overrides on validation gates**; this spec governs **workflow mutation of prod state via human-in-the-loop approval**. Different audiences, different lifecycles.

Contract that any workflow MUST honor when it wants to mutate prod state (run a command, restart a container, edit a file, call a destructive API). Lifts the propose-only ceiling that previously kept all `langgraph-aiops/workflows/*.py` write paths blocked behind `NotImplementedError("APPLY_FIX mode deferred to T29")`.

---

## Two-tier permission model

| Tier | Path | Examples | Constraint |
|---|---|---|---|
| **Autonomous** | `langgraph-aiops/watchdogs.py`, `langgraph-aiops/workflows/vps_maintainer.py` (low/medium-risk steps in `--cron` mode only) | Service auto-restart on consecutive failures; weekly disk cleanup | Idempotent, reversible, low blast radius. Documented in `langgraph-aiops/LEGACY_MIGRATION.md` as exceptions; new exceptions require an explicit row added there. |
| **HITL-gated (this spec)** | All other workflow mutations | etcd defrag, package upgrade, schema migration | Goes through `hitl.request_approval` with the envelope shape below. Default. |

Any workflow that mutates state and is NOT in the autonomous tier MUST follow the contract in §Envelope and §Apply path below.

`break-glass.md`'s `--force-with-reason` does NOT apply here — that flag exists for CLI gates that block a human from doing a one-off thing (commit, validate, render). This contract governs **automation** mutating prod, where the human must affirm in real time.

---

## Envelope

`hitl.request_approval` accepts (in addition to existing `action`, `payload`, `severity`):

| Field | Type | Required when | Meaning |
|---|---|---|---|
| `command_preview` | `str` | `mode="apply"` | The exact bytes the workflow will execute. Channel adapters render this verbatim to the approver. The bytes the workflow runs MUST equal these bytes — see §Exact-match invariant. |
| `idempotency_key` | `str` | `mode="apply"` | Workflow-supplied unique key (typically `<workflow>-<step>-<host>-<date>`). A re-run with the same key on already-converged state MUST produce no diff. |
| `reversal_hint` | `str` | `mode="apply"` | Short text the approver sees: how to roll back, or "irreversible" + recovery cost. Examples: `"rollback: docker start rancher (~30 s)"`, `"irreversible: rebuilt cache on next image build (~10 min)"`. |
| `risk` | `"low" \| "medium" \| "high"` | `mode="apply"` | Risk tier. Routes to channel + escalation. `high` cannot be pre-approved by recurring schedule. |
| `mode` | `"dry-run" \| "apply"` | always optional; default `"dry-run"` | Whether to actually run on approval. `dry-run` always runs the idempotency precheck and renders to channel but skips execution. |
| `max_approval_age_seconds` | `int \| None` | optional | Per-call TTL override. Falls back to `hitl.py` global default (24 h) if unset. |

Example envelope (workflow code):

```python
from langgraph_aiops.workflows.hitl import request_approval

approval = request_approval(
    action="vps-cleanup-docker-prune",
    payload={"host": "consumer-d-prod"},
    severity="warn",
    command_preview="docker builder prune -af",
    idempotency_key="vps_maintainer-docker-prune-consumer-d-prod-2026-04-29",
    reversal_hint="cache rebuilds on next image build (~10 min, recoverable)",
    risk="medium",
    mode="apply",
)
```

---

## Apply path

Once `request_approval` returns `ApprovalResult.approved=True`, the workflow MUST:

1. Call `hitl.verify_apply_safety(approval, expected_command=<exact bytes>, idempotency_check=<callable>)` before executing.
   - Returns `True` if the command-about-to-run exact-matches the approved `command_preview` AND the idempotency precheck reports "would change state".
   - Returns `False` if the precheck reports already-converged (workflow should skip + log).
   - Raises `ApplyFixMismatchError` if the bytes do not exact-match.
2. If `verify_apply_safety` returns `True` AND the envelope was `mode="apply"`: execute the command.
3. If the envelope was `mode="dry-run"`: skip execution; record the precheck result.
4. Always call `hitl.record_apply_outcome(approval, before=..., after=..., applied=<bool>, reason=<enum>)` after any of the above. This writes the structured row to `<repo>/.ai-playbook/incidents.jsonl` with `request_id` correlation.

Reasons enum:

| Reason | When |
|---|---|
| `applied` | Command executed successfully. |
| `dry-run-skip` | `mode="dry-run"` — precheck ran, command not executed. |
| `already-converged` | Idempotency precheck reported `would_change=False`; no envelope sent if pre-checked before request_approval, or skipped post-approval if state changed in between. |
| `human-rejected` | `ApprovalResult.approved=False`. |
| `timeout` | `ApprovalResult.approved=None` (24 h or `max_approval_age_seconds` exceeded). |
| `exact-match-failed` | `verify_apply_safety` raised `ApplyFixMismatchError`. Counts as a safety event; emits `error`-level notification. |
| `executor-failed` | The command executed but its exit code was non-zero. before/after still captured. |

---

## Exact-match invariant

The bytes the workflow executes MUST equal the bytes captured in `command_preview` at `request_approval` time. No string formatting, no env-var substitution, no quoting changes between propose and apply.

Why: time-of-check vs time-of-use bugs are the canonical class of "approved X, executed Y" disasters. The exact-match check is the primary safety net.

Implementation: `verify_apply_safety` reads the resolved envelope from `<repo>/.ai-playbook/approvals-resolved.jsonl` (which echoes the original `command_preview` from the pending file), and does `expected == approved.command_preview`. Strict byte equality.

If the workflow needs to substitute a value at apply time (e.g., the host changes between propose and apply — should never happen but guard anyway), it MUST re-call `request_approval` with the new `command_preview`. No "almost matches" path exists.

---

## Idempotency contract

Every workflow that requests `mode="apply"` MUST supply a precheck callable to `verify_apply_safety`:

```python
def idempotency_check() -> bool:
    """Return True if executing the command would change state, else False."""
```

Examples:

| Workflow step | Precheck |
|---|---|
| `docker builder prune` | Run `docker builder prune --dry-run` (or `docker system df`) and check if any reclaimable space exists. Return True if > 100 MB reclaimable. |
| `etcdctl defrag` | Run `etcdctl endpoint status --write-out=json` and compare `dbSize` vs `dbSizeInUse`. Return True if `dbSize > dbSizeInUse * 1.1`. |
| `apt-get upgrade <package>` | `apt list --upgradable 2>/dev/null \| grep -q <package>`. Return True on match. |

The precheck is REQUIRED. Workflows without idempotency cannot use `mode="apply"` — they must either find a way to make the action idempotent, or stay in `mode="dry-run"` and surface the action via the dashboard/Telegram for a human to apply manually.

---

## Identity binding

Resolutions to approval requests are written to `<repo>/.ai-playbook/approvals-resolved.jsonl` ONLY by sources whose identity is bound in env:

- `TELEGRAM_HITL_ARTURO_CHAT_ID` — the only Telegram chat ID whose callback presses are honored.
- `WA_HITL_ARTURO_E164` — the only WhatsApp number whose replies are routed to Hermes for NL parsing.
- `HITL_FILE_QUEUE_ENABLED=1` — when set, manually-appended lines to `approvals-resolved.jsonl` (offline / test mode) are honored. Off by default in prod.

Resolutions arriving from any other identity:

1. NEVER appear in `approvals-resolved.jsonl` (the channel adapter rejects them at the boundary).
2. Are audit-logged via `notify.py` event `hitl.identity.rejected` at `warn` severity, recording the attempted chat ID / phone number, the `request_id` they tried to resolve, and the timestamp.
3. Do NOT count as approved or rejected from the workflow's perspective — the workflow keeps polling until a valid identity resolves or the timeout expires.

Multi-signer quorum is NOT supported in v1.0.0. The role-matrix in `break-glass.md` will evolve when a second signer exists; until then, Arturo is the sole canonical approver.

---

## Logging contract

Every apply attempt — success, dry-run-skip, already-converged, human-rejected, timeout, exact-match-failed, executor-failed — writes a structured row to `<repo>/.ai-playbook/incidents.jsonl`. Shape:

```json
{
  "ts": "2026-04-29T19:42:13.847Z",
  "kind": "hitl.apply.outcome",
  "request_id": "uuid-v4",
  "workflow": "vps_maintainer",
  "action": "vps-cleanup-docker-prune",
  "host": "consumer-d-prod",
  "applied": true,
  "reason": "applied",
  "command_preview": "docker builder prune -af",
  "idempotency_key": "vps_maintainer-docker-prune-consumer-d-prod-2026-04-29",
  "approval": {
    "signer": "telegram:arturo-chat-id",
    "approved_at": "2026-04-29T19:41:55.123Z",
    "channel": "telegram"
  },
  "before": {"disk_used_pct": 80, "build_cache_gb": 35.6},
  "after": {"disk_used_pct": 59, "build_cache_gb": 0},
  "duration_seconds": 18.7
}
```

`request_id` is the trace correlation key. Other systems (`consumer-d_ops.tools.recent_incidents`, dashboard, future Hindsight retains) consume this log.

---

## Risk-tier rule

| Risk | HITL required even on `--cron` autonomous run? | Rationale |
|---|---|---|
| `low` | No | Routine, reversible, predictable (e.g., `journalctl --vacuum-time=7d`). |
| `medium` | No | Slightly more impactful but reversible (e.g., `docker builder prune -af`). |
| `high` | **Yes — always** | Container restart, irreversible deletion, or sustained downtime > 30 s. The cron schedule is not blanket approval. |

Workflows with mixed-risk steps (e.g., `vps_maintainer.py` has 4 low/medium + 1 high) split: low/medium steps are pre-approved by the cron schedule for autonomous tier; high steps still emit a HITL envelope on every cron run, even if a human is unlikely to be at their phone. If the high step times out unanswered, the cron run finishes the low/medium work and exits cleanly with `partial-cron-run` status logged.

---

## Helpers (Python API)

Workflows interact with this contract via three helpers in `langgraph_aiops/workflows/hitl.py`:

```python
def request_approval(*, action, payload, severity, command_preview=None,
                     idempotency_key=None, reversal_hint=None, risk=None,
                     mode="dry-run", max_approval_age_seconds=None,
                     timeout_seconds=24*60*60, poll_interval_seconds=5.0,
                     clock=None) -> ApprovalResult:
    """Block until approval resolved or timeout. Channel-routed."""

def verify_apply_safety(approval: ApprovalResult, *,
                        expected_command: str,
                        idempotency_check: Callable[[], bool]) -> bool:
    """Return True iff exact-match + idempotency-would-change. Raise ApplyFixMismatchError on mismatch."""

def record_apply_outcome(approval: ApprovalResult, *,
                         before: dict, after: dict,
                         applied: bool, reason: str,
                         duration_seconds: float | None = None,
                         output: str | None = None,
                         error: str | None = None) -> None:
    """Append the structured outcome row to incidents.jsonl."""
```

`ApprovalResult` adds two fields beyond v0: `command_preview` (echo of envelope) and `signer_channel` (one of `telegram`, `whatsapp`, `file-queue`).

---

## Deprecation: `NotImplementedError` guards

The previous-generation guards in `hitl.py:128–133` and `tools.py:516–518` raised `NotImplementedError("APPLY_FIX mode deferred to T29")` when `APPLY_FIX_MODE=apply`. As of v1.0.0 of this spec:

- `hitl.py` no longer raises on `APPLY_FIX_MODE=apply`. It honors the envelope mode field instead. Tests previously asserting the raise (`test_workflows.py::test_hitl_refuses_apply_mode`) are updated to assert the new contract.
- `tools.py:suggest_remediation` no longer raises on `APPLY_FIX_MODE=apply`. It returns propose-only candidates with a `mode_note: "use workflow.apply_with_hitl to execute"` hint. The actual apply happens in workflows, not in `consumer-d_ops.tools` (which stays read-only by design).

The string `"T29"` should not appear in any new code. References to a non-existent `break-glass.md §propose-only ceiling` have been removed; this spec is the canonical reference instead.

---

## Cross-references

- [break-glass.md](break-glass.md) — sibling spec for CLI gate overrides. Different scope.
- [notification-policy.md](notification-policy.md) — channel routing for the envelopes. Adds `hitl.identity.rejected` event at `warn` (registered in §3.1 channel matrix).
- [memory-hierarchy.md](memory-hierarchy.md) — `incidents.jsonl` is a Tier 2 (project) durable store consumed by `consumer-d_ops.tools.recent_incidents`.
- [enforcement-status.md](enforcement-status.md) — this spec ships at `✅ wired` once Change A's tests land.
- [error-message-standard.md](error-message-standard.md) — `ApplyFixMismatchError` follows the canonical WHY/WHERE/FIX/OVERRIDE shape (`OVERRIDE: none — exact-match is non-negotiable`).
- `consumer-d/langgraph-aiops/LEGACY_MIGRATION.md` — autonomous-tier exceptions (`watchdogs.py`, `vps_maintainer.py`).
