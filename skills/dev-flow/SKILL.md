---
name: dev-flow
description: Orchestrate the canonical task↔PR↔release flow end-to-end. Two modes — `/dev-flow start <description>` scaffolds an OpenSpec change + branch + (optional) worktree + git hook ready for commits; `/dev-flow ship` validates the current branch + pushes + opens PR + monitors CI. Use whenever you start any non-trivial change in a playbook-consuming project. LLM-agnostic — works for Claude Code, Cursor, Antigravity, Gemini CLI, OpenCode, and humans.
license: Apache-2.0
metadata:
  author: ai-playbook
  version: "1.0"
  spec: docs/development-flow.md
---

Orchestrate the playbook's canonical developer flow: from "I want to make a change" to "PR is open and CI is green" without re-reading 5+ specs each time.

**Input**:
- `start <description>` — start a new change. Description should name the capability (e.g. "add Telegram retry-with-backoff to notification queue"). Optional flags: `--type <feat|fix|chore|...>` (default `feat`), `--change-id <slug>` (default derived from description), `--no-worktree` (default: auto-detects N≥3 concurrent slices), `--no-hook` (skip auto-tick git hook install).
- `ship` — push current branch + open PR + verify CI. No args. Optional: `--draft` to open as draft, `--auto-merge` to enable auto-merge once CI passes.

## When to use this skill

**Use `/dev-flow start`** when starting any non-trivial change:
- Anything that creates new files OR touches > 50 lines OR spans > 5 commits → use this skill.
- Trivial 1-line fixes (typo, version bump) — bypass with a regular `fix/<short-id>` branch + manual PR. The skill is overhead at that scale.

**Use `/dev-flow ship`** when your branch is implementation-complete:
- All tests pass locally
- All `tasks.md` boxes ticked (or auto-tick git hook handled it)
- Pre-commit clean
- You're ready to open the PR

For sequential implementation **inside** the change: standard `/opsx:apply`. For multi-group parallel implementation: `/opsx:apply-parallel`. The dev-flow skill is the OUTER orchestrator; opsx skills are inner.

## Steps — `/dev-flow start <description>`

### 1. Resolve change-id

If `--change-id` provided, use it. Otherwise derive from the description:
- Lowercase, replace spaces with `-`, strip non-`[a-z0-9-]` chars.
- Strip leading/trailing dashes; collapse double-dashes.
- Truncate to 50 chars max.

Reject if: change-id matches an existing `openspec/changes/<id>/` AND that change is not in archive (= still in flight). Print: "change-id `<id>` is already in flight; pick a new one or `cd openspec/changes/<id>` to extend it."

### 2. Confirm or scaffold the OpenSpec change

If `openspec/changes/<change-id>/` does not exist:

```
/opsx:propose --no-slice <change-id>
```

This creates `proposal.md` + `tasks.md` + `specs/` skeleton. The user fills in the proposal body before committing.

If it exists and has `archive/` child: refuse — change is already shipped.
If it exists without `archive/`: warn "extending an in-flight change; confirm intent" + proceed.

### 3. Branch + worktree

Read the type flag (default `feat`). Branch name: `<type>/<change-id>`.

**Worktree decision** (per docs/development-flow.md §2 + git-worktree-bare-layout.md):
- Count branches with `git worktree list`. If `--no-worktree` is set OR count < 3 → simple branch:
  ```
  git checkout -b <type>/<change-id>
  ```
- Otherwise (≥ 3 worktrees, parallelism in flight) → use `wt_add.py`:
  ```
  python .ai-playbook/scripts/wt_add.py <change-id> --branch-type <type>
  ```
  This creates a worktree at `worktrees/<change-id>/` with submodules + ecosystem deps installed (per PR #32 in v0.9.3).

### 4. Install the auto-tick git hook (idempotent)

Unless `--no-hook` is set, ensure the prepare-commit-msg hook is installed:

```bash
HOOK_SRC=".ai-playbook/templates/git-hooks/prepare-commit-msg"
HOOK_DST=".git/hooks/prepare-commit-msg"
if [ ! -f "$HOOK_DST" ] || ! cmp -s "$HOOK_SRC" "$HOOK_DST"; then
  cp "$HOOK_SRC" "$HOOK_DST"
  chmod +x "$HOOK_DST"
  echo "✅ Installed auto-tick git hook"
fi
```

The hook is local to each developer's checkout (git does not version `.git/hooks/`); the skill installs it once per branch creation. After install, every `git commit` parses the conventional-commit subject and ticks matching `tasks.md` boxes (per Followup #4 / scripts/auto_tick_tasks.py).

### 5. Print the canonical entry

```
✅ dev-flow: <change-id> scaffolded

Branch:    <type>/<change-id>
Worktree:  <path or "main working tree">
Tasks:     openspec/changes/<change-id>/tasks.md
Hook:      installed (auto-ticks boxes from conventional-commit subject)

Next steps:
  1. Edit proposal.md → fill in problem + approach + decisions
  2. Edit tasks.md   → expand the task list
  3. Implement: standard commits with conventional-commit subjects
       feat(<change-id>): groups 1-3
       chore: §2.1 + §2.2
       fix: task 5
     The hook will auto-tick matching boxes.
  4. When implementation-complete, run /dev-flow ship to open the PR.

References:
  - docs/development-flow.md  (canonical end-to-end flow)
  - specs/release-management.md §4 §6.5 (PR shape, pre-flight rebase)
  - specs/merge-policy.md (squash vs merge-commit decision)
```

## Steps — `/dev-flow ship`

### 1. Pre-flight checks

```bash
# Branch shape
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if ! [[ "$BRANCH" =~ ^(feat|fix|chore|docs|refactor|test|release)/[a-z0-9][a-z0-9-]*$ ]]; then
  echo "❌ Branch '$BRANCH' does not match canonical pattern <type>/<change-id>."
  echo "   FIX: rename via 'git branch -m <new-name>' or use a chore/* prefix for hot-fixes."
  exit 1
fi

CHANGE_ID="${BRANCH#*/}"

# OpenSpec change exists?
case "$BRANCH" in
  chore/*) ;; # exempt — chore branches don't need an OpenSpec dir
  *)
    if [ ! -d "openspec/changes/$CHANGE_ID" ]; then
      echo "❌ openspec/changes/$CHANGE_ID/ does not exist."
      echo "   FIX: create proposal first via /opsx:propose --no-slice $CHANGE_ID"
      exit 1
    fi
    ;;
esac
```

### 2. Local validation

In order — abort on first failure:

```bash
# Working tree clean
git diff --quiet && git diff --cached --quiet || {
  echo "❌ Uncommitted changes. Commit or stash first."
  exit 1
}

# Pre-commit (run on the branch's diff)
python -m pre_commit run --from-ref main --to-ref HEAD || exit 1

# Targeted tests (heuristic: discover changed test files OR fall back to full)
CHANGED_TESTS=$(git diff --name-only main..HEAD | grep -E '^tests/' || true)
if [ -n "$CHANGED_TESTS" ]; then
  python -m pytest -p no:asyncio $CHANGED_TESTS -q || exit 1
else
  python -m pytest -p no:asyncio -q || exit 1
fi

# Ruff
python -m ruff check . || exit 1
```

### 3. tasks.md completeness check

```bash
TASKS_FILE="openspec/changes/$CHANGE_ID/tasks.md"
if [ -f "$TASKS_FILE" ]; then
  TOTAL=$(grep -cE '^\s*-\s*\[[ xX]\]' "$TASKS_FILE")
  UNCHECKED=$(grep -cE '^\s*-\s*\[ \]' "$TASKS_FILE")
  if [ "$UNCHECKED" -gt 0 ]; then
    PCT=$(( (TOTAL - UNCHECKED) * 100 / TOTAL ))
    echo "⚠️  tasks.md: ${PCT}% ticked, $UNCHECKED unchecked. Continue? [y/N]"
    read -r REPLY
    [ "$REPLY" = "y" ] || exit 1
  fi
fi
```

### 4. Push branch

```bash
git push -u origin "$BRANCH"
```

If the branch already exists on remote: `git push` (no `-u`).

### 5. Open PR

PR title: derived from the LAST commit subject (or first commit if branch has 1 commit).

PR body template (auto-generated from commit log):

```
## Summary

<auto-generated from `git log main..HEAD --pretty=%s` — bullet per commit>

## Test plan

- [x] Pre-commit clean
- [x] Targeted tests green (<N> passed)
- [x] Ruff clean
- [ ] CI green
- [ ] CodeRabbit review pass
- [ ] Reviewer signoff

## Cross-references

- `openspec/changes/<change-id>/proposal.md`

EOF
```

```bash
gh pr create --base main \
  --title "$(git log -1 --pretty=%s)" \
  --body "$(cat <<EOF
## Summary

$(git log main..HEAD --pretty='- %s')

## Test plan

- [x] Pre-commit clean
- [x] Targeted tests green
- [x] Ruff clean
- [ ] CI green
- [ ] CodeRabbit review pass
- [ ] Reviewer signoff

## Cross-references

- \`openspec/changes/$CHANGE_ID/proposal.md\`
EOF
)" \
  ${DRAFT_FLAG:+--draft}
```

### 6. Monitor CI (optional, depends on user preference)

```bash
PR_NUM=$(gh pr view --json number --jq .number)
echo "✅ PR #$PR_NUM opened. Waiting for CI..."
gh pr checks "$PR_NUM" --watch
```

If `--auto-merge` flag was passed, enable it:

```bash
gh pr merge "$PR_NUM" --auto --merge
```

### 7. Print next steps

```
✅ dev-flow: shipped

PR:        https://github.com/.../pull/<N>
Branch:    <type>/<change-id>
Commits:   <N> commits ahead of main
Diff:      <added> +/<deleted> -

Next steps:
  1. Address review feedback (CodeRabbit + 3-layer review per parallel-review.md).
  2. Once approved, merge:
       gh pr merge <N> --merge --delete-branch    # (multi-commit, semantic — D2.1)
       gh pr merge <N> --squash --delete-branch   # (single-commit / trivial — D2.2)
     (See specs/merge-policy.md for the decision rule.)
  3. After merge, archive the OpenSpec change:
       openspec archive <change-id>
     (Verifies tasks.md is N/N ticked per Followup #4.)
  4. If this is the last PR for the next release, see runbooks/release.md
     for the release-cut PR + tag procedure.
```

## Decisions

- **D1.1** Two modes (`start`, `ship`) cover the lifecycle endpoints; the middle (implementation) is delegated to `/opsx:apply` (sequential) or `/opsx:apply-parallel` (multi-group). Rationale: the skill is an orchestrator, not a code generator.
- **D1.2** Conventional-commit subjects auto-tick `tasks.md` via the pre-installed git hook. Rationale: per Followup #4, manual ticking drifts; auto-tick from commit subject is the only reliable channel.
- **D1.3** Pre-flight runs `pre-commit + pytest + ruff` in order. Rationale: the cheapest checks first; a ruff failure is a 10s fix, a test failure may be 30 min — fail-fast cascades.
- **D1.4** PR body is auto-generated from commit log. Rationale: encourages good commit messages by making them visible in the PR description.
- **D1.5** The skill suggests but does NOT decide merge style. Rationale: per merge-policy.md D2.3, the maintainer always has final decision; the advisor (`pr-merge-style.yml` workflow) provides the recommendation.
- **D1.6** No automatic `openspec archive` — the maintainer drives archive after merge. Rationale: archive depends on confirming the merge actually shipped without revert; automating it would be premature.

## Anti-patterns

- **Bypassing `/dev-flow start` for "I'll just commit directly"**: ends up with a branch named `my-changes` that fails branch-name-validator at PR-open time. The 30-second cost of running the skill saves the rename + force-push later.
- **`/dev-flow ship` before all tasks ticked**: the skill warns; if you `y` past it, `check-tasks-checkboxes.yml` will comment on the PR with the gap. Tick honestly OR file a `tasks.md` amendment first.
- **Running `/dev-flow start` inside an existing in-flight change directory**: refused — the skill won't extend an in-flight change without `--extend` (not yet implemented; manual `cd` required for now).

## Cross-references

- [`docs/development-flow.md`](../../docs/development-flow.md) — the canonical doc this skill operationalises.
- [`specs/release-management.md`](../../specs/release-management.md) — release process the skill respects.
- [`specs/merge-policy.md`](../../specs/merge-policy.md) — squash vs merge-commit (skill suggests, doesn't decide).
- [`specs/conflict-resolution-policy.md`](../../specs/conflict-resolution-policy.md) — what happens when 2 ships collide.
- [`scripts/auto_tick_tasks.py`](../../scripts/auto_tick_tasks.py) — the auto-tick implementation triggered by the hook.
- [`templates/git-hooks/prepare-commit-msg`](../../templates/git-hooks/prepare-commit-msg) — the hook this skill installs.
- [`scripts/wt_add.py`](../../scripts/wt_add.py) — worktree creation (when ≥ 3 concurrent slices).
- [`skills/openspec-propose/SKILL.md`](../openspec-propose/SKILL.md) — used internally by `start` to scaffold the proposal.
- [`skills/openspec-apply-change/SKILL.md`](../openspec-apply-change/SKILL.md) — sequential implementation (called between `start` and `ship`).
- [`skills/openspec-apply-parallel/SKILL.md`](../openspec-apply-parallel/SKILL.md) — parallel implementation when tasks.md has disjoint groups.
