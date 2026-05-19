---
schema: tutorial/v1
slug: curriculum
title: 4-week onboarding curriculum — operator to maintainer
description: A 4-week structured learning path that takes a new dev from operator (week 1) to reviewer (week 2) to contributor (week 3) to maintainer candidate (week 4). Each week has a goal, a reading list, hands-on exercises, and exit criteria.
estimated_time: "4 weeks (~4–6 hours per week)"
prerequisite_concepts: []
audience: developer
order: 6
---

# 4-week onboarding curriculum — operator to maintainer

> **What you'll learn**: A structured 4-week sequence that takes you from "I ran the quickstart" to "I can run a weekly retro and cut a patch release." Each week has a goal, a reading list, hands-on exercises, and explicit exit criteria. You will not skim docs; you will operate, then review, then contribute, then maintain.
> **Estimated time**: 4 weeks at ~4–6 hours per week
> **Prerequisites**:
> - You have finished [03-quickstart.md](03-quickstart.md) end-to-end
> - You have a scratch consumer project you can experiment on
> - You are comfortable writing prose alongside code (the playbook is a documentation product first; engineers who reject writing won't enjoy it)

This is not a replacement for any existing doc. Every week points at docs and specs that already exist; the value is in the **sequence** and the **exit criteria**.

---

## Prereqs (before week 1)

- Python 3.11+ installed (per [03-quickstart.md](03-quickstart.md) §Prereqs).
- git 2.40+, Node.js 20+, pipx, pre-commit, gh CLI authenticated, sops + age.
- A GitHub account with access to the `Wizarck` org.
- Willingness to write prose alongside code. The playbook is a documentation product first; engineers who reject writing won't enjoy it.
- ~4–6 hours per week set aside for the curriculum. Less than that stretches to 6–8 weeks; don't skip weeks to compress it.

---

## Week 1 — Operator

**Goal**: you can bootstrap a fresh consumer project and run every pre-commit hook green.

**Read** (in order):

1. [02-start-here.md](02-start-here.md) — 60-second orientation + the 3-level dispatcher diagram.
2. [03-quickstart.md](03-quickstart.md) — the 25–40-min walkthrough, end-to-end.
3. [../../AGENTS.md](../../AGENTS.md) — the playbook's own project dispatcher (dogfooding example).
4. In a consumer repo: `CLAUDE.md` / `GEMINI.md` / `.cursor/rules/*.mdc` — thin LLM-specific routers that point at AGENTS.md. (The playbook itself has no `CLAUDE.md`; it dogfoods AGENTS.md only.)
5. [../concepts/dispatcher-chain.md](../concepts/dispatcher-chain.md) — the 3-level contract.
6. [../concepts/projects-registry.md](../concepts/projects-registry.md) — how `~/.ai-playbook/projects.yaml` is populated and consumed.

**Do**:

- Run `python .ai-playbook/scripts/doctor.py`; fix every `fail` finding until clean.
- Follow [03-quickstart.md](03-quickstart.md) Steps 1–8 against a throwaway scratch repo.
- Install pre-commit hooks; run `pre-commit run --all-files` to green.

**Exit criteria**:

- You can recite the 3 levels of the dispatcher chain from memory.
- You can bootstrap a fresh consumer project in <40 min without referring to the doc.
- All pre-commit hooks run green on your scratch project.

---

## Week 2 — Reviewer

**Goal**: you can review a PR using the playbook's parallel-review discipline and articulate why a finding is S1 vs S3.

**Read** (any order, but all five):

1. [../rules/verdict-contract.rule.md](../rules/verdict-contract.rule.md) — the verdict literals, severity taxonomy, max-2-rework rule.
2. [../concepts/parallel-review.md](../concepts/parallel-review.md) — the 3-layer review model (Blind Hunter / Edge Case Hunter / Acceptance Auditor).
3. [../concepts/agent-contract.md](../concepts/agent-contract.md) — the machine-shaped envelope that carries verdicts between agents.
4. [../concepts/model-routing.md](../concepts/model-routing.md) — why reviewer layers use specific models.
5. [../rules/break-glass.rule.md](../rules/break-glass.rule.md) — when an override is legitimate and when it's not.

**Do**:

- Invoke the `bmad-code-review` skill on a fictitious diff (a deliberately buggy PR from a scratch branch).
- Produce a review artefact ending with the exact `⚠️ ISSUES FOUND (iter 1)` verdict literal.
- Include at least one `S1`, one `S2`, and one `S3` finding; explain the severity rationale in-line.

**Exit criteria**:

- You can articulate why an S1 blocks unconditionally and an S3 batches (verdict-contract.md §2).
- Your review artefact passes `scripts/verdict_lint.py` without warnings.
- You can name one scenario where `--force-with-reason` is appropriate and one where it is not.

---

## Week 3 — Contributor

**Goal**: you can land a small spec or script PR that passes CI and triages a FEEDBACK.md bullet.

**Read** (end-to-end, including comments):

1. `scripts/schema_validate.py` — the frontmatter validator.
2. `scripts/mcp/validate.py` — the MCP SSOT validator.
3. `scripts/discover_projects.py` — the registry builder.

**Do**:

- Open a small spec PR (e.g. add a row to [../concepts/taxonomy.md](../concepts/taxonomy.md), or fix a cross-ref).
- Follow [contributing.md](../concepts/contributing.md) §4 commit style and §5 test discipline.
- Triage one open issue in the project's GitHub Issues: turn it into a fix, an RFC, or a rejection with rationale.

**Exit criteria**:

- One PR merged.
- One issue triaged.
- You can point to the ruff, type-hint, and pathlib rules in [contributing.md](../concepts/contributing.md) §4 from memory.

---

## Week 4 — Maintainer candidate

**Goal**: you can run a full weekly retro and cut a patch release unassisted.

**Read** (in order):

1. [../concepts/rollout-strategy.md](../concepts/rollout-strategy.md) — breaking-change workflow.
2. [../concepts/slos.md](../concepts/slos.md) — the targets that define "is the playbook healthy".
3. `docs/concepts/data-retention.md` (owned by Subagent A, T22 track — if not yet populated when you reach week 4, read [../concepts/retrospective-cadence.md](../concepts/retrospective-cadence.md) §3 Outputs as the interim pointer).
4. `docs/concepts/incident-response.md` (owned by Subagent A, T22 track — same interim pointer).
5. [../concepts/retrospective-cadence.md](../concepts/retrospective-cadence.md) — the three cadences and their templates.

**Do**:

- Run a full weekly retro using [../../templates/retro/weekly.md.tmpl](../../templates/retro/weekly.md.tmpl). Commit it to `reports/retros/`.
- Cut a patch release: bump version in the appropriate source file, add a CHANGELOG entry, tag the commit, open the GH Release.
- Read one currently-open RFC end-to-end. Write a reviewer comment of ≥200 words with concrete questions or approval rationale.

**Exit criteria**:

- Your retro passes `scripts/telemetry/report.py (absorbed in Slice 6)` (no "copy-paste retro" or "retro-as-blame" flags).
- Your patch release tag appears in `git tag -l` and the CHANGELOG entry follows the existing voice.
- You can name the deprecation window rule (1 minor cycle OR 90 days, whichever is longer) from memory.

---

## Ongoing — past week 4

- **Weekly retro attendance**: observer for 2 weeks, participant for 4 weeks, facilitator thereafter. The maintainer decides when you cross each threshold.
- **Monthly lifecycle check review**: read the monthly retro output, propose at least one systemic-flag fix per quarter.
- **One RFC per quarter**: either write one, or serve as the named reviewer on one.
- **Per-quarter spec rotation**: pick one spec, re-read it cold, file an issue for any line you struggle to follow. Ambiguity rot (per [slos.md](../concepts/slos.md)) depends on fresh eyes to surface.

---

## Do NOT

- **Skip weeks.** Week 3 assumes week 2's reviewer instincts. Week 4 assumes week 3's contributor discipline. A contributor who never operated the playbook writes specs that don't survive contact with consumers.
- **Compress the curriculum into a weekend.** You can read all the docs in a weekend; you cannot internalise the dispatcher chain, the verdict contract, and the rollout strategy in a weekend. Time-in-tool matters more than read-throughs.
- **Treat this as a checklist.** Exit criteria are minimums, not targets. If week 2 took you 3 weeks because you wanted to read five more specs, that's fine.

---

## What's next

- [02-start-here.md](02-start-here.md) — the 60-second orientation you re-read at the start of week 1.
- [03-quickstart.md](03-quickstart.md) — the operator-layer walkthrough you complete in week 1.
- [Concept: contributing](../concepts/contributing.md) — roles, RFC SLAs, code style (week 3).
- [Concept: dispatcher-chain](../concepts/dispatcher-chain.md), [Rule: verdict-contract](../rules/verdict-contract.rule.md), [Concept: parallel-review](../concepts/parallel-review.md), [Concept: agent-contract](../concepts/agent-contract.md), [Concept: model-routing](../concepts/model-routing.md), [Rule: break-glass](../rules/break-glass.rule.md) — week-by-week reading list.
- [Concept: rollout-strategy](../concepts/rollout-strategy.md), [Concept: slos](../concepts/slos.md), [Concept: retrospective-cadence](../concepts/retrospective-cadence.md) — week 4 governance reading.
- [../../templates/retro/](../../templates/retro/) — retro templates used in weeks 3–4 and ongoing.
