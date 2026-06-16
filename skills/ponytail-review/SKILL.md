---
name: ponytail-review
description: Use when the user wants a code review focused exclusively on over-engineering — says "review for over-engineering", "what can we delete", "is this over-engineered", "simplify review", or invokes /ponytail-review. Complements correctness/security review; this one only hunts complexity in the current diff. Gated by the ponytail review_ponytail component.
license: MIT
metadata:
  author: ai-playbook (ported from DietrichGebert/ponytail, MIT)
  version: "1.0"
---

# ponytail-review — over-engineering review of the current diff

Review the current changes for unnecessary complexity only. One line per
finding: location, what to cut, what replaces it. The diff's best outcome is
getting shorter.

## When to fire

- "review for over-engineering", "what can we delete", "is this over-engineered",
  "simplify review", or `/ponytail-review`.
- After a ponytail (or any) coding session, as a complexity pass before commit.

## Output contract

`L<line>: <tag> <what>. <replacement>.`, or `<file>:L<line>: ...` for
multi-file diffs.

Tags:

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, layer with one caller.
- `shrink:` same logic, fewer lines. Show the shorter form.

## Examples

❌ "This EmailValidator class might be more complex than necessary, have you
considered whether all these validation rules are needed at this stage?"

✅ `L12-38: stdlib: 27-line validator class. "@" in email, 1 line — real validation is the confirmation mail.`

✅ `L4: native: moment.js imported for one format call. Intl.DateTimeFormat, 0 deps.`

✅ `repo.py:L88: yagni: AbstractRepository with one implementation. Inline it until a second one exists.`

✅ `L52-71: delete: retry wrapper around an idempotent local call. Nothing replaces it.`

✅ `L30-44: shrink: manual loop builds dict. dict(zip(keys, values)), 1 line.`

## Scoring

End with the only metric that matters: `net: -<N> lines possible.`

If there is nothing to cut, say `Lean already. Ship.` and stop.

## Boundaries

Complexity only. Correctness bugs, security holes, and performance go to a normal
review pass (`/code-review`), not this one. A single smoke test or `assert`-based
self-check is the ponytail minimum, not bloat — never flag it for deletion.
Lists findings; applies nothing. "stop ponytail-review" / "normal mode" reverts
to verbose review style.

## See also

- [skills/ponytail/SKILL.md](../ponytail/SKILL.md) — the lazy-mode ruleset this enforces in review form.
- [skills/ponytail-audit/SKILL.md](../ponytail-audit/SKILL.md) — the same lens, repo-wide instead of diff-scoped.
- [skills/caveman-review/SKILL.md](../caveman-review/SKILL.md) — the terse-prose PR-review twin.
