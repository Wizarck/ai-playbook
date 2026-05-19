# Design — slice-5d-tutorials-rewrite

## Diátaxis tutorial framing

Tutorials are **learning-oriented** (Diátaxis quadrant 1). The reader is a beginner being led by the hand through a series of small concrete actions, each one building on the previous. The reader's confidence is more important than completeness — every section should leave the reader thinking "I did that, and I understand what happened."

Boundaries against the other 3 quadrants:

- **Not how-to** (`docs/runbooks/`) — runbooks assume the reader knows what they want and need a sequence of steps to get there. Tutorials are for readers who don't yet know what they want.
- **Not reference** (`docs/concepts/` + `docs/rules/`) — reference is for lookup; tutorials are for walking through.
- **Not explanation** — deep theory belongs in `docs/concepts/`. Tutorials mention WHY only briefly and link out for the deeper "why."

## Frontmatter contract (`schema: tutorial/v1`)

```yaml
---
schema: tutorial/v1                                 # versioning hook
slug: <kebab-case>                                  # authoritative identifier
title: <human-readable>                             # for INDEX + mkdocs nav
description: <one-line, ≤300 chars>                 # routing key for LLMs
estimated_time: "<X min>" | "<X hour>"              # cold-start budget for the reader
prerequisite_concepts: [<concept-slug>, ...]        # OPTIONAL — link to concepts the reader should read first
audience: new-contributor | operator | developer    # primary audience tag
order: <int>                                        # numbered sequence (01-, 02-, ...)
---
```

`schemas/schema-tutorial-v1.json` is NOT authored in this slice (file-ownership: `schemas/` belongs to a different sub-slice). The frontmatter above is the de-facto contract; a JSON schema can be retrofitted later without doc edits because `schema: tutorial/v1` is the versioning hook.

## Body template

```markdown
# <Title>

> **What you'll learn**: <one paragraph, 2–3 sentences — the headline outcome>
> **Estimated time**: <X min>
> **Prerequisites**: <bulleted; link to concepts/runbooks the reader needs first>

## 1. <First concrete action>

<step-by-step, with expected outputs>

## 2. <Build on step 1>

...

## What's next

- [<Next tutorial>](02-...md) — <one-line>
- [Concept: <X>](../concepts/<slug>.md) — for the deeper "why"
- [Runbook: <Y>](../runbooks/<slug>.md) — for production usage
```

## Numbering and the `01-` slot

The plan reserves `01-architecture-tour.md` as the canonical entry point (per Slice 7.F handoff into 5.D — the placeholder lives at `01-` and content lands here, ahead of schedule). Existing `01-start-here.md` and downstream files renumber by +1 to free the slot.

Final order:

| Order | File | Audience | Estimated time |
|---|---|---|---|
| 01 | `01-architecture-tour.md` | new-contributor | 15 min |
| 02 | `02-start-here.md` | new-contributor | 1 min |
| 03 | `03-quickstart.md` | operator | 25–40 min |
| 04 | `04-bootstrap-new-project.md` | operator | 10 min |
| 05 | `05-quickstart-lessons.md` | operator | 10 min |
| 06 | `06-curriculum.md` | developer | 4 weeks |
| 07 | `07-why-these-choices.md` | developer | 15 min |
| 08 | `08-fork-inventory.md` | developer | 10 min |

`02-start-here.md` is the 60-second orientation; `01-architecture-tour.md` is the 15-minute walking tour. Both reference each other so a reader who finishes one can step up or down at will.

## What "architecture tour" covers in 15 minutes

| Minute | Section | Action |
|---|---|---|
| 0–1 | What ai-playbook is | Read one paragraph; click through to `enforcement-layers.md` for depth. |
| 1–3 | The 4 doc types | See the table; click one of each (rule, concept, runbook, tutorial) to feel the shape. |
| 3–5 | Clone + install | `git clone`, `pip install -e .`. Expected: a clean install with `ai-playbook` importable. |
| 5–7 | Run the tests | `pytest tests/`. Expected: 900+ passing. |
| 7–9 | Run cleanup-zombies validator | `python scripts/cleanup_zombies.py validate`. Expected: exit 0; learn what "zombies" means. |
| 9–11 | Run doc-language linter | `python scripts/check_doc_language.py docs/`. Expected: exit 0; learn the ENGLISH mandate. |
| 11–13 | Run pairing validator | `python scripts/validate_pairing.py`. Expected: exit 0; learn the slug pairing convention. |
| 13–15 | Where to next | Pointer table to follow-up tutorials + concept docs. |

Each step has a 1-paragraph "why this matters" link to the relevant concept doc so the curious reader can branch off, but the main thread stays cold-start-friendly.

## Cross-reference policy

- Intra-tutorials: relative `[label](NN-slug.md)`.
- Cross-category outbound: `[label](../concepts/<slug>.md)` / `[label](../rules/<slug>.rule.md)` / `[label](../runbooks/<slug>.md)`.
- This slice fixes intra-tutorials refs only. Cross-category inbound fixes (README, AGENTS.md, runbook/concept references to old tutorial paths) are 5.F harmonization scope.

## Validation harness

- `scripts/check_doc_language.py docs/tutorials/` — exit 0 (English mandate, D6).
- `scripts/check_link_integrity.py docs/tutorials/` — exit 0 (no broken links).
- `pytest tests/` — green at the 918+ baseline.

## Out of scope

- `schemas/schema-tutorial-v1.json` (file-ownership)
- VERSION bump (5.F's job)
- CHANGELOG.md (5.F's job)
- Cross-category inbound link fixes from README/AGENTS/concept docs that reference old tutorial paths (5.F harmonization)
- `bmad-checkpoint-preview` 25/50/75% checkpoints — single-agent slice, no parallelism
