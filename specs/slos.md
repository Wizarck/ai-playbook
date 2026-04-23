# slos.md

> **Status**: v1.0.0. Populated in T22f.

Service-level objectives for the `ai-playbook` repo itself — the shared norms and tooling consumed as a submodule by every Wizarck project. These SLOs target the playbook-as-product: the contract it makes with Arturo (solo maintainer) and future team devs who inherit from it.

---

## 1. What we measure (and what we don't)

These SLOs apply to the **playbook**: its specs, scripts, docs, retros, and governance loop. They do NOT cover the runtime services that a consumer project ships (Hindsight memory plane, Hermes personal assistant, OpenTrattOS API, etc.) — those services carry their own SLOs in their own repos. Mixing the two planes inflates dashboards and hides real misses. Keep them separate.

The SLOs codified here answer one question: **"Is the playbook still a net win for the people consuming it?"** If drift, ambiguity, or flakiness erodes the signal, these numbers go red before the consumers lose trust.

---

## 2. Objectives

| SLO | Target | Measured by | Why |
|---|---|---|---|
| **Drift resolution time** | 95% of drift findings closed within 7 days of first detection. | `scripts/drift_check.py` weekly output (GH Action) compared against issue-close timestamps. | Drift rot between playbook norms and consumer `AGENTS.md` is the #1 silent killer of the LLM-agnostic promise. If drift sits, the submodule contract erodes. |
| **Retro freshness** | 100% of OpenSpec archives have a post-archive retro committed within 7 days of the archive. | `scripts/lifecycle_check.py` monthly aggregation of `reports/retros/<YYYY-MM>/post-archive-*.md` vs archive timestamps. | Retros are the learning loop per [retrospective-cadence.md](retrospective-cadence.md). Missed retros mean lessons evaporate. |
| **Doctor-green on new machines** | `scripts/doctor.py` reports zero `fail`-level findings on a fresh supported OS within 30 min of clone. | Timings captured in [../docs/quickstart-lessons.md](../docs/quickstart-lessons.md) per T15 dry-runs. | Onboarding friction compounds. A 30-min time-to-green is the ceiling before a new dev defects to ad-hoc solutions. |
| **CI green rate on `main`** | ≥98% over any rolling 30-day window. | GitHub Actions run history on `master`. | Flakiness destroys trust in the gates. A playbook whose own CI is flaky cannot credibly ask consumers to block on its hooks. |
| **Spec ambiguity aging** | 0 `TODO: clarify with maintainer` markers older than 30 days across `specs/*.md`. | Grep of `specs/` timestamped against git blame. | Ambiguity rot — an unresolved TODO is a silent invitation to break-glass or goal drift. 30 days is the outer bound; most should close within 7. |
| **Break-glass ratio** | <5% of gate evaluations across all consumers invoke `--force-with-reason` over any rolling 30-day window. | `.ai-playbook/overrides.log` aggregated by `scripts/lifecycle_check.py` per [break-glass.md](break-glass.md) §audit. | A high override rate means a gate is miscalibrated; [break-glass.md](break-glass.md) §audit escalates after ≥3 overrides of the same gate in 30 days, this SLO is the org-wide aggregate. |
| **Test suite wall-clock** | `pytest --no-header` completes in ≤5 s on a developer laptop (M-class Mac or equivalent). | Local wall-clock + a CI timing gate. | Fast feedback keeps the loop tight. Tests slower than 5 s stop being run before commit. |
| **Schema validation coverage** | 100% of registered consumers' `AGENTS.md` pass `scripts/schema_validate.py` in the nightly cross-registry run. | `scripts/schema_validate.py --all` driven by the projects registry (`~/.ai-playbook/projects.yaml`). | No stragglers. A v0 file quietly living in a registered project is exactly the drift these specs exist to prevent. |

Each row is a **single, measurable, time-bounded** promise. A metric that cannot be measured automatically belongs in a retro observation, not in this table.

---

## 3. Exception handling

When an SLO misses for a given measurement window:

1. `scripts/lifecycle_check.py` emits a `warn`-level `slo.breach.<slo-id>` event per [notification-policy.md](notification-policy.md) §4.
2. The script auto-files a GitHub Issue tagged `slo-breach` with the metric, window, observed value, and target. Title format: `slo-breach: <slo-id> <YYYY-MM>`.
3. The maintainer triages the issue in the next weekly retro per [retrospective-cadence.md](retrospective-cadence.md) §1.
4. **Recurring breach** — same SLO misses in ≥2 consecutive monthly windows → escalate to an RFC under `rfcs/`. Either the SLO is miscalibrated (tighten or loosen the target with evidence) or the underlying system has a structural gap (fix it; don't re-paper the target).
5. Breach of **Break-glass ratio** triggers a per-gate audit: which gate is overridden most, is it still correct, is the error message helping or hindering? Cross-refs [break-glass.md](break-glass.md) §audit.

A single-month breach is data. A two-month breach is a signal. A three-month breach unremediated is a governance failure and surfaces as a systemic flag in the monthly retro.

---

## 4. Review cadence

- **Monthly** — SLO state is a required section of the monthly retro template ([../templates/retro/monthly.md.tmpl](../templates/retro/monthly.md.tmpl)). `scripts/lifecycle_check.py` fills the evidence; the maintainer writes the narrative.
- **Quarterly** — one SLO row is selected for a deeper review: is the target still right, is the measurement still accurate, has the underlying concern shifted? Documented in the monthly retro that closes the quarter.
- **Annual** — the whole table is re-opened in a dedicated RFC. Targets below 99% get a one-line "still correct because X" justification or get tightened.

---

## 5. Cross-references

- [retrospective-cadence.md](retrospective-cadence.md) — monthly SLO review lives in the monthly retro.
- [break-glass.md](break-glass.md) — override-ratio SLO reads `.ai-playbook/overrides.log`.
- [notification-policy.md](notification-policy.md) §4 — `slo.breach.*` events map to `warn`.
- [verdict-contract.md](verdict-contract.md) — QA-loop SLOs (rework cycles, clarification lag) inherit the severity taxonomy; max-2-rework per §3 is the hard cap that keeps QA SLOs tractable.
- `scripts/drift_check.py` — drift-resolution SLO source.
- `scripts/lifecycle_check.py` — SLO aggregation owner; contract in [retrospective-cadence.md](retrospective-cadence.md) §4.
- [rollout-strategy.md](rollout-strategy.md) — emergency bypasses of the deprecation window carry a mandatory post-mortem, which surfaces here as an SLO-adjacent signal.
