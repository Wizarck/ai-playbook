---
change_id: jira-ticket-standard
tracker_id: GPLO-1350
status: proposed
---

# Enforce the ticket-authoring standard

## Why

GPLO tickets are supposed to carry a fixed structure — an A/B/C test plan and
metrics with a declared type — and that has depended on manual discipline, so it
drifts. Measured on the sixteen tickets created on 2026-08-02: **1 conformant, 6%**.
The only one that passes is GPLO-1350 itself, the ticket asking for the standard.
The other fifteen include three filed carefully hours earlier in the same session.
Careful authors drift too, because there was nothing to drift against.

## What changes

One contract, `specs/jira-ticket-standard.yaml`, read by one validator,
`scripts/rules/_ticket_kit.py`, used by four consumers:

1. **PreToolUse hook** (`jira-ticket-standard.rule.py::pretooluse`) — denies a
   non-conformant Atlassian MCP `createJiraIssue`/`editJiraIssue`. This is the
   majority path and the only mechanically gateable one that survives context
   compaction: a rule doc and a skill are advice that fades, a hook re-fires per
   call with no memory of the last.
2. **`create_jira_issue()`** — validates pre-POST and raises a typed
   `TicketStandardError` instead of the old `(None, reason)`, which made "the
   ticket is malformed" indistinguishable from "Jira timed out".
3. **`check` / `explain` / `validate` CLI** — the detective half, ratcheted by
   `--since <date>` so the gate bites for new work without failing on a legacy
   backlog nobody is rewriting.
4. **`/jira-ticket` skill** — assistive: pre-fills from session context and
   proposes the metric type, rather than presenting a blank form that only says no.

Also fixes a latent bug found on the way: `create_jira_issue()` posted the whole
markdown body as ONE ADF text node, so `## Métricas` was stored as literal
characters and every sync-created ticket was structureless in Jira. Now emits real
`heading` nodes; the validator reads both dialects so the existing backlog still
parses.

## Deliberate non-goals

- **Rewriting the 126 open legacy tickets.** They are measured and reported as
  their own cohort.
- **Jira UI layers** — Automation `validate-on-create` and required custom fields.
  Originally deferred as "configuration only Arturo can apply"; **dropped outright
  on 2026-08-02** once the intent was stated plainly: the standard exists to bind
  agents, which write tickets at machine speed with no memory across calls, not
  people choosing what to type. Two costs settled it — required fields in a
  team-managed project apply to the REST API as well, so enabling them breaks
  `issue_sync.py`, and an Automation rule that only comments is a notification, not
  a gate. Neither buys anything the hook does not already provide on the path that
  produces the volume.
- **A conformance baseline in CI.** Report-only until the number is trusted; a gate
  that lands red on a backlog is a gate someone switches off.

## Residual risk, stated rather than discovered later

The hook cannot cover a claude.ai web session (no local hooks) or `curl` with the
sync credentials. `check` is the compensating control for both, and a
non-conformant ticket with no corresponding hook telemetry event is an
attributable bypass.
