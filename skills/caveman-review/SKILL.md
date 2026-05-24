---
name: caveman-review
description: Use when the user wants a pull-request review delivered as one-line comments with severity emoji, line references, and direct fix suggestions instead of paragraphs.
license: MIT
metadata:
  author: ai-playbook (ported from JuliusBrussee/caveman, MIT)
  version: "1.0"
---

# caveman-review — one-line PR review

Review a diff or a small set of files and emit one finding per line, in a fixed shape.

## When to fire

User intent triggers (any of):
- "/caveman-review"
- "review this PR", "review the diff", "review my changes"
- "what's wrong with this code", "give me a one-line review"

## Output contract

One finding per line, no preamble, no summary at the end. Exact shape:

```
<path>:<line>: <severity> <category>: <problem>. <fix>.
```

- `<severity>` ∈ `🔴 critical` | `🟠 high` | `🟡 medium` | `🟢 low` | `💬 nit`.
- `<category>` ∈ `bug` | `security` | `perf` | `correctness` | `style` | `test` | `doc`.
- `<problem>` ≤ 50 chars, caveman voice (drop articles, fragments OK).
- `<fix>` ≤ 50 chars, imperative voice.
- Sort: severity descending, then path, then line.
- If nothing is wrong: emit the single line `LGTM. No issues found.`

## Steps

1. **Get the diff.** Run `git diff <base>...HEAD` if reviewing a branch, or `git diff --cached` if reviewing staged changes. If the user passed a specific PR number, use `gh pr diff <n>`.

2. **Refuse if too large.** If the diff exceeds ~400 lines or touches more than 5 files, emit `OUT_OF_SCOPE: diff too large (<lines>L, <files>F), split first.` and stop.

3. **Walk every changed line.** For each line, ask:
   - Does this introduce a bug?
   - Does this open a security hole (injection, missing auth check, leaked secret)?
   - Does this regress performance (N+1 query, unbounded loop, sync I/O in hot path)?
   - Is correctness obvious (off-by-one, missing null guard, wrong comparison)?
   - Is the test coverage adequate for the change?
   - Are docs out of date with the change?
   - Style nits ONLY if they break the project's existing style.

4. **Write the findings.** One per real issue. Do not pad. Do not duplicate.

5. **Output.** Just the lines. No "Here's my review:". No "Hope this helps." No closing remark.

## Trust boundary

- Do not invent issues to look thorough. Empty result is acceptable; emit `LGTM. No issues found.`
- Do not post the review to GitHub. The skill drafts; the user posts.
- Do not mark `🔴 critical` for style or nit issues. Reserve that severity for actual production-breaking risks.

## Examples

```
scripts/caveman/toggle.py:42: 🔴 critical bug: race on flag write. Use temp+rename.
scripts/caveman/cli.py:88: 🟠 high security: shell=True with user input. Use list args.
scripts/caveman/mcp_shrink.py:120: 🟡 medium correctness: silent ignore of error. Log and raise.
tests/test_caveman_toggle.py:30: 🟢 low test: only happy path covered. Add schema-fail case.
docs/runbooks/caveman-toggle.md:55: 💬 nit doc: stale path reference. Update to new location.
```

## See also

- [skills/caveman/SKILL.md](../caveman/SKILL.md) — base caveman ruleset.
- [skills/caveman/agents/cavecrew-reviewer.md](../caveman/agents/cavecrew-reviewer.md) — subagent version for batched review.
