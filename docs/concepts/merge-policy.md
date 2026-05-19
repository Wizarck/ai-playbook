---
schema: concept/v1
slug: merge-policy
title: Merge Policy
summary: |
  This spec codifies when to use squash-merge vs merge-commit vs rebase-merge
  when landing PRs to main. The choice affects git log readability, git blame
  quality, and audit trail of authorial intent. Wrong default = either lost
  history (over-squashing) or noisy log…
last_validated: "2026-05-19"
---

# Merge Policy

This spec codifies when to use **squash-merge** vs **merge-commit** vs **rebase-merge** when landing PRs to `main`. The choice affects `git log` readability, `git blame` quality, and audit trail of authorial intent. Wrong default = either lost history (over-squashing) or noisy log (under-squashing).

---

## 1. The three merge styles

| Style | What it produces on main | When to use | Effect on history |
|---|---|---|---|
| **squash** | Single commit collapsing all branch commits | Trivial 1-commit PRs, lint cleanups, doc typo fixes | Loses individual commit messages; preserves PR-level narrative |
| **merge-commit** | Merge commit + all individual commits preserved | Multi-commit PRs with semantically distinct steps | Preserves authorial intent; `git log --first-parent` shows clean release history |
| **rebase-merge** | Linear history (no merge commit), individual commits preserved | When the team has agreed on linear history (not the playbook default) | Preserves commits but loses the "this was a PR" boundary marker |

**Playbook default**: **merge-commit**. Rationale: the playbook prefers preserving semantic commit history because OpenSpec changes typically have multiple logical steps that future-readers benefit from (Change C in PR #31 had 4 commits: feat / feat / fix lint / fix deps — each meaningful on its own).

---

## 2. Decision rules

### 2.1 Use **squash** when ALL of the following hold

- The PR has exactly **1 commit**, OR has multiple commits that are all variants of the same intent (typo fixes, lint reformat, "address review feedback ×3").
- The PR is a **trivial change**: doc typo, single-line fix, lint cleanup, dep version bump, configuration tweak.
- **Total diff < 50 lines added** (not counting auto-generated files).
- **No multiple files conceptually** — touching a single concern (one bugfix, one doc edit, one config).

Example matches:
- "fix(docs): typo in docs/runbooks/release.md" (1 commit, 1 line)
- "chore(deps): bump pytest 8.0 → 8.2" (1 commit, 1 file)
- "fix(lint): apply ruff --fix on PR #31" (1 commit, but multiple files — STILL squash because it's a single intent: lint cleanup)

### 2.2 Use **merge-commit** when ANY of the following hold

- The PR has **≥ 2 semantically distinct commits** (different `feat:`, `fix:`, `docs:` types — or same type but different concerns).
- The PR is a **substantive change**: new feature, refactor, multi-step migration.
- **Total diff ≥ 50 lines** AND the commits represent meaningful checkpoints.
- The PR implements an **OpenSpec change** with a `tasks.md` of multiple groups.

Example matches:
- "feat(litellm-routing) + feat(ir-and-model-migration) + fix(lint) + fix(deps)" (PR #31 — 4 commits, ~3500 lines, 2 OpenSpec changes)
- "feat(persistence): slice 3 tenant isolation" (multiple commits per group: domain, listeners, alembic, migration, tests)
- "refactor(advisor): split into worker + judge legs" (multi-step refactor with intermediate states)

### 2.3 Use **rebase-merge** when

- **Never as the playbook default.** The team has not agreed on linear history.
- If the maintainer chooses rebase-merge for a specific PR, document the rationale in the merge commit message.

---

## 3. The advisor workflow

`.github/workflows/pr-merge-style.yml` runs on every PR open + push and posts a comment recommending the merge style based on:

```
1. Count commits on the PR branch (= git rev-list --count <base>..<head>).
2. Compute total diff lines (added + deleted, excluding auto-generated paths).
3. Classify:
   - 1 commit AND < 50 lines diff           → recommend SQUASH
   - ≥ 2 commits with distinct conv-commit types  → recommend MERGE-COMMIT
   - ≥ 2 commits, all same intent (e.g. fix lint x3)  → recommend SQUASH
   - Tie / ambiguous                         → recommend MERGE-COMMIT (safer default)
4. Post (or update) a sticky PR comment with the recommendation
   and rationale. Maintainer can override.
```

The advisor is **not** a hard gate — the maintainer keeps final decision. Reasoning:
- Squashing a 4-commit PR with semantic history is a one-way information-loss; the tool advises, the human decides.
- Hard-blocking on style would create reviewer friction (especially for emergency hot-fixes where speed > narrative).
- The advisor's comment is a **checklist item** for review, not a gate.

---

## 4. GitHub repo settings (recommended)

To make the advisor effective, configure (in `Settings → General → Pull Requests`):

- ✅ **Allow merge commits** — required for merge-commit style (default)
- ✅ **Allow squash merging** — required for squash style
- ❌ **Allow rebase merging** — disabled (not playbook default; if needed for a specific PR, enable temporarily)
- ✅ **Always suggest updating pull request branches** — keeps PRs current with main
- ✅ **Automatically delete head branches** — cleanup post-merge
- ✅ **Default to PR title for squash merges** — uses conventional commit subject

These settings are documented here for reference; they are NOT enforced via this spec (require repo admin permissions). Each playbook consumer mirrors these settings in their own repo.

---

## 5. Cross-references

- [`docs/concepts/development-flow.md`](development-flow.md) §1 (hierarchy) and §5 (industrialisation) — referrer.
- [`docs/concepts/release-management.md`](release-management.md) — section §4 PR shape.
- [`.github/workflows/pr-merge-style.yml`](../../.github/workflows/pr-merge-style.yml) — the advisor implementation.
- [`docs/runbooks/release.md`](../runbooks/release.md) — the release-cut PR uses merge-commit (semantic checkpoints).

---

## 6. Decisions

- **D2.1** Default is merge-commit (not squash, not rebase). Rationale: preserves OpenSpec change semantic history.
- **D2.2** Squash only for trivial single-intent PRs. Rationale: collapsing semantically distinct commits into one is information-destructive.
- **D2.3** Advisor is soft enforcement (comment, not gate). Rationale: overriding for hot-fix paths must remain frictionless; audit trail (the advisor comment + maintainer's choice) is enough.
- **D2.4** Rebase-merge disabled by default. Rationale: linear history is a team-style choice; the playbook hasn't adopted it; flipping later is reversible.
