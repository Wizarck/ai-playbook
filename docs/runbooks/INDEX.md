# docs/runbooks/INDEX.md

> **Status**: v1.0.0. Manual index (not auto-generated yet).

Operational runbooks — AI-executable procedures for recurring ops. Specs
define the contract; runbooks describe the sequence of commands a
maintainer (human or AI) runs to execute it.

> **Where to start (any change)**: read [`docs/concepts/development-flow.md`](../docs/concepts/development-flow.md) FIRST. It's the LLM-agnostic canonical entry point for "how do I make a change in any playbook-consuming project?" and points outward to the right runbook / spec for each step.

All runbooks follow the same shape:

- Purpose + prereqs in the header.
- Numbered steps, each with exact command + expected output + error branch.
- Rollback section.
- Cross-references.

## Runbooks

| Runbook | When to run it | Cross-refs |
|---|---|---|
| [onboard-new-project.md](onboard-new-project.md) | Add a brand-new repo as a consumer of the playbook (submodule + dispatcher + Hindsight loop + auto-propagation). | [scripts/bootstrap.py](../scripts/bootstrap.py), [consumers.yaml](../consumers.yaml), [templates/new-project/](../templates/new-project/) |
| [release.md](release.md) | Cut a new semver tag on `ai-playbook`; auto-propagates PRs to every consumer. | [consumers.yaml](../consumers.yaml), [docs/concepts/rollout-strategy.md](../docs/concepts/rollout-strategy.md) |
| [rotate-secrets.md](rotate-secrets.md) | Any secret expires, rotates, or is compromised (PLAYBOOK_PROPAGATION_TOKEN, SMTP, ATLASSIAN, GITHUB_TOKEN). | [docs/concepts/data-retention.md](../docs/concepts/data-retention.md), [docs/concepts/env-vars.md](../docs/concepts/env-vars.md) |
| [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) | `propagate-playbook-bump.yml` Action fails or a consumer's PR doesn't appear. Decision tree by failing step. | [scripts/propagate_bump.py](../scripts/propagate_bump.py), [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) |
| [hindsight-retain.md](hindsight-retain.md) | At the end of any meaningful work — discovered gotcha, ADR, agentic-failure resolved, retro pattern. Persists durable knowledge to Hindsight so any future session/project can recall it. | [docs/concepts/memory-hierarchy.md](../docs/concepts/memory-hierarchy.md), [scripts/retain_memory.py](../scripts/retain_memory.py) |
| [skills-version-bump.md](skills-version-bump.md) | Cut a new semver tag on a skills source repo (`ai-playbook` itself or `consumer-d-skills`) and propagate the bump as PRs across every consumer pinning that source. | [docs/concepts/skills-distribution.md](../docs/concepts/skills-distribution.md), [scripts/propagate_skills_bump.py](../scripts/propagate_skills_bump.py), [.github/workflows/propagate-skills-bump.yml](../.github/workflows/propagate-skills-bump.yml) |
| [git-worktree-bare-setup.md](git-worktree-bare-setup.md) | Greenfield bootstrap, migration, or daily-flow worktree management for the bare-repo + per-branch layout (consumers running ≥3 concurrent OpenSpec slices). | [docs/concepts/git-worktree-bare-layout.md](../docs/concepts/git-worktree-bare-layout.md), [scripts/wt_add.py](../scripts/wt_add.py), [docs/concepts/runbook-bmad-openspec.md](../docs/concepts/runbook-bmad-openspec.md) §3.7 |
| [runbook-vps-down.md](runbook-vps-down.md) | VPS unreachable (S1). Stub v0.1.0 — referenced by `incident-response.md` §4 scenario #1. | [docs/concepts/incident-response.md](../docs/concepts/incident-response.md), [docs/concepts/post-mortem.md](../docs/concepts/post-mortem.md) |
| [runbook-db-corruption.md](runbook-db-corruption.md) | Hindsight DB corruption (S1, data integrity). Stub v0.1.0 — `incident-response.md` §4 scenario #2. | [docs/concepts/incident-response.md](../docs/concepts/incident-response.md), [docs/concepts/memory-hierarchy.md](../docs/concepts/memory-hierarchy.md) |
| [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md) | Scoped credential leak (1-3 keys), 1h MTTR. Stub v0.1.0. | [rotate-secrets.md](rotate-secrets.md), [docs/concepts/incident-response.md](../docs/concepts/incident-response.md) §4 scenario #3 |
| [runbook-secrets-leak-containment.md](runbook-secrets-leak-containment.md) | Wide-scope leak (machine compromise, supplier compromise, public repo). Stub v0.1.0. | [runbook-key-rotation-emergency.md](runbook-key-rotation-emergency.md), [docs/concepts/incident-response.md](../docs/concepts/incident-response.md) |
| [cascade-failure-template.md](cascade-failure-template.md) | Author a per-service cascade-failure runbook (added v0.11.0). Template with 5 sections (symptom list / precondition check / impact map / recovery sequence / postmortem trigger). | [docs/concepts/post-mortem.md](../docs/concepts/post-mortem.md), [docs/concepts/degradation-modes.md](../docs/concepts/degradation-modes.md), [docs/concepts/incident-response.md](../docs/concepts/incident-response.md) |

## Adding a new runbook

1. Create `runbooks/<slug>.md` with the header + steps pattern above.
2. Append a row to this file.
3. Reference it from any affected spec or workflow.
4. Commit — no tag bump required for runbook-only additions.

## Deferred runbooks

These will land when the trigger fires (no value writing them in the
abstract):

- `upstream-sync-conflict.md` — activates the first time
  `upstream_refresher.py` produces a real 3-way conflict that needs
  human resolution.

(`incident-response.md` and `model-migration.md` were promoted to v1.0.0
on 2026-05-01 by OpenSpec change `complete-ir-and-model-migration-specs`.
The four IR-referenced stubs now live above this section.)
