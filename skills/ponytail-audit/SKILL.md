---
name: ponytail-audit
description: Use when the user wants a whole-repo audit for over-engineering — says "audit this codebase", "audit for over-engineering", "what can I delete from this repo", "find bloat", or invokes /ponytail-audit. Like ponytail-review but scans the entire tree, not a diff. One-shot report, applies no fixes. Gated by the ponytail audit_ponytail component.
license: MIT
metadata:
  author: ai-playbook (ported from DietrichGebert/ponytail, MIT)
  version: "1.0"
---

# ponytail-audit — whole-repo over-engineering audit

ponytail-review, repo-wide. Scan the whole tree instead of a diff. Rank findings
biggest cut first.

## When to fire

- "audit this codebase", "audit for over-engineering", "what can I delete from
  this repo", "find bloat", or `/ponytail-audit`.

## Hunt

Dependencies the stdlib or platform already ships, single-implementation
interfaces, factories with one product, wrappers that only delegate, files
exporting one thing, dead flags and config, hand-rolled stdlib.

## Output contract

Same tags as ponytail-review:

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, layer with one caller.
- `shrink:` same logic, fewer lines. Show the shorter form.

One line per finding, ranked biggest cut first:
`<tag> <what to cut>. <replacement>. [path]`.

End with `net: -<N> lines, -<M> deps possible.` Nothing to cut: `Lean already. Ship.`

## Boundaries

Complexity only. Correctness bugs, security holes, and performance go to a normal
review pass. Lists findings, applies nothing. One-shot. "stop ponytail-audit" /
"normal mode" reverts.

## See also

- [skills/ponytail-review/SKILL.md](../ponytail-review/SKILL.md) — the same lens, scoped to the current diff.
- [skills/ponytail/SKILL.md](../ponytail/SKILL.md) — the lazy-mode ruleset.
