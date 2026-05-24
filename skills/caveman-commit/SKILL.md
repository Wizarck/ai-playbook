---
name: caveman-commit
description: Use when the user asks for a commit message, wants a Conventional Commit, or wants a terse commit subject that fits in fifty characters and focuses on why over what.
license: MIT
metadata:
  author: ai-playbook (ported from JuliusBrussee/caveman, MIT)
  version: "1.0"
---

# caveman-commit — terse Conventional Commit messages

Write commit messages that are short, conventional, and focused on intent.

## When to fire

User intent triggers (any of):
- "/caveman-commit"
- "write the commit message", "draft a commit", "commit this"
- "give me a Conventional Commit"

## Output contract

Always emit a Conventional Commit. Shape:

```
<type>(<scope>): <subject>

<body — optional, only if subject does not capture the why>
```

Rules:
- `<type>` ∈ `feat` | `fix` | `refactor` | `perf` | `docs` | `test` | `chore` | `build` | `ci` | `style`.
- `<scope>` ≤ 14 chars, kebab-case, optional. Drop the parentheses if no scope.
- `<subject>` ≤ 50 chars, lowercase, no trailing period. Imperative voice ("add", not "added"/"adds").
- `<body>` only when the subject cannot fit the why. Wrap at 72 chars. Caveman style: drop articles, fragments OK.
- No "Generated with Claude" footer unless the user explicitly asks for it.
- No emoji in subject. Body may use them sparingly if the user's repo style allows.

## Steps

1. **Read the diff.** Run `git diff --cached` (staged) or `git diff` (unstaged) — whichever the user pointed at. If both are empty, refuse with `Nothing staged or modified to commit.`

2. **Identify intent.** What is the user trying to accomplish? Look at:
   - Added/removed lines, not just file count.
   - Renamed identifiers vs new logic vs deleted code.
   - Whether tests changed alongside production code.

3. **Pick the type.**
   - New user-visible behavior → `feat`.
   - Bug fix → `fix`.
   - Internal restructure, no behavior change → `refactor`.
   - Performance improvement → `perf`.
   - Documentation only → `docs`.
   - Tests only → `test`.
   - Build/CI/deps → `build`/`ci`/`chore`.

4. **Pick the scope.** Usually a directory or module name from the changed paths. Drop if scope spans multiple unrelated areas.

5. **Write the subject — why over what.**
   - Bad: `fix(auth): change `<` to `<=` in token expiry check`
   - Good: `fix(auth): close one-second token expiry gap`
   - Bad: `feat: add new endpoint`
   - Good: `feat(api): support batch user lookup`

6. **Add a body only if needed.** If the subject explains the why, skip the body. Otherwise add a 1-2 sentence caveman-style paragraph.

## Trust boundary

- Never commit the message. The skill drafts it; the user runs `git commit`.
- Never include secrets, tokens, file contents from `.env`, or large diffs in the body.
- If the diff is empty, refuse — do not invent intent.

## Examples

```
feat(toggle): per-project caveman state at .ai-playbook/caveman.json
```

```
fix(mcp): guard against missing caveman-shrink binary

npx caveman-shrink absent on offline machines. Wrap call in
try/except, warn once, fall through to un-wrapped command.
```

```
refactor(scripts): single source of truth for skill descriptions
```

## See also

- [docs/rules/error-message-standard.rule.md](../../docs/rules/error-message-standard.rule.md) — verdict + commit conventions on this repo.
- [skills/caveman/SKILL.md](../caveman/SKILL.md) — base caveman ruleset.
