# zero-touch-automation.md

> **Status**: v1.0.0. Populated 2026-04-23. Realises the deferred automations of `docs/concepts/issue-tracking.md` §4.

This doc describes the **zero-touch loop** that takes OpenSpec changes and semver tags from repo events to tracker tickets, releases, and notifications — without human intervention in the happy path.

---

## 1. End-to-end flow

```
           ┌───────────────────────────────────────────────────────────┐
           │                 CONSUMER REPO (e.g. consumer-c)           │
           │                                                             │
           │   /opsx:propose  →  openspec/changes/<id>/proposal.md      │
           │                                                             │
           │   PR merged into main  ─────┐                                │
           │                              ▼                                │
           │                 .github/workflows/issue-sync.yml              │
           │                   (GitHub Actions runner)                    │
           │                              │                                │
           │                              ▼                                │
           │                 scripts/issue_sync.py                         │
           │                   reads projects registry                    │
           │                   ↓ private?   ↓ public?                     │
           │                   Jira REST   gh issue create                 │
           │                                gh project item-add            │
           │                              │                                │
           │                              ▼                                │
           │                 proposal.md embeds  tracker_id: PROJ-42       │
           │                 (follow-up commit)                           │
           └─────────────────────────────┬─────────────────────────────┘
                                         │
                                         ▼
              .ai-playbook/notifications.jsonl  (append on every step)
                                         │
                      ┌──────────────────┴──────────────────┐
                      ▼                                     ▼
              Dashboard bell 🔔                     SMTP email (warn+error)
              (consumer-d /api/notifications)      (via scripts/notify.py)
```

**Release flow** (mirror, on tag push):

```
git tag v0.3.0 && git push --tags
        │
        ▼
.github/workflows/release-cut.yml
scripts/release_cut.py
   ├── parse CHANGELOG section
   ├── collect archived OpenSpec changes since previous tag
   ├── public?  →  gh release create
   └── private? →  Jira fixVersion + mark issues Released
        │
        ▼
.ai-playbook/notifications.jsonl  →  dashboard bell + email
```

---

## 2. Zero-touch guarantees

| Step | Guarantee |
|---|---|
| New `proposal.md` lands on main | Workflow fires automatically on PR merge. |
| Tracker already present (`tracker_id`/`tracker_issue` in frontmatter) | `issue_sync` skips; emits `silent` notification. Idempotent. |
| Jira/GH API down | Sync queues to `.ai-playbook/issue_sync_queue.jsonl` for next run. Emits `warn`. Notifies Arturo. |
| Jira/GH credentials missing | Same as above — queue + `warn`. No hard fail unless `--strict`. |
| Tag pushed | Release auto-cut. GH Release + Jira fixVersion + notification. |
| Existing GH Release on that tag | Hard fail (prevents clobber). `error` notification. Arturo inspects. |
| Jira fixVersion already exists | No duplicate — reuses and marks issues Released. Idempotent. |
| Email disabled (no SMTP env) | JSONL still writes; dashboard bell still works; no email silently. |
| Rate-limit blast | ≤5 info/min per event+actor; overages coalesce into a single `burst` notification. |

Human intervention is needed ONLY when:
- The consumer repo is missing an `openspec/` folder (setup issue).
- An `error`-level notification fires (credential rotation, API breakage, file corruption).
- A monthly lifecycle-check flag surfaces a systemic drift.

---

## 3. Notification paths

### 3.1 Dashboard bell 🔔

- **Live**: `GET /api/stream/notifications` (SSE) tails `.ai-playbook/notifications.jsonl`.
- **Snapshot**: `GET /api/notifications?since=ISO&limit=50&min_severity=info`.
- **Badge count**: `GET /api/notifications/count` (unread since last `mark-all-read` timestamp in `localStorage`).
- Bell lives in the dashboard header with a dropdown panel: severity pill (info/warn/error), timestamp, event name, summary. Filter tabs: All / Info / Warn / Error.

### 3.2 SMTP email

- Triggered on `warn` or `error` severity (threshold configurable via `$AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY`).
- Subject: `[ai-playbook] WARN issue_sync.failed — <summary>`.
- Body: timestamp, severity, event, actor, attrs (pretty JSON), detail.
- To: `$AIPLAYBOOK_NOTIFICATIONS_TO` (default: `$SMTP_USER`).
- Opt-out: set `$AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY=never`.

### 3.3 OTel span (best-effort)

Every `notify()` call also emits an OTel event via `scripts.tracing.trace_emit.add_event` so long-session traces correlate with notifications.

---

## 4. Env var cheat sheet

See [docs/concepts/env-vars.md](../docs/concepts/env-vars.md) for the full table. Minimum for full zero-touch:

```bash
# SMTP (Gmail example; any provider works)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=23051550+Wizarck@users.noreply.github.com
SMTP_PASSWORD=<app-password>

# Jira via atlassian-consumer-a
ATLASSIAN_URL=https://consumer-a.atlassian.net
ATLASSIAN_USERNAME=23051550+Wizarck@users.noreply.github.com
ATLASSIAN_API_TOKEN=<jira-api-token>
AIPLAYBOOK_JIRA_DEFAULT_PROJECT=consumer-a        # or consumer-b

# GitHub
AIPLAYBOOK_GH_PROJECT_NUMBER=1                 # optional; 1 = Arturo's board
GITHUB_TOKEN=<auto-in-Actions>

# Notification addresses (optional)
AIPLAYBOOK_NOTIFICATIONS_TO=23051550+Wizarck@users.noreply.github.com
AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY=warn
```

All credentials live in SOPS-encrypted `secrets.env`; Actions pull from GitHub repo secrets mirrored by the same names.

---

## 5. Manual override

Every automation accepts `--force-with-reason="<≥10 chars>"` per `docs/rules/break-glass.rule.md` when a gate is blocking something legitimate:

```bash
python -m scripts.issue_sync --force-with-reason="bootstrapping acme-shop before openspec/ exists"
python -m scripts.release_cut --tag v0.3.0 --force-with-reason="hotfix; CHANGELOG updated post-tag"
```

Every override lands in `.ai-playbook/overrides.log` and emits a `warn` notification.

---

## 6. Troubleshooting

### Empty bell (no events)

1. Is the dashboard pod's `NOTIFICATIONS_LOG_PATH` pointing at an actually-populated file? On the VPS: `ssh consumer-d-vps kubectl exec -n consumer-d deploy/consumer-d-dashboard -- ls -la /app/.ai-playbook/`.
2. Is the aiops-state hostPath mounted? Check `helm/consumer-d-stack/templates/dashboard.yaml` has the `aiops-state` volumeMount.
3. Has anything written to the JSONL yet? `ssh consumer-d-vps cat /opt/consumer-d/data/aiops-metrics/notifications.jsonl`.

### Email not arriving

1. Is `$AIPLAYBOOK_NOTIFICATIONS_EMAIL_MIN_SEVERITY` set to `never`? That's the opt-out.
2. Is severity below threshold? Default is `warn`.
3. Check `scripts/notify.py` stderr — it breadcrumbs `notify.failed=1` when SMTP send fails.
4. Gmail app-password expired? Rotate and update `SMTP_PASSWORD` in SOPS + GitHub secrets.

### Issue-sync queue growing

`.ai-playbook/issue_sync_queue.jsonl` drains on next run. If entries older than 7 days appear, they're evicted with an `error` notification. Usually means Jira/GH creds rotated without updating secrets — rotate + re-run.

### Release-cut fails with "GH Release already exists"

Someone (or a prior CI run) already created the release. Inspect `gh release view <tag>` manually. To re-run: `gh release delete <tag> && git push --delete origin <tag> && git push origin <tag>` — use `--force-with-reason` only if you're sure.

---

## 7. Cross-references

- `docs/concepts/issue-tracking.md` §2-§4 — the flow this doc implements.
- `docs/concepts/notification-queue.md` — the JSONL schema + rate-limit contract.
- `docs/concepts/notification-policy.md` — severity levels + per-event policy.
- `docs/rules/break-glass.rule.md` — `--force-with-reason` contract.
- `scripts/notify.py`, `scripts/issue_sync.py`, `scripts/release_cut.py` — the implementations.
- `.github/workflows/issue-sync.yml`, `.github/workflows/release-cut.yml` — the CI triggers.
- `templates/new-project/.github/workflows/*.tmpl` — consumer-repo copies.
- Dashboard bell: `consumer-d/dashboard/backend/routes/notifications.py`.
