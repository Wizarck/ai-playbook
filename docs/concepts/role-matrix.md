---
schema: concept/v1
slug: role-matrix
title: Role Matrix
summary: |
  Four people-roles govern who can do what in the ai-playbook repo. The roles
  are orthogonal to the process-roles named in agent-contract.md (k8s
  ServiceAccounts, subagent contracts) — see §5 for the mapping.
last_validated: "2026-05-19"
---

# Role Matrix

Four people-roles govern who can do what in the ai-playbook repo. The roles are orthogonal to the process-roles named in [agent-contract.md](agent-contract.md) (k8s ServiceAccounts, subagent contracts) — see §5 for the mapping.

---

## 1. Maintainer

**Today:** sole maintainer (see [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for identity).

**Rights.**

- Merge to `master` / cut releases / pin semver tags.
- RFC final say — write the `Decided:` line that closes an RFC.
- Unilateral docs-only / typo-fix merges without RFC (per `contributing.md` §3.1).
- Bypass PR review on hotfixes tagged `fix!` with a `Why:` line in the commit body (rare; break-glass still applies per [break-glass.md](../rules/break-glass.rule.md)).

**Responsibilities.**

- Weekly triage (open issues, open RFCs, open PRs) per `contributing.md` §3.2 SLAs.
- Run the monthly retro per [retrospective-cadence.md](retrospective-cadence.md) §1.
- Keep `specs/*` internally consistent (no contradictory cross-references).
- Own the incident-response contract until IR activates (see [incident-response.md](incident-response.md)).
- Approve post-mortems per [post-mortem.md](post-mortem.md).

**Audit trail.**

- Every merge produces a git commit with maintainer's email.
- Every RFC decision leaves a `Decided:` line in the RFC file, signed (email + date).
- Every break-glass use is logged to `.ai-playbook/overrides.log` (same audit as any other role).

**How to become this role.**

- At v0.1.0, closed set (the maintainer only).
- v0.2+: the maintainer may nominate a second maintainer via RFC. RFC must pass with explicit maintainer approval (solo majority at first) and a 7-day public comment window. Once 2+ maintainers exist, nominations require consensus.
- When the team grows past ~5 active contributors, the role splits into a **standing maintainer committee** with quorum rules (`contributing.md` §1).

---

## 2. Reviewer

**Today:** empty (no external trusted reviewers yet).

**Rights.**

- Approve PRs (GitHub "Approve" review).
- Request changes (GitHub "Request changes" review).
- Cannot merge to `master`.
- Can convert issues to RFCs when the scope warrants.

**Responsibilities.**

- Review within 7 days of PR-request or RFC-request tag.
- Cite sources on every structural comment per global CLAUDE.md principle #7 (`Jira: PROJ-N`, `GH: #N`, ADR reference — not intermediaries).
- Use the verdict contract ([verdict-contract.md](../rules/verdict-contract.rule.md)) for formal reviews of artefacts.
- Flag scope creep in PRs rather than silently approving.

**Audit trail.**

- Every review is a GitHub PR review record (timestamped, attributed).
- Formal review artefacts (worker→QA loops, parallel review) follow [verdict-contract.md](../rules/verdict-contract.rule.md) and produce committed markdown under `reports/reviews/` on the consumer repo.

**How to become this role.**

- Maintainer-nominated via a CODEOWNERS-style PR (`.github/CODEOWNERS`-equivalent lands alongside T22). Nomination states the scope (e.g. "reviewer for `scripts/mcp/**`").
- Scoped reviewers are valid — a reviewer for MCP tooling is not automatically a reviewer for governance docs.
- Consumers of the playbook (see §4) do **not** automatically get reviewer rights on the playbook itself; they must be named individually.

---

## 3. Contributor

**Today:** any dev with a GitHub account who submits a PR or issue to this repo. No approval required to contribute.

**Rights.**

- Open issues, open RFCs, submit PRs against `master`.
- Append bullets to ../FEEDBACK.md without ceremony.
- Ask for clarification in any thread.

**Responsibilities.**

- Follow `contributing.md` §4 code style (Conventional Commits, Ruff, type hints, pathlib).
- Ship tests with every script (`contributing.md` §5; no untested script merges).
- Stay in scope per the OpenSpec proposal or RFC driving the work — do not gold-plate.
- Use `--force-with-reason` responsibly if an override is needed; the log is audited monthly per [break-glass.md](../rules/break-glass.rule.md) §4.

**Audit trail.**

- Every contribution produces a git commit with contributor email.
- Every FEEDBACK.md bullet carries the contributor's handle.
- Contribution attribution stays in git history forever; identity handling per [data-retention.md](data-retention.md) §"Right to deletion".

**How to become this role.**

- Clone the repo, open a PR. No onboarding required.
- First PR gets an extra-careful review by the maintainer (sanity check on tone, scope, and style) — not a gate, a kindness.

---

## 4. Consumer-only

**Today:** team devs on projects that consume the playbook as a submodule but never edit it (consumer-c contributors, future consumer-d team devs, future external consumer orgs).

**Rights.**

- **Read** the playbook specs.
- **Inherit** via `git submodule add` + `inherits_from: [github.com/Wizarck/ai-playbook@<pin>]` in their project AGENTS.md.
- **File consumer-side issues** in their own project repo ("we need X from the playbook").
- **Pin** the submodule to any semver tag in their consumer repo.
- **Full rights** on their own project repo (subject to that repo's governance, which is out of scope here).

**Responsibilities.**

- Pin the submodule to a semver tag — never track `main` directly (enforced by [migration-guide.md](migration-guide.md) "Common pitfalls" #1).
- Do NOT hand-patch `.ai-playbook/` inside a consumer repo. If a fix is needed, open a PR here instead. Manual patches in a consumer submodule are a drift signal that `scripts/drift_check.py` surfaces.
- Report gaps via their own project maintainer, who can escalate as an upstream issue.

**Audit trail.**

- No audit trail inside this repo (consumer-only devs never touch it).
- Consumer repos' own audit trails are that repo's concern.

**How to become this role.**

- Work on a project that consumes the playbook. No action on this repo needed.
- Consumer-only is the **majority** audience — most readers of `specs/*` will never file a PR here.

---

## 5. Mapping to k8s RBAC (deferred)

This spec names **people-roles** (humans with repo-level rights). The ServiceAccount / workload-identity model referenced in [agent-contract.md](agent-contract.md) names **process-roles** (what an agent or service can do at runtime). The two are orthogonal:

- A maintainer (people-role) is not automatically a k8s cluster-admin (process-role).
- A `hermes` ServiceAccount (process-role) has no corresponding people-role.

Mapping specifics are deferred until a second human has production cluster access. At v0.1.0, the maintainer is the sole cluster-admin on every cluster; the mapping question does not arise.

When IR activates (see [incident-response.md](incident-response.md) triggers) or the first non-maintainer operator lands, this section expands into a real table:

| People-role | k8s role(s) | Namespaces | Status |
|---|---|---|---|
| Maintainer | `cluster-admin` | `*` | active (maintainer only at v1.0.0) |
| Reviewer | `view` on prod + `edit` on staging | `prod-*`, `staging-*` | spec-only; activates when a Reviewer lands |
| Contributor | `view` on dev | `dev-*` | spec-only; activates when a Contributor lands |
| Consumer-only | none | none | spec-only |

Until then, the maintainer is sole cluster admin. Break-glass for `kubectl` access is logged outside this repo per the ops runbook in `consumer-d/docs/operations/`.

---

## 6. Cross-references

- [../../CONTRIBUTING.md](../../CONTRIBUTING.md) — public-facing contribution summary; this file is normative.
- [agent-contract.md](agent-contract.md) — process-role model for subagents (not people).
- [break-glass.md](../rules/break-glass.rule.md) — override contract applies equally across roles; no role is exempt from logging.
- [incident-response.md](incident-response.md) — activation triggers that expand §5 into a real mapping.
- [data-retention.md](data-retention.md) §"Right to deletion" — how contributor identity is handled when they leave.
- [post-mortem.md](post-mortem.md) — review-flow after SEV0/SEV1 incidents names responder + reviewer roles.
