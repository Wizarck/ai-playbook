---
schema: concept/v1
slug: retrospective-cadence
title: Retrospective Cadence
summary: |
  Retros are not a ritual. They are the feedback loop that keeps the playbook
  honest — if a spec is ambiguous, a gate miscalibrated, or a pattern
  chronically painful, the retros catch it before it metastasises. Three
  cadences cover three horizons.
last_validated: "2026-05-19"
---

# Retrospective Cadence

Retros are not a ritual. They are the feedback loop that keeps the playbook honest — if a spec is ambiguous, a gate miscalibrated, or a pattern chronically painful, the retros catch it before it metastasises. Three cadences cover three horizons.

---

## 1. Cadences

| Cadence | Trigger | Scope | Participants | Output path |
|---|---|---|---|---|
| **Post-archive** | Every `openspec archive` call (per [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §4). | The single change that was archived: its artefacts, iter counts, break-glass usages, lessons retained. | Main agent + human approver (same human who approved Gate F). | `reports/retros/<YYYY-MM>/post-archive-<change-id>.md` |
| **Weekly** | Monday per local time. Missed Monday → run Tuesday; log the slip. | All post-archives from the week + FEEDBACK.md gripes + break-glass aggregate + top frictions. | Maintainer (Arturo solo at v0.1.0). | `reports/retros/<YYYY-MM>/weekly-<YYYY-WW>.md` |
| **Monthly** | First Monday of each month. | Lifecycle-check output, systemic flags, deprecation progress, cost report, aggregate of weekly retros. | Maintainer. | `reports/retros/<YYYY-MM>/monthly.md` |

"Log the slip" means the delayed retro still runs but its opening paragraph names the slip and the cause. Three slips in a row escalates to a systemic flag in the next monthly.

---

## 2. Templates

Each cadence has a dedicated template under `../templates/retro/`. Retros NOT produced from the template are rejected by `lifecycle_check.py` during the next monthly (the template frontmatter is the identity marker).

| Cadence | Template |
|---|---|
| Post-archive | ../templates/retro/post-archive.md.tmpl |
| Weekly | ../templates/retro/weekly.md.tmpl |
| Monthly | ../templates/retro/monthly.md.tmpl |

Every template ends with a verdict line per [verdict-contract.md](../rules/verdict-contract.rule.md) §1. A retro without a verdict is malformed.

---

## 3. Outputs

All retros are committed to the repo under `reports/retros/<YYYY-MM>/`. This is the audit trail. Retros are NOT gitignored — they are evidence that the loop ran.

Directory shape after a typical month:

```
reports/retros/2026-04/
  post-archive-acme-shop-bootstrap.md
  post-archive-acme-shop-catalog.md
  weekly-2026-W15.md
  weekly-2026-W16.md
  weekly-2026-W17.md
  monthly.md
```

The first time a project generates retros, `reports/retros/` is auto-created by the scripts. The directory is committed to the repo (consumers add it to their repo, not to the playbook).

---

## 4. Automation

[`scripts/lifecycle_check.py`](../../scripts/lifecycle_check.py) generates the **monthly retro skeleton** and powers the lifecycle-check output block (template §1). Humans fill narrative; the script fills evidence.

Contract the script must satisfy:

1. Invocable as `python scripts/lifecycle_check.py --month YYYY-MM [--format md|json]`.
2. Produces, in the markdown form, a section per topic below so the monthly template can paste it verbatim (§1 of `templates/retro/monthly.md.tmpl`):
   - Stale OpenSpec changes (no activity >30 days).
   - Outdated memories (hindsight entries older than the related code's last commit).
   - Drift findings (playbook ↔ consumer AGENTS.md, surfaced by `drift_check.py`).
   - Override counters per gate per project per month (from `.ai-playbook/overrides.log`, cross-ref [break-glass.md](../rules/break-glass.rule.md) §4).
   - Notification volume per actor per level per week ([notification-policy.md](notification-policy.md) §5).
   - Agentic-failure spans aggregated by `ai_playbook.failure.kind` ([agentic-failures.md](agentic-failures.md) §3).
   - Secrets-scan match counts (should be 0; any non-zero is a systemic flag).
3. Exit 1 if any systemic threshold is crossed (e.g. gate overridden ≥3× in 30 days), exit 0 otherwise. Retro author must still fill the narrative; the exit code is for CI visibility.
4. Emits an OTel span with `ai_playbook.retro.month=<YYYY-MM>` and `ai_playbook.retro.flags=<N>` so the dashboard (T19) can surface retro health.

The script does **not** auto-generate weekly or post-archive retros — those are short-horizon and the human should write them by hand from the template.

---

## 5. Anti-patterns

Retros fail when they become ritual. These four patterns are auditable by the monthly lifecycle check and surface as systemic flags.

- **Silent retros.** A cadence ran, no markdown produced. `lifecycle_check.py` expects a file at the canonical path; missing file = silent retro = flag. If the cadence was intentionally skipped, the following retro must explain why in its opening paragraph.
- **Retro-as-blame.** Frictions framed as "X person failed" instead of "the system allowed this to happen". Retros target systems, not individuals. Actor identity appears ONLY in the notification/override log sections where it is load-bearing, never in the frictions narrative.
- **Copy-paste retros.** Generic bullets reused across weeks with no concrete evidence (trace_id, file:line, retro link). A retro whose §1 and §4 sections have no links is suspect. The monthly check grep's for link density and flags below-threshold ones.
- **Retros without action items.** Frictions identified, no one owns a fix. Every top-3 friction in a weekly retro must produce at least one action item with owner and due date, or an explicit deferral reason. "We'll keep an eye on it" is not an action item.

---

## 6. Cross-references

- [verdict-contract.md](../rules/verdict-contract.rule.md) — every retro ends with a canonical verdict line (§1 of each template).
- [break-glass.md](../rules/break-glass.rule.md) §4 — override audit trail feeds the weekly/monthly retros.
- [notification-policy.md](notification-policy.md) §5 — retro surface for notification volume anomalies.
- [agentic-failures.md](agentic-failures.md) §3 — failure-kind aggregation lands in monthly retros.
- [runbook-bmad-openspec.md](runbook-bmad-openspec.md) §4 — runbook cross-references this spec for per-change cadence.
- [migration-guide.md](migration-guide.md) — deprecation progress section of the monthly retro.
- `scripts/lifecycle_check.py` — automation (Subagent A, T14i).
