# stacked-pr-guard

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

2026-08-01, in this repo. PR #145 was stacked on #144. #144 merged with
`--delete-branch`, and GitHub closed #145 the moment its base branch
disappeared. That close is terminal: `gh pr reopen` answers "Could not open the
pull request" and `gh pr edit --base` answers "Cannot change the base branch of
a closed pull request". The commits survived on the head branch, so no work was
lost, but the pull request had to be replaced by #146 — discarding its review
thread and CI history.

The failure is one of ordering, and it has no recovery path, only a prevention
path: retarget dependents onto the merging PR's base BEFORE the merge. That is
exactly the kind of mechanical precondition a hardrule exists for, and the
project norm is hooks over prompts.

## What

- New rule `stacked-pr-guard` (md + hardrule + 11 tests). `validate --pr <n>`
  lists open PRs whose base is this PR's head and exits 1 with the exact
  retarget command for each, 0 when there are none, and 2 when the answer could
  not be determined — a guard that reports "all clear" because `gh` was missing
  is worse than no guard.
- Rule Map entry in `AGENTS.md`; `enforcement-status` row at ✅ wired.
- Regenerated rule/concept indexes.

## Release

`VERSION` → 0.20.1. Patch-level feature (one advisory-shaped pre-merge gate, no
consumer surface removed). Pull model.
