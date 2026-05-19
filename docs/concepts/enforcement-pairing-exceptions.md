---
schema: concept/v1
slug: enforcement-pairing-exceptions
title: Pairing exceptions — advisory-only rules
summary: |
  Justifies rules that declare `paired_hardrule: null` (advisory-only).
  Every entry must explain why an L1 hook would be impractical or
  counter-productive. Slice 5 populates concrete entries.
---

# Pairing exceptions

> **Slice 4 placeholder**: stub. Slice 5 populates concrete entries as
> rules are rewritten.

A rule may declare `paired_hardrule: null` only when:

1. **No deterministic L1 check exists** (e.g., "tone of voice in user-facing
   error messages" — needs human or LLM judgment).
2. **The rule is informational** (e.g., a doc listing approved technologies
   — no per-edit enforcement applicable).
3. **The hook would create a false-positive storm** (e.g., a rule that fires
   on every line of code; an L3 PR-time check is the right cadence).

For each `paired_hardrule: null` rule, add an entry below:

| Rule slug | Reason |
|---|---|
| _(populated in Slice 5)_ | _(populated in Slice 5)_ |

The pairing validator (`scripts/validate_pairing.py --strict`) checks that
every advisory-only rule has an entry in this file.

## See also

- [`enforcement-layers.md`](enforcement-layers.md)
- [`enforcement-status.md`](enforcement-status.md)
