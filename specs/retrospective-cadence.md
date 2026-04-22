# retrospective-cadence.md

> **Status**: stub, v0.1.0. Populated in **T14i**.

## Cadence

| Trigger | Cadence | Participants | Focus |
|---|---|---|---|
| Post-archive | Every `openspec archive`. | Main agent + Arturo (review). | Did worker→QA cycles hit 2+ rework? Any `❓ CLARIFICATION` blocks? |
| Weekly | Every Monday. | Arturo. | FEEDBACK.md gripes, break-glass usages, cost report (T14f). |
| Monthly | First Monday of month. | Arturo. | Lifecycle-check (T14i): stale changes, outdated memories, drift findings. |

## Outputs

- Post-archive: short "lessons" note appended to the change's archive folder.
- Weekly: triage of FEEDBACK.md → issues/RFCs. Update `gotchas` sections in consumer `AGENTS.md` if a pattern emerged.
- Monthly: Arturo decides: promote skills to playbook, deprecate stale specs, refresh runbook.

## Populated in T14i

Templates for each cadence, the `scripts/lifecycle_check.py` automation that emits the monthly report, and the dashboard widget (T19) that surfaces retro backlog.
