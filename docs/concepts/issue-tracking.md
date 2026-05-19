---
schema: concept/v1
slug: issue-tracking
title: Issue Tracking
summary: |
  How user stories, features, bugs, and releases flow through two tracker
  surfaces: - Jira — enterprise / private work (Paperclip tenants, consumer-c
  Enterprise, any closed-source SaaS). - GitHub Projects + Issues — community
  / open-source work (consumer-c, awesome-paperclip,…
last_validated: "2026-05-19"
---

# Issue Tracking

How user stories, features, bugs, and releases flow through **two** tracker surfaces:

- **Jira** — enterprise / private work (Paperclip tenants, consumer-c Enterprise, any closed-source SaaS).
- **GitHub Projects + Issues** — community / open-source work (consumer-c, awesome-paperclip, any public repo under the org).

The split is intentional and mirrors the dual-repo strategy already documented in
`consumer-c/AGENTS.md` §4 and ADR-010 (community AGPL-3.0 vs enterprise private). This spec
extends that split from **issues** to full **product planning** (user stories → features →
releases) so the two audiences stay on surfaces they expect.

---

## 1. Which surface for which repo

Decision rule (apply to every repo under the org):

| Repo class | Examples | Planning surface | Release surface | Ticket prefix |
|---|---|---|---|---|
| Public AGPL-3.0 (community) | `consumer-c`, `awesome-paperclip`, `paperclip-mcp` | **GitHub Project** (org-level board) + GitHub Issues | **GitHub Release** per semver tag | `#<issue-number>` |
| Private with public OS counterpart (dual-repo) | `consumer-c Enterprise` (mirrors consumer-c), Paperclip enterprise tenants (mirror awesome-paperclip stack) | **Jira** (`atlassian-consumer-a` tenant) | **Jira release version** + git tag in private repo | `PROJ-<number>` |
| Private standalone (no public counterpart) | `consumer-d`, `consumer-b`, `consumer-b-hub`, `ESILDA`, future closed-source SaaS without an OSS half | **GitHub Project** (per-repo board) + GitHub Issues | git tag + optional GitHub Release | `#<issue-number>` |
| Tooling / lightweight | `ai-playbook`, `consumer-d-skills`, `skills-manager-personal`, `diakopa`, `GTM-Helper` | GitHub Issues (no project board) | git tag only | `#<issue-number>` |

**Rule of thumb**: Jira is reserved for the *enterprise half* of a dual-repo (community public + enterprise private) so the two audiences live on the surface they expect. A private repo without a public counterpart has no audience split → GH is sufficient. Per-repo project boards (vs the org-level board) are used for private standalone repos so the work stays scoped to the repo's collaborators.

Mixed-mode repos (the maintainer runs some public + some private inside the same org) follow the
visibility of the repo where the work lands; never straddle. A feature that ships in
`consumer-c` (public) AND `consumer-c Enterprise` (private) gets two tickets — one per surface —
linked to each other by URL in the description.

---

## 2. The BMAD+OpenSpec ↔ tracker loop

BMAD Discovery produces PRDs; OpenSpec implements changes. Trackers are the **product-side
record** that outlives any single change.

### 2.1 During BMAD Discovery

| BMAD artefact | Tracker shape |
|---|---|
| PRD (`docs/prd*.md`) | One **epic** (Jira) or **milestone** (GH) with `prd` label. The epic's description links back to the PRD file by commit SHA. |
| Persona / JTBD | No new ticket — lives in `docs/personas-jtbd.md`. The epic references it. |
| ADR (`docs/architecture-decisions.md`) | One **decision-record ticket** per ADR (Jira issue type `Decision`, or GH Issue labelled `adr`). Links to the ADR file + date. |
| Slicing output (list of proposed OpenSpec changes) | One **user story** per proposed change, under the epic/milestone. Status starts `Backlog`. |

### 2.2 During OpenSpec Implementation

For **each** OpenSpec change:

1. Create (or link) one ticket per change: `ai-playbook/scripts/issue_sync.py` automates this
   (see §4). Status: `In progress → In review → Done`.
2. The ticket ID goes in the change's `proposal.md` frontmatter as `tracker_id: PROJ-42`
   (Jira) or `tracker_issue: 42` (GH).
3. QA verdicts per `verdict-contract.md` map to ticket transitions:
   - `✅ APPROVED` → ticket moves to `In review`.
   - `⚠️ ISSUES FOUND (iter N)` → ticket stays in `In progress`; add a comment summarising.
   - `❓ CLARIFICATION NEEDED` → ticket moves to `Blocked`; labels `blocked-by-spec`.
4. `openspec archive` → ticket moves to `Done`, references the archive commit SHA.

### 2.3 Cross-references in source

Every commit message that closes a ticket cites it:

- Jira: `PROJ-42:` subject prefix (Atlassian's automation links commits to the issue).
- GH: `Closes #42` in the commit body.

The pre-commit hook does NOT enforce this today (deferred); `scripts/verdict_lint.py --shape
commit-message` lands later if friction warrants.

---

## 3. Releases

### 3.1 Community (GitHub)

- **Trigger**: merge to `main` that bumps semver tag.
- **Surface**: GitHub Release auto-generated from the tag. Release notes = relevant
  `CHANGELOG.md` section.
- **Assets**: `consumer-c` publishes `@consumer-c/types` to npm from the release; `ai-playbook`
  publishes nothing (consumed via git submodule).
- **Timeline**: semver discipline — breaking change needs major bump; `rollout-strategy.md`
  applies to every public repo too.

### 3.2 Enterprise (Jira)

- **Trigger**: same semver tag; release workflow creates a Jira "Release" version under the
  relevant project (`PROJ`, `consumer-b`, etc.) AND marks all tickets in that fixVersion as
  Released.
- **Surface**: Jira's native Release tab, plus a private-repo git tag.
- **Assets**: Docker images pushed to `ghcr.io/wizarck/<service>:<tag>`; `helm/consumer-d-stack`
  chart version bump; internal changelog email via the enterprise notification channel.
- **Timeline**: calendar-driven (monthly or quarterly) — enterprise releases batch changes;
  community releases can be lightweight per-feature.

### 3.3 Dual releases

Work that lands in BOTH community + enterprise (rare but possible — e.g. a shared library)
cuts TWO releases on the same semver tag. Keep commit SHAs identical across repos when the
code is truly shared.

---

## 4. Automation (LIVE as of 2026-04-23; pull-model contract from v0.19.0+)

Zero-touch automation — no human intervention in the happy path. See
[docs/concepts/zero-touch-automation.md](zero-touch-automation.md) for the end-to-end flow.

**Configuration source (v0.19.0+)**: each consumer declares its tracker in
its OWN `AGENTS.md` frontmatter. The playbook holds no central registry of
consumers — that registry (`consumers.yaml`) was retired with the push
pipeline. Required frontmatter keys:

```yaml
---
schema: agents-md/v1
project: <consumer-name>
tracker_kind: github | jira     # required
jira_project: PROJ              # required iff tracker_kind == jira
personal: true | false          # optional; always GH Issues regardless of tracker_kind
---
```

- **`scripts/issue_sync.py`** — scans `openspec/changes/*/proposal.md`, creates Jira issues
  (private repos via Atlassian REST / `atlassian-consumer-a` tenant) OR GH Issues + optional GH
  Project add (public repos). Reads `tracker_kind`/`jira_project` from the consumer's
  own AGENTS.md frontmatter. Embeds `tracker_id: PROJ-42` (Jira) or `tracker_issue: 42`
  (GitHub) in the proposal frontmatter via a follow-up commit. Idempotent; failed creates
  queue to `.ai-playbook/issue_sync_queue.jsonl` for retry. Wired as
  `.github/workflows/issue-sync.yml` firing on PR merge into main/master.

- **`scripts/release_cut.py`** — on semver tag push, parses CHANGELOG, collects archived
  OpenSpec changes since the previous tag, creates GH Release (public) OR Jira fixVersion
  (private), marks associated tracker ids as `Released`. Refuses to overwrite existing GH
  Releases. Wired as `.github/workflows/release-cut.yml` firing on `v*.*.*` tag push.

- **`scripts/notify.py`** — shared emitter; every step in the two scripts above calls it.
  Writes JSONL at `.ai-playbook/notifications.jsonl` (dashboard bell reads it via SSE) and
  emails via SMTP for severity ≥ `warn`. Rate-limited (≤5 info/min per event+actor, 60s
  dedup window). Stdlib-only (urllib + smtplib); zero runtime deps added.

- **`scripts/telemetry/report.py (absorbed in Slice 6)`** — monthly retro already flags `tracker_id-less` archived
  changes; these get emitted as `warn` notifications.

Consumer repos inherit the two workflows via `templates/new-project/.github/workflows/*.tmpl`
copied by `scripts/bootstrap.py`.

**Manual override** for any blocked gate: `--force-with-reason="<≥10 chars>"` per
[break-glass.md](../rules/break-glass.rule.md). Every override emits a `warn` notification and lands in
`.ai-playbook/overrides.log`.

### Required env vars

Full catalogue in [env-vars.md](env-vars.md) — new sections: `SMTP_*`, `ATLASSIAN_*`,
`AIPLAYBOOK_GH_PROJECT_NUMBER`, `AIPLAYBOOK_JIRA_DEFAULT_PROJECT`,
`AIPLAYBOOK_NOTIFICATIONS_*`. All credentials live in SOPS; GitHub Actions pull from repo
secrets mirrored by the same names.

---

## 5. MCP surfaces the playbook already exposes

From `mcp-servers-base.yaml` + what's live on the VPS:

- `atlassian-consumer-a` — Jira read/write for the consumer-a tenant (PROJ + consumer-b + whatever
  lives there). Tools: `searchJiraIssuesUsingJql`, `createJiraIssue`, `editJiraIssue`,
  `transitionJiraIssue`, `addCommentToJiraIssue`, `getTransitionsForJiraIssue`. Already used
  by Hermes for operational queries.
- `gh` CLI (not MCP; wrapped by `scripts/openspec_validate.py`, `scripts/skills_registry.py`,
  and any contributor). Has `repo`, `issue`, `pr`, `search`, and `project` subcommands.

For public-repo issue creation: `gh issue create --repo Wizarck/consumer-c --title ... --body
...` + `gh project item-add <project-number> --owner Wizarck --url <issue-url>`.

---

## 6. Anti-patterns

- **Ticket-in-readme** — tracking work inside `CHANGELOG.md` or ad-hoc lists. Every non-trivial
  piece of work has a tracker id. If it's too small to ticket, it goes in `FEEDBACK.md`.
- **Cross-surface duplication** — opening the same ticket in Jira AND GH for the same repo.
  One surface per repo, always. Public-mirror PRs that cross-reference a private ticket are OK.
- **Orphan epics** — creating a Jira epic with no PRD, or a GH milestone with no source
  artefact in the repo. The BMAD output is the source of truth; the tracker is the projection.
- **Closing via archive without tracker update** — `openspec archive` runs, ticket stays open.
  The monthly lifecycle check flags this.
- **Release without CHANGELOG** — every tag has a CHANGELOG entry; `rollout-strategy.md`
  already forbids CHANGELOG-only breaks but also forbids release-only (silent) changes.

---

## 7. Cross-references

- `docs/concepts/runbook-bmad-openspec.md` — phase map + HITL gates; this spec is the tracker projection.
- `docs/concepts/rollout-strategy.md` — release sequencing; this spec names the surfaces.
- `docs/concepts/retrospective-cadence.md` — monthly lifecycle check flags orphan tickets.
- `docs/rules/verdict-contract.rule.md` — QA verdict → ticket transition mapping.
- `docs/tutorials/07-fork-inventory.md` — determines which repos are public vs private.
- `consumer-c/AGENTS.md` §4 + ADR-010 — dual-repo strategy (origin of the split this spec
  extends).
