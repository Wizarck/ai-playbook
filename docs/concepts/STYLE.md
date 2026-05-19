---
schema: concept/v1
slug: style
title: Writing style guide (Slice 5 authors)
summary: |
  Voice, tense, vocabulary, link syntax, example structure. Authored in
  Slice 4 as a placeholder; ratified by Slice 5.A canonical-rule rewrite
  before the 5.A-E parallel rewrites kick off.
---

# Writing style guide

> Authoritative source for Slice 5 doc rewrites. ≤30 lines body per D14
> convention.

## Voice

- Imperative, second person ("YOU MUST", "Run...", "Verify..."), not first ("we", "I").
- Present tense; avoid future ("will fail") and past ("has failed").

## Vocabulary (RFC 2119)

- `MUST` / `MUST NOT` — binding hard requirement (enforced by hook or CI).
- `SHOULD` / `SHOULD NOT` — strong recommendation; deviation requires justification.
- `MAY` — permissive option.
- Never use "please" or "try to" — they soften binding clauses.

## Example structure (rules)

Every rule body has these sections in order:

1. **Trigger** — explicit when-clause (tools / paths / events).
2. **Binding clause** — single RFC 2119 sentence.
3. **Trust boundary** — only when the rule touches tool output (data ≠ instructions).
4. **Process supervision** — paired hook CLI invocation + expected exit code.
5. **Examples** — one preferred, one avoided.
6. **Break-glass** — only when the rule has a bypass env var.

## Link syntax

- Within `docs/`: relative paths only — `[name](../runbooks/foo.md)`.
- To repo root: prefix with `../../` (relative to docs/concepts/).
- External URLs: full https://; mark provider in parentheses when not obvious.
