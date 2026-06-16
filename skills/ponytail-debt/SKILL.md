---
name: ponytail-debt
description: Use when the user wants to harvest every `ponytail:` comment in the codebase into a tracked debt ledger — says "ponytail debt", "/ponytail-debt", "what did ponytail defer", "list the shortcuts", "ponytail ledger", or "what did we mark to do later". One-shot report, changes nothing. Gated by the ponytail debt_ponytail component.
license: MIT
metadata:
  author: ai-playbook (ported from DietrichGebert/ponytail, MIT)
  version: "1.0"
---

# ponytail-debt — harvest `ponytail:` shortcuts into a ledger

Every deliberate ponytail shortcut is marked with a `ponytail:` comment naming
its ceiling and upgrade path. This collects them into one ledger so a deferral
can't quietly become permanent ("later means never").

## When to fire

- "ponytail debt", "what did ponytail defer", "list the shortcuts", "ponytail
  ledger", "what did we mark to do later", or `/ponytail-debt`.

## Scan

Grep the repo for comment markers, skipping `node_modules`, `.git`, and build
output:

`grep -rnE '(#|//) ?ponytail:' .`  (add other comment prefixes if your stack uses them)

Each hit is one ledger row. The comment prefix keeps prose that merely mentions
the convention out of the ledger.

## Output contract

One row per marker, grouped by file:

`<file>:<line> — <what was simplified>. ceiling: <the limit named>. upgrade: <the trigger to revisit>.`

The convention is `ponytail: <ceiling>, <upgrade path>`, so pull the ceiling and
the trigger straight from the comment. Want an owner per row too? add
`git blame -L<line>,<line>`.

Flag the rot risk: any `ponytail:` comment that names no upgrade path or trigger
gets a `no-trigger` tag — those are the ones that silently rot.

End with `<N> markers, <M> with no trigger.` Nothing found: `No ponytail: debt. Clean ledger.`

## Boundaries

Reads and reports only; changes nothing. To persist it, ask and it writes the
ledger to a file (e.g. `PONYTAIL-DEBT.md`). One-shot. "stop ponytail-debt" /
"normal mode" reverts.

## See also

- [skills/ponytail/SKILL.md](../ponytail/SKILL.md) — defines the `ponytail:` marker convention this harvests.
- [skills/ponytail-audit/SKILL.md](../ponytail-audit/SKILL.md) — finds NEW cuts; this one tracks the ones already marked.
