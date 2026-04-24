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
| [release.md](release.md) | Cut a new semver tag on `ai-playbook`; auto-propagates PRs to every consumer. | [consumers.yaml](../consumers.yaml), [specs/rollout-strategy.md](../specs/rollout-strategy.md) |
| [rotate-secrets.md](rotate-secrets.md) | Any secret expires, rotates, or is compromised (PLAYBOOK_PROPAGATION_TOKEN, SMTP, ATLASSIAN, GITHUB_TOKEN). | [specs/data-retention.md](../specs/data-retention.md), [specs/env-vars.md](../specs/env-vars.md) |
| [propagate-bump-troubleshooting.md](propagate-bump-troubleshooting.md) | `propagate-playbook-bump.yml` Action fails or a consumer's PR doesn't appear. Decision tree by failing step. | [scripts/propagate_bump.py](../scripts/propagate_bump.py), [.github/workflows/propagate-playbook-bump.yml](../.github/workflows/propagate-playbook-bump.yml) |
| [hindsight-retain.md](hindsight-retain.md) | At the end of any meaningful work — discovered gotcha, ADR, agentic-failure resolved, retro pattern. Persists durable knowledge to Hindsight so any future session/project can recall it. | [specs/memory-hierarchy.md](../specs/memory-hierarchy.md), [scripts/retain_lesson.py](../scripts/retain_lesson.py) |

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
