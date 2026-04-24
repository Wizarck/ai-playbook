# post-mortem.md

> **Status**: v1.0.0. Contract for post-mortem artefacts produced after an S1 incident or a SYSTEMIC verdict escalation. Pairs with [../templates/post-mortem.md.tmpl](../templates/post-mortem.md.tmpl).

A post-mortem is the artefact that turns a painful event into a durable improvement. Blameless by contract, systems-focused by construction. A post-mortem without action items is not a post-mortem — it is a confession.

---

## 1. When required

A post-mortem MUST be produced when **any** of the following is true:

- **S1 incident** (per [verdict-contract.md](verdict-contract.md) §2):
  - Data loss (irreversible corruption, destructive merge, dropped DB).
  - Secret exposure (plaintext secret in a commit, log, or off-box copy).
  - Prod outage > 15 minutes (user-visible downtime on any service listed in [incident-response.md](incident-response.md)).
  - Any CI revert — a landed PR that had to be reverted for correctness/safety, regardless of blast radius.
- **SYSTEMIC verdict escalation** per [verdict-contract.md](verdict-contract.md) §3 — when a worker→QA loop halts with `❓ CLARIFICATION NEEDED` because the same S1/S2 finding recurred twice. The post-mortem investigates the process/spec gap, not the individual finding.
- **Security event** — confirmed unauthorised access, confirmed data exfiltration, confirmed key compromise. Regardless of whether downtime ensued.

A post-mortem is NOT required for:

- Routine failed CI runs that got fixed in the next commit.
- Flaky tests that passed on retry.
- A worker→QA loop that converged in ≤2 iterations with a clean approval.
- A break-glass invocation that flowed through the normal override contract. (But chronic break-glass on the same gate IS a systemic flag, surfaced by the monthly retro, and may prompt a post-mortem at maintainer discretion.)

---

## 2. Owner

- **Incident responder** writes the post-mortem. At v0.1.0, that is Arturo for every incident.
- When [incident-response.md](incident-response.md) activates, the post-mortem owner is the primary responder named in that event's on-call record.

---

## 3. Due

Within **7 days** of incident resolution. "Resolution" means: the service is back up OR the systemic gap is named (for SYSTEMIC escalations).

Missing the 7-day window is a systemic flag itself, surfaced in the next monthly retro per [retrospective-cadence.md](retrospective-cadence.md) §4 lifecycle-check output.

---

## 4. Where

Post-mortems land at:

```
<repo>/reports/post-mortems/<YYYY-MM-DD>-<slug>.md
```

Where:

- `<YYYY-MM-DD>` is the incident's start date (UTC).
- `<slug>` is a 3–6 word kebab-case identifier capturing the affected service + nature (`hermes-queue-backlog`, `secret-leak-tracing-pr`).

Multiple post-mortems on the same day get distinct slugs; no numeric suffixes. The file is committed alongside the fix PR (or in a follow-up PR if urgent).

---

## 5. Template

Authored from [../templates/post-mortem.md.tmpl](../templates/post-mortem.md.tmpl). Frontmatter fields are the identity marker; lifecycle-check rejects post-mortems that do not carry the template's frontmatter.

---

## 6. Review

- **Reviewer(s).** Maintainer (always) + any affected consumer maintainer (when the incident touched a consumer repo).
- **Cadence.** Within 7 days of the post-mortem draft landing. Reviewer leaves comments in the PR; author addresses; merge when reviewer approves.
- **Blameless contract.** The review is for systems, not people. Any review comment framing an action as "X person should do Y better" is rejected; reframe as "the system allowed this; we change the system."
- **Verdict.** Every post-mortem ends with a verdict line per [verdict-contract.md](verdict-contract.md) §1. `✅ APPROVED` means: reviewer agrees the cause-analysis is sound AND the action items are concrete enough to execute.

---

## 7. Outcome

A post-mortem is considered `closed` only when **at least one** of the following landed as a direct consequence:

- **A spec update.** The triggering gap is now documented (new row in a table, new section, a clarifying example).
- **A guard script.** A new `scripts/*` check catches the same class of failure in pre-commit or CI.
- **A runbook update.** The service-level runbook has a new section covering this failure mode.
- **A tightened hook.** An existing pre-commit or CI check gets a stricter rule or wider file pattern.
- **A new doctor check.** [`scripts/doctor.py`](../scripts/doctor.py) gains a check for the prerequisite that was missing.

"Talked about it in the retro" is not an outcome. Every action item carries an assignee, a due date, and a tracking link (GH issue / PR / RFC / spec section). Action items without owner + due date + link are rejected by the reviewer.

---

## 8. Anti-patterns

- **Blame.** "Jane should have tested this." Rejected; reframe as "CI didn't catch this class of error; we add a check."
- **No action items.** The post-mortem lists contributing factors, then nothing follows. The next monthly surfaces the orphan.
- **Write-only.** Action items listed, none tracked, none closed by the next cadence. Lifecycle-check flags stale action items weekly.
- **Recycling previous wording.** Copy-pasted sections across post-mortems with no incident-specific detail (same cause-analysis string in 3 files = flag).
- **Post-mortem as PR approval.** Landing the fix PR without the post-mortem attached. The fix and the post-mortem are two artefacts; both are required.
- **S0 annotations in draft.** `S0` is retro-audit-only (per [verdict-contract.md](verdict-contract.md) §2.1); do not use it to annotate a rule as wrong in the post-mortem body. File an RFC or open an issue instead.
- **Private post-mortems.** Post-mortems are committed to the repo (same rationale as retros per [retrospective-cadence.md](retrospective-cadence.md) §3 — evidence stays visible).

---

## 9. Cross-references

- [verdict-contract.md](verdict-contract.md) — severity levels (S1 is the trigger) and SYSTEMIC escalation path.
- [retrospective-cadence.md](retrospective-cadence.md) — monthly retro surfaces open post-mortems and slippage on due dates.
- [incident-response.md](incident-response.md) — IR produces post-mortems; triggers named there also trigger this contract.
- [agentic-failures.md](agentic-failures.md) — a post-mortem on an agent-initiated S1 uses the failure-kind taxonomy in its cause analysis.
- [data-retention.md](data-retention.md) — post-mortems are retained forever.
- [role-matrix.md](role-matrix.md) — responder + reviewer rights live there.
- [break-glass.md](break-glass.md) §4 — break-glass usage during incident response is logged and referenced from the post-mortem timeline.
