---
name: openspec-apply-parallel
description: Implement an OpenSpec change in parallel using multiple subagents (one per disjoint task group inside the same slice). Use when the slice's tasks.md has ≥2 task groups with disjoint write-paths AND >30 min of parallelisable work. For sequential implementation use openspec-apply-change instead.
license: Apache-2.0
metadata:
  author: ai-playbook
  version: "1.0"
  spec: specs/release-management.md §6.6
---

Implement a multi-group OpenSpec change with parallel subagents.

**Input**: Required: a change name. Optional: `--dry-run` to print the planned spawn matrix without actually spawning.

## When to use this skill (gating questions)

You MUST answer YES to all four before invoking this skill. If any is NO, fall back to `/opsx:apply` (sequential):

1. **Multi-group**: does `tasks.md` declare ≥2 task groups with explicit `**Owns:**` write-paths in their headers?
2. **Disjoint**: are those write-paths non-overlapping? (no two groups touch the same directory subtree)
3. **>30 min**: is the parallelisable work substantial? Rule of thumb: each group has ≥10 tasks, OR cumulative parallel work is ≥30 min wall-clock. Below that, recombination overhead (~10-15 min) wipes the saving.
4. **Pre-allocated migration numbers**: if the slice creates DB migrations, are sequence numbers reserved per group in `tasks.md` (NOT chosen by subagents)?

If you can't answer YES to all four, the slice is mis-sliced for parallel execution. Either re-slice, OR run sequentially via `/opsx:apply`.

## Steps

### 1. Select the change

If a name is provided, use it. Otherwise:
- Infer from conversation context if the user mentioned a change.
- Auto-select if only one active change exists.
- If ambiguous, run `openspec list --json` and ask the user to pick.

Announce: "Parallel-applying change: `<name>`. Spawn matrix below."

### 2. Read the contract artifacts (no edits)

Read in this order:
- `openspec/changes/<change-id>/proposal.md` — scope.
- `openspec/changes/<change-id>/design.md` — design decisions.
- `openspec/changes/<change-id>/tasks.md` — REQUIRED. Identify task groups + their write-path ownership headers.
- `.ai-playbook/specs/release-management.md` §6.6 — the contract you'll follow.

### 3. Cross-check ownership (BEFORE spawning anything)

Build a table from the per-group `**Owns:**` declarations in `tasks.md`:

| Group ID | Branch (`slice/<id>--<group>`) | Owns paths | Reads (no edit) | Migration #s reserved |
|---|---|---|---|---|
| §2 IAM | `slice/module-1-ingredients-impl--iam` | `apps/api/src/iam/**`, `migrations/0001-0004_*.ts` | `data-source.ts`, `app.module.ts` | 0001-0004 |
| §3 Ingredients | `slice/module-1-ingredients-impl--ingredients` | `apps/api/src/ingredients/**`, `migrations/0005-0009_*.ts` | (same) | 0005-0009 |
| ... | ... | ... | ... | ... |

Verify:
- **No two groups own the same path** (any subtree overlap → abort, fall back to sequential).
- **Migration numbers are non-overlapping** (gaps OK; overlaps NOT OK).
- **Shared files** (`app.module.ts`, `package.json`, `data-source.ts`, top-level `tsconfig`, `Makefile`, `pyproject.toml` runtime deps) are NOT owned by any group — flag them as "main agent recombination work".

If the cross-check fails, STOP and tell the user: "tasks.md ownership is inconsistent (concrete reason). Re-slice via /opsx:propose, or sequentialize via /opsx:apply." Do NOT proceed.

### 4. Pre-flight (per §6.5 + §6.6 pre-conditions)

```bash
git fetch origin
BASE_SHA=$(git rev-parse --short origin/main)
git checkout slice/<change-id>
git rebase origin/main   # abort on conflict; tell user to re-slice
```

For each group, create the ephemeral branch (NOT pushed to origin):

```bash
git branch slice/<change-id>--<group-id> $BASE_SHA
```

### 5. Print the spawn matrix (and if `--dry-run`, stop here)

Show the user the table from step 3 + the planned subagent count. Confirm: "Spawning N subagents. Continue?" If they say no, stop. If `--dry-run`, stop after printing.

### 6. Spawn subagents in parallel (single message, multiple Agent tool calls)

For each group, invoke the `Agent` tool with `isolation: "worktree"` and a scoped prompt. CRITICAL: all calls go in **one message** so they run concurrently. Each prompt MUST include:

- The branch to commit on: `slice/<change-id>--<group-id>` (DO NOT push to origin).
- The owned paths (write-allowed).
- The read-only paths (consult, don't edit).
- The reserved migration numbers (if any).
- The relevant subset of `tasks.md` (their group only).
- Return contract: "When done, return your branch name + the SHA range you committed (`<base-sha>..<head-sha>`)."

Template prompt for each subagent:

```
You are implementing task group <group-id> of OpenSpec change <change-id>.

## Owned paths (write here only)
<paths from tasks.md>

## Read-only paths (consult, don't edit)
<paths from tasks.md>

## Reserved migration numbers
<migration #s>

## Tasks
<the task group's tasks from tasks.md>

## Contract
1. Implement every task in the list. Mark each `- [ ]` → `- [x]` in tasks.md as you complete it.
2. Commit ONLY to branch `slice/<change-id>--<group-id>`. Do NOT push to origin.
3. Do NOT edit ANY file outside the owned paths.
4. Run the slice's local tests scoped to your group (e.g. `pytest apps/api/tests/<group-dir>/`) before each commit.
5. When all tasks are done, return: branch name + SHA range (`<base>..<head>`).

If you discover a task requires editing a shared file, STOP and return: "blocked: needs <file> edit (out of scope for this group)". The main agent will handle shared files in recombination.
```

### 7. Await completion + collect results

Each subagent returns its branch name + commit SHA range. Build the recombination plan:

```
Recombination order (apply in dependency order — leaf groups first, shared-state last):
  1. <group-A> commits: <sha>..<sha>
  2. <group-B> commits: <sha>..<sha>
  ...
  N. Main agent: shared file updates (app.module.ts, package.json, data-source.ts)
```

If ANY subagent returned `blocked: ...`, stop. Show the user which group blocked + on what file. They decide: split the slice, or sequentialize.

### 8. Recombine onto `slice/<change-id>` (sequential, main agent only)

```bash
git checkout slice/<change-id>
for group in <ordered groups>; do
  git cherry-pick <group's-sha-range>
done
# Now update shared files (the parts no subagent owned).
# Examples: register modules in app.module.ts, aggregate deps in package.json,
#           wire migrations into data-source.ts.
```

### 9. Run the FULL test suite (NOT scoped to a group)

```bash
# Slice-wide. Fails here = recombination conflict or untracked shared file.
pytest apps/api/tests/   # (or the equivalent for your stack)
```

If the test fails:
- **Conflict in shared files** → fix the shared-file edit in step 8 + re-run.
- **Two groups had implicit cross-dependency not caught in step 3** → ABORT recombination (`git reset --hard origin/main` on `slice/<id>`) + fall back to sequential `/opsx:apply`. File a slicing-too-coarse retro for next time.

### 10. Push the slice branch + open PR

```bash
git push -u origin slice/<change-id>
```

Then follow the standard `/opsx:apply` post-implementation flow: open PR, populate §4.5 AI-reviewer signoff, await reviews, gate F, archive.

### 11. Clean up ephemeral branches

```bash
for group in <groups>; do
  git branch -D slice/<change-id>--<group-id>   # local only; never were on origin
done
```

## Anti-patterns (each is a goal_drift per agentic-failures.md §X)

- **Subagent edits a file outside owned paths** → caught by main agent during cross-check at recombination time. If it slipped through, ABORT + fall back to sequential.
- **Subagent pushes to a public branch** (`origin/slice/...` or `origin/feat/...`) → reject the work. Branches MUST stay local until the main agent pushes the bundled `slice/<change-id>`.
- **Main agent skips the cross-check step 3 and spawns with overlapping ownership** → race conditions in cherry-pick. Cross-check is non-negotiable.
- **Migration numbers chosen by subagents instead of pre-allocated in step 3** → migration sequence collisions on recombination. Numbers come from the spec, not from subagent inference.

## Hard limit

This pattern caps at the number of disjoint bounded contexts the slice covers. Most slices have 1–2 (use `/opsx:apply`); modules-as-foundation slices have 3–5; nothing in the playbook spawns >6 subagents inside one slice (above that, the slice is mis-sliced — see [runbook-bmad-openspec.md](../../specs/runbook-bmad-openspec.md) §2.2).

## When this skill is the wrong tool

Fall back to `/opsx:apply` (sequential) when:
- The slice has 1 task group, OR
- Task groups are TDD-tight (interface → impl → consumer cannot be parallelised), OR
- Each group is <10 tasks (overhead exceeds saving), OR
- Cross-checks in step 3 reveal overlapping ownership.

## References

- `specs/release-management.md` §6.6 — the contract this skill implements.
- `specs/runbook-bmad-openspec.md` §3.8 — pointer to §6.6.
- `skills/openspec-apply-change/SKILL.md` — the sequential cousin.
