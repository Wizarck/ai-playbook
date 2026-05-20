---
schema: tutorial/v1
slug: learning-path
title: Learning path — operator to maintainer
description: A self-paced reading order for getting from "I ran the quickstart" to "I can review PRs and cut a release". Skip what you don't need.
estimated_time: ""
prerequisite_concepts: []
audience: developer
order: 5
---

# Learning path

A suggested reading order, self-paced. Pick the stage that matches what you want to do; skip what you don't need. This is a map, not a sequence to complete.

## Prereqs

- You finished [03-quickstart.md](03-quickstart.md) end-to-end.
- You have a scratch project to experiment on.
- You are comfortable writing prose alongside code — the playbook is a documentation product first.

## Operator — "I can use the playbook in my project"

Read [02-start-here.md](02-start-here.md), [03-quickstart.md](03-quickstart.md), [../../AGENTS.md](../../AGENTS.md), [../concepts/dispatcher-chain.md](../concepts/dispatcher-chain.md), and [../concepts/projects-registry.md](../concepts/projects-registry.md).

Then: run `python .ai-playbook/scripts/doctor.py` clean against a scratch repo, install pre-commit hooks, get `pre-commit run --all-files` green.

## Reviewer — "I can review PRs against the playbook"

Read [../rules/verdict-contract.rule.md](../rules/verdict-contract.rule.md), [../concepts/parallel-review.md](../concepts/parallel-review.md), [../concepts/agent-contract.md](../concepts/agent-contract.md), [../concepts/model-routing.md](../concepts/model-routing.md), and [../rules/break-glass.rule.md](../rules/break-glass.rule.md).

Then: invoke `bmad-code-review` on a deliberately buggy PR; produce a review artefact with the exact `⚠️ ISSUES FOUND (iter 1)` verdict literal and at least one S1, S2, and S3 finding.

## Contributor — "I can land a small PR"

Read `scripts/schema_validate.py`, `scripts/mcp/validate.py`, and `scripts/discover_projects.py` end-to-end, comments included.

Then: open a small PR (e.g. add a row to [../concepts/taxonomy.md](../concepts/taxonomy.md), or fix a cross-ref) following [CONTRIBUTING.md](../../CONTRIBUTING.md) — Conventional Commits, ruff, tests with every script.

## Maintainer — "I can cut a release"

Read [../concepts/rollout-strategy.md](../concepts/rollout-strategy.md), [../concepts/slos.md](../concepts/slos.md), and [../concepts/retrospective-cadence.md](../concepts/retrospective-cadence.md).

Then: cut a patch release end-to-end (bump VERSION, CHANGELOG entry, tag, open GH Release). Read one open RFC and write a substantive reviewer comment.

## What's next

- [02-start-here.md](02-start-here.md) — orientation.
- [03-quickstart.md](03-quickstart.md) — bootstrap walkthrough.
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — commit style, RFC flow.
- [../concepts/dispatcher-chain.md](../concepts/dispatcher-chain.md), [../rules/verdict-contract.rule.md](../rules/verdict-contract.rule.md), [../concepts/parallel-review.md](../concepts/parallel-review.md) — core reading.
