# runbooks/INDEX.md

> **Status**: v1.0.0. Manual index (not auto-generated yet).

Operational runbooks — AI-executable procedures for recurring ops. Specs
define the contract; runbooks describe the sequence of commands a
maintainer (human or AI) runs to execute it.

All runbooks follow the same shape:

- Purpose + prereqs in the header.
- Numbered steps, each with exact command + expected output + error branch.
- Rollback section.
- Cross-references.

## Runbooks

| Runbook | When to run it | Cross-refs |
|---|---|---|
| [onboard-new-project.md](onboard-new-project.md) | Add a brand-new repo as a consumer of the playbook (submodule + dispatcher + Hindsight loop + auto-propagation). | [scripts/bootstrap.py](../scripts/bootstrap.py), [consumers.yaml](../consumers.yaml), [templates/new-project/](../templates/new-project/) |
| [release.md](release.md) | Cut a new semver tag on `ai-playbook`; auto-propagates PRs to every consumer. | [consumers.yaml](../consumers.yaml), [specs/rollout-strategy.md](../specs/rollout-strategy.md) |
| [rotate-secrets.md](rotate-secrets.md) | Any secret expires, rotates, or is compromised (PLAYBOOK_PROPAGATION_TOKEN, SMTP, ATLASSIAN, GITHUB_TOKEN). | [specs/data-retention.md](../specs/data-retention.md), [specs/env-vars.md](../specs/env-vars.md) |
| [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) | `propagate-playbook-bump.yml` Action fails or a consumer's PR doesn't appear. Decision tree by failing step. | [scripts/propagate_bump.py](../scripts/propagate_bump.py), [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) |
| [hindsight-retain.md](hindsight-retain.md) | At the end of any meaningful work — discovered gotcha, ADR, agentic-failure resolved, retro pattern. Persists durable knowledge to Hindsight so any future session/project can recall it. | [specs/memory-hierarchy.md](../specs/memory-hierarchy.md), [scripts/retain_memory.py](../scripts/retain_memory.py) |
| [skills-version-bump.md](skills-version-bump.md) | Cut a new semver tag on a skills source repo (`ai-playbook` itself or `consumer-d-skills`) and propagate the bump as PRs across every consumer pinning that source. | [specs/skills-distribution.md](../specs/skills-distribution.md), [scripts/propagate_skills_bump.py](../scripts/propagate_skills_bump.py), [.github/workflows/propagate-skills-bump.yml](../.github/workflows/propagate-skills-bump.yml) |
| [git-worktree-bare-setup.md](git-worktree-bare-setup.md) | Greenfield bootstrap, migration, or daily-flow worktree management for the bare-repo + per-branch layout (consumers running ≥3 concurrent OpenSpec slices). | [specs/git-worktree-bare-layout.md](../specs/git-worktree-bare-layout.md), [scripts/wt_add.py](../scripts/wt_add.py), [specs/runbook-bmad-openspec.md](../specs/runbook-bmad-openspec.md) §3.7 |

## Adding a new runbook

1. Create `runbooks/<slug>.md` with the header + steps pattern above.
2. Append a row to this file.
3. Reference it from any affected spec or workflow.
4. Commit — no tag bump required for runbook-only additions.

## Deferred runbooks

These will land when the trigger fires (no value writing them in the
abstract):

- `incident-response.md` — activates at first paying client (see
  [specs/incident-response.md](../specs/incident-response.md)).
- `model-migration.md` — activates at first pinned-model retirement (see
  [docs/model-migration.md](../docs/model-migration.md)).
- `upstream-sync-conflict.md` — activates the first time
  `upstream_refresher.py` produces a real 3-way conflict that needs
  human resolution.
