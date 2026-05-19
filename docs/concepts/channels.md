# channels.md

> **Status**: v1.0.0.

The communication surfaces the playbook team uses, by purpose, with triage cadence and the line between ephemeral chat and load-bearing decisions. Written for the current state (Arturo solo) and the near-term growth horizon (0–3 months, 3–5 devs).

---

## 1. Current state (0–1 dev, Arturo solo)

Everything load-bearing lives in this repo:

- **Issues, PRs** — the formal ticketing surface.
- **RFCs** under [../rfcs/](../rfcs/) — breaking-change proposals.
- [../FEEDBACK.md](../FEEDBACK.md) — append-only low-friction gripe log.
- **Retros** under `reports/retros/` per [retrospective-cadence.md](retrospective-cadence.md).
- **Post-mortems** under `reports/post-mortems/` per `docs/concepts/post-mortem.md` (owned by Subagent A, T22 track).

There is **no Slack, no Discord, no team Telegram group** at v0.1.0. The Telegram bot configured in [notification-policy.md](notification-policy.md) §3 is Hermes, Arturo's personal assistant — it is NOT a team channel, MUST NOT be used to distribute team messages, and MUST NOT receive any decision that should land in a spec or RFC.

Rationale: at solo or near-solo, every surface that is not the repo is a surface that hides state. The audit trail wins.

---

## 2. Channels by purpose

| Need | Channel | Triage cadence | Notes |
|---|---|---|---|
| **Bug / feature request** | GitHub Issue | Weekly (Monday retro per [retrospective-cadence.md](retrospective-cadence.md) §1). | Label `bug`, `feat`, `docs`, or `spec`. Additional labels per [../docs/concepts/contributing.md](../docs/concepts/contributing.md) §3.3. |
| **Low-friction gripe / half-formed observation** | One bullet in [../FEEDBACK.md](../FEEDBACK.md) | Weekly (same Monday retro). | Append-only. Dated and signed per that file's header. Not for bugs with a clear repro — those go as issues. |
| **Breaking change proposal** | `rfcs/NNNN-<slug>.md` | Triage ≤7 days, decision ≤30 days per [../docs/concepts/contributing.md](../docs/concepts/contributing.md) §3.2. | Follows [rollout-strategy.md](rollout-strategy.md). |
| **Security vulnerability** | **Direct email** to maintainer (`23051550+Wizarck@users.noreply.github.com`). | Same day. | Never a public issue, never a public PR description, never a chat message. Post-mortem per §7 of rollout-strategy within 7 days of resolution. |
| **Lifecycle / SLO breach** | Auto-issue from `scripts/lifecycle_check.py` + a scheduled `drift-check.yml` GitHub Action. | Monthly retro per [retrospective-cadence.md](retrospective-cadence.md) §1. | Auto-labels `slo-breach`. Cross-ref [slos.md](slos.md) §3. |
| **Post-mortem** | `reports/post-mortems/<YYYY-MM-DD>-<slug>.md` | Committed within 7 days of incident resolution. | Template owned by `docs/concepts/post-mortem.md` (Subagent A, T22 track). Mandatory after any `rollout-strategy.md` §7 emergency bypass. |
| **Dev-facing runtime notification** | OTel → Langfuse / dashboard + Telegram (Arturo personal). | Per [notification-policy.md](notification-policy.md) §2 rate limits. | Telegram receives `warn` and `error` only, Arturo only. Team-wide notification channels land when §3 of this file activates. |
| **Release announcement** | [../CHANGELOG.md](../CHANGELOG.md) + GitHub Release. | Per release. | Semver. CHANGELOG entry ships in the same commit as the tag. See [rollout-strategy.md](rollout-strategy.md) §4. |

The table is the authority on *where* a given signal goes. When in doubt, default to GH Issue or FEEDBACK.md — they are the lowest-cost to audit.

---

## 3. Growing into a team (0–3 month horizon)

When the team crosses 2 devs, add:

- **Async team chat** — Slack or Discord. One channel to start (`#playbook-ops` if Slack, mirrored workspace-wide mention etiquette). Purpose: ephemeral coordination, not decisions.
- **Dedicated Telegram group for on-call** — separate from Arturo's personal Hermes chat. Receives `warn` + `error` for every registered consumer once the Slack webhook adapter lands per [notification-policy.md](notification-policy.md) §3.2.
- **Role matrix activation** — the CODEOWNERS-style reviewer entries defined in `docs/concepts/role-matrix.md` (owned by Subagent A, T22 track — **flag for race: ensure role-matrix.md's triage SLA rows align with this file's "Triage cadence" column**) turn on once there are named reviewers other than Arturo.
- **Promote maintainer-only notifications to team-wide** — only after the Slack/Telegram adapters are contract-tested against [notification-policy.md](notification-policy.md) §3.2.

Until the team crosses 2 devs, none of the above is turned on. Formal communication stays in this repo for audit. This is deliberate: premature channel proliferation is how a 1-dev project accretes 5 surfaces to check.

---

## 4. Anti-patterns

- **Slack-as-decision-record.** Decisions MUST land in a spec, an RFC, or an ADR. A Slack thread is ephemeral; a decision that exists only in Slack is lost the day a dev leaves or the workspace is downgraded. If it matters, it lands in the repo.
- **Issue-as-ticket-dump.** Opening an issue for every fleeting thought clogs the triage queue and hides real bugs. Use [../FEEDBACK.md](../FEEDBACK.md) for half-formed observations; promote to an issue when the shape is clear.
- **Direct-message-driven work.** Assigning work via DM creates a blame target (the DM'd individual) instead of a system target (the backlog). All work flows through issues, PRs, or RFCs. Exceptions: security (§2, direct email to maintainer, by design) and time-critical emergencies (followed by a retroactive issue within 24h).
- **Running retros in chat.** Retros are committed markdown per [retrospective-cadence.md](retrospective-cadence.md). A chat retro produces nothing `lifecycle_check.py` can read and nothing the next maintainer can learn from.
- **Silent private emails about public decisions.** If a decision affects every consumer, it belongs in a public issue, a public PR description, or a public RFC. Private emails are for the §2 security row and nothing else.
- **Using the Hermes Telegram bot for team messages.** It is a personal assistant channel. Team comms go through the channels this file lists.

---

## 5. Cross-references

- [notification-policy.md](notification-policy.md) — channel adapter contract; which levels route to which surfaces.
- [../docs/concepts/contributing.md](../docs/concepts/contributing.md) §3 — issue vs FEEDBACK vs RFC routing and SLAs.
- [rollout-strategy.md](rollout-strategy.md) — release announcement path, emergency bypass, post-mortem trigger.
- [retrospective-cadence.md](retrospective-cadence.md) — weekly/monthly triage cadences.
- `docs/concepts/role-matrix.md` — CODEOWNERS-style reviewer routing (Subagent A, T22 track).
- `docs/concepts/post-mortem.md` — post-mortem template (Subagent A, T22 track).
- [slos.md](slos.md) §3 — the `slo-breach` label and issue shape emitted by `lifecycle_check.py`.
