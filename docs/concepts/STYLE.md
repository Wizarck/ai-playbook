---
schema: concept/v1
slug: style
title: Concept-doc writing style
summary: |
  Authoritative style guide for docs/concepts/*.md. Locked by Slice 5.B,
  read by sub-slices 5.A/5.C/5.D/5.E before they rewrite their categories.
last_validated: "2026-05-19"
---

# Concept-doc writing style

Declarative, present tense, third person. Concept docs explain; they do not bind.

## RFC 2119 vocabulary — banned in body prose

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, `MAY` belong in `docs/rules/`. In concept bodies use lowercase (`must`, `should`, `can`) or rephrase. Code fences and quoted spec excerpts are exempt.

## Section structure (minimum)

1. `## Why` — motivation, the problem the concept addresses.
2. `## What` — definition / explanation.
3. `## How it relates to other concepts` — cross-refs to sibling concept slugs and to rule / runbook / tutorial docs.
4. `## Concrete example` — at least one worked example.

`## Further reading` is optional. Sub-sections of any depth are allowed inside these four.

## Anchor + link convention

Frontmatter `slug:` (D3) is authoritative and matches the filename stem. Cross-doc citations: `docs/concepts/<slug>.md`. Relative paths only inside `docs/` — for example, `[label](../rules/cleanup-zombies.rule.md)`. External URLs use full `https://`.

## Length cap (D7)

≤300 body lines per concept doc. Oversized docs are flagged for split during harmonisation.
