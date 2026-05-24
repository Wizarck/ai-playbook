---
schema: runbook/v1
slug: git-worktree-bare-setup
description: Set up the canonical bare-repo + per-branch worktree layout for a consumer project (greenfield, migration, or daily flow).
audience: developer
estimated_time: greenfield 5 min · migrate 10-15 min · daily 30 s per worktree
last_validated: "2026-05-19"
---

# Set up the bare-repo + per-branch worktree layout

## Outcome

The consumer project sits under `<project-root>/` with this canonical layout (per [Concept: git-worktree-bare-layout](../concepts/git-worktree-bare-layout.md)):

```
<project-root>/
├── .bare/                 # bare repo (single git database)
├── .git                   # pointer file: "gitdir: ./.bare"
├── master/                # default-branch worktree
└── <change-id>/           # one worktree per OpenSpec change in flight
```

The registry at `~/.ai-playbook/projects.yaml` keeps a single `path: <project-root>` entry (no per-worktree rows) and the dispatcher resolves cwd-in-`<wt>/` via the parent-of-cwd rule.

## When to use this

Pick the section matching the situation:

- **§1 Greenfield** — creating a new consumer repo from scratch.
- **§2 Onboard existing repo** — first-time clone of a repo already on GitHub.
- **§3 Migrate legacy single-tree** — converting an existing local clone to bare layout.
- **§4 Daily flow** — add or remove a worktree per OpenSpec change.

## Prerequisites

- `git --version` reports ≥ 2.36 (required for `git worktree repair`).
- `gh auth status` shows authenticated.
- `python --version` reports 3.11 or later.
- Write access to the repo and OS-level rename permission on the local directory.

## Steps

### 1. Greenfield — bootstrap a new consumer

```bash
PROJECT=my-new-project

mkdir -p /c/Projects/$PROJECT && cd /c/Projects/$PROJECT

# 1.1 Create the bare repo.
git clone --bare https://github.com/Wizarck/$PROJECT.git .bare

# 1.2 Reconfigure remote.origin.fetch so refs land under refs/remotes/origin/*.
#     The default --bare clone puts remote heads in refs/heads/, which conflicts
#     with how `git worktree add` creates local tracking branches.
git -C .bare config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
git -C .bare fetch origin --prune

# 1.3 Drop the pointer file so commands from the parent dir find the repo.
echo "gitdir: ./.bare" > .git

# 1.4 Add the default-branch worktree (auto-detect default).
DEFAULT=$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
git worktree add $DEFAULT $DEFAULT

# 1.5 Run consumer bootstrap inside the default worktree.
cd $DEFAULT
python /c/Projects/ai-playbook/scripts/bootstrap.py $PROJECT \
    --owner <your-email> \
    --path . \
    --register-in /c/Projects/ai-playbook \
    --visibility <public|private> \
    --default-branch $DEFAULT
```

### 2. Onboard existing repo (first clone, GitHub already has it)

Same as §1 with a real remote URL. The bootstrap step is skipped automatically if the repo already has `.ai-playbook/` and `AGENTS.md`.

### 3. Migrate a legacy single-tree clone

The repo is already cloned at `/c/Projects/<repo>/` with the working tree directly inside. Rebuild the bare layout as a sibling, swap, then `git worktree repair` the absolute paths.

#### 3.1 Pre-flight

```bash
cd /c/Projects/<repo>
git status --short                            # must be empty (or only gitignored)
git log --oneline @{upstream}..HEAD           # must be empty (no unpushed commits)
git worktree list                             # note any additional worktrees
```

If there are unpushed commits, `git push` first. If there is uncommitted work, commit or stash. If additional worktrees exist (e.g. `<repo>-feature-x/`), push their branches and plan to recreate them in §3.3.

#### 3.2 Backup untracked working files

```bash
mkdir -p /c/Projects/_migration-backup-<repo>
cp -R /c/Projects/<repo>/_bmad-output/research /c/Projects/_migration-backup-<repo>/ 2>/dev/null || true
cp /c/Projects/<repo>/.env /c/Projects/_migration-backup-<repo>/ 2>/dev/null || true
```

#### 3.3 Build the new layout as a sibling

```bash
mkdir -p /c/Projects/<repo>-new && cd /c/Projects/<repo>-new

git clone --bare $(git -C /c/Projects/<repo> remote get-url origin) .bare
git -C .bare config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
git -C .bare fetch origin --prune

echo "gitdir: ./.bare" > .git

DEFAULT=$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
git worktree add $DEFAULT $DEFAULT

# Recreate every additional worktree from §3.1:
git worktree add <change-id> slice/<change-id>

# Init submodules per worktree (submodules are per-working-tree).
for wt in $DEFAULT <change-id>; do
    (cd $wt && git submodule update --init --recursive)
done
```

#### 3.4 Restore untracked files into the new default worktree

```bash
cp -R /c/Projects/_migration-backup-<repo>/research /c/Projects/<repo>-new/$DEFAULT/_bmad-output/ 2>/dev/null || true
cp /c/Projects/_migration-backup-<repo>/.env /c/Projects/<repo>-new/$DEFAULT/ 2>/dev/null || true
```

#### 3.5 Atomic swap

On Linux or macOS:

```bash
cd /tmp
mv /c/Projects/<repo> /c/Projects/_<repo>-OLD-trash
mv /c/Projects/<repo>-new /c/Projects/<repo>
```

On Windows the cwd of any open Claude Code / VS Code session is held by the OS — see Troubleshooting `rename fails with Device or resource busy`.

#### 3.6 Repair worktree absolute paths

```bash
cd /c/Projects/<repo>/.bare
git worktree repair /c/Projects/<repo>/master /c/Projects/<repo>/<change-id>
git worktree list                              # all paths show /c/Projects/<repo>/...
```

If `git worktree repair` still complains, manually verify two files:

- `<repo>/<wt>/.git` must contain `gitdir: <repo>/.bare/worktrees/<wt>` (absolute path).
- `<repo>/.bare/worktrees/<wt>/gitdir` must contain `<repo>/<wt>/.git` (absolute path).

#### 3.7 Clean up the backups

Once a build + test + editor open in `master/` succeeds:

```powershell
Remove-Item -Recurse -Force C:/Projects/<repo>_old
Remove-Item -Recurse -Force C:/Projects/_migration-backup-<repo>
```

### 4. Daily flow — add and remove worktrees

#### 4.1 Add a worktree for a new OpenSpec change

```bash
cd /c/Projects/<repo>/.bare
python /c/Projects/ai-playbook/scripts/wt_add.py <change-id>
```

The helper creates `<repo>/<change-id>/` as a worktree on a fresh `slice/<change-id>` branch, branched from the project default, and runs `git submodule update --init --recursive`. It refuses to create a worktree whose `<change-id>` does not match an existing `openspec/changes/<id>/` folder; pass `--no-slice-check` for ad-hoc branches.

Manual equivalent:

```bash
cd /c/Projects/<repo>
git worktree add <change-id> -b slice/<change-id> origin/$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
(cd <change-id> && git submodule update --init --recursive)
```

#### 4.2 Remove a finished worktree

After the slice's PR is merged or closed:

```bash
cd /c/Projects/<repo>
python /c/Projects/ai-playbook/scripts/wt_remove.py <change-id>
```

The helper checks via `gh pr list --head slice/<change-id>` that the PR is `MERGED` or `CLOSED` before doing anything (pass `--force` to bypass — e.g. for ad-hoc branches that were never PR'd). It then runs `git worktree remove --force <change-id>` (the `--force` is needed because the worktree contains submodule directories git's bookkeeping does not track), wipes any submodule residue that survives, and finally runs `git branch -D slice/<change-id>` to retire the local branch.

Flags:

- `--force` — skip the PR-state gate (useful when no PR exists or when `gh` is unavailable).
- `--keep-branch` — remove only the worktree; preserve the local branch.
- `--dry-run` — print the exact commands the helper would run without executing them.

Manual equivalent (matches the helper's behavior):

```bash
cd /c/Projects/<repo>
git worktree remove --force <change-id>
rm -rf <change-id>                              # if force-remove leaves submodule dirs
git branch -D slice/<change-id>                 # cleanup local branch
```

#### 4.3 Bulk-clean zombie slice/* branches

When many PRs have been merged without their worktree+branch being retired (a common drift on long-lived projects), use the sweep helper to retire them in one pass:

```bash
cd /c/Projects/<repo>
python /c/Projects/ai-playbook/scripts/wt_sweep.py             # dry-run plan
python /c/Projects/ai-playbook/scripts/wt_sweep.py --apply     # execute
python /c/Projects/ai-playbook/scripts/wt_sweep.py --apply --remote
                                                               # also delete origin/*
```

The sweeper enumerates every local branch matching `slice/*`, queries GitHub via `gh pr list --head <branch>` for each, and prints a table with the action it would take (`DELETE` for MERGED/CLOSED, `skip` for OPEN or no-PR). The default is a dry-run; `--apply` executes the plan; `--remote` additionally deletes the matching remote branch (useful when the GitHub repo doesn't have "Automatically delete head branches" enabled).

Pair with `--include-worktrees` if some merged branches still have their worktree directories around — the sweeper will retire those too.

**Tip — prefer auto-delete at the source**: enabling **Settings → General → Pull Requests → "Automatically delete head branches"** in the GitHub repo eliminates the source of zombie remote branches at merge time, so `wt_sweep.py --remote` becomes unnecessary in steady state. The sweep helper remains useful for clearing accumulated drift in projects that adopt the policy retroactively.

## Verification

```bash
cd /c/Projects/<repo>
git worktree list
# Expected:
# /c/Projects/<repo>/.bare      (bare)
# /c/Projects/<repo>/master     <sha>  [master]
# /c/Projects/<repo>/<change-id> <sha> [slice/<change-id>]

git -C master status --short                    # clean
git -C master submodule status                  # all submodules at expected SHAs
git -C master log --oneline -3                  # last commits match origin/$DEFAULT
```

The registry at `~/.ai-playbook/projects.yaml` needs no editing — `path: C:/Projects/<repo>` resolves cwd-in-`<repo>/master/` via the parent-of-cwd rule (per [Concept: dispatcher-chain](../concepts/dispatcher-chain.md)).

## Troubleshooting

### Symptom: rename fails with "Device or resource busy" on Windows during §3.5
**Cause**: an editor or terminal has cwd inside `/c/Projects/<repo>/`. Windows holds the directory handle open.
**Fix**:
1. Close every Claude Code session and editor with cwd inside `/c/Projects/<repo>/`.
2. Open a fresh terminal outside any of those tools (Windows Terminal, PowerShell, cmd).
3. Run the rename in PowerShell:
   ```powershell
   Move-Item -Path C:/Projects/<repo> -Destination C:/Projects/<repo>_old
   Move-Item -Path C:/Projects/<repo>-new -Destination C:/Projects/<repo>
   ```
4. Reopen the editor at `C:/Projects/<repo>/master/` — not the parent dir, which has no source files.

### Symptom: `git worktree remove --force` leaves the directory behind on Windows
**Cause**: VS Code language server, file watcher, or antivirus is still holding handles inside the worktree.
**Fix**: stop the holder (shut down the IDE / kill the watcher / wait for AV) and re-run the remove, OR manually delete: `powershell -Command "Remove-Item -Path '<change-id>' -Recurse -Force"`. See [Runbook: windows-dev-environment](windows-dev-environment.md) §4 for the canonical writeup.

### Symptom: §3 fails partway and the new layout is unusable
**Cause**: any step from §3.3-§3.6 errored — most often the bare clone or the worktree add.
**Fix (rollback)**:
1. The original `<repo>/` is preserved at `<repo>_old/`. Reverse the §3.5 rename to restore.
2. Delete the bare clone at `<repo>-new/`: `rm -rf <repo>-new`.
3. The remote on GitHub is untouched; nothing on GitHub needs reverting.
4. If §3.1 pre-flight was skipped and unpushed work was lost, recover from `<repo>_old/.git/reflog`.

### Symptom: `submodule status` shows different SHAs across worktrees
**Cause**: submodules are per-worktree — `git submodule update --init --recursive` must run inside each worktree, not just the default.
**Fix**: `for wt in master <change-id>; do (cd $wt && git submodule update --init --recursive); done`.

## Related

- [Runbook: onboard-new-project](onboard-new-project.md) — broader greenfield bootstrap; this runbook plugs in at step 1.5.
- [Runbook: windows-dev-environment](windows-dev-environment.md) — Windows-specific worktree removal pitfalls.
- [Concept: git-worktree-bare-layout](../concepts/git-worktree-bare-layout.md) — the layout contract this runbook operationalises.
- [Concept: dispatcher-chain](../concepts/dispatcher-chain.md) — how the registry resolves cwd-in-worktree paths.
- [Concept: release-management](../concepts/release-management.md) — `slice/<change-id>` branch convention.
- [Concept: runbook-bmad-openspec](../concepts/runbook-bmad-openspec.md) — branch + PR + merge contract.
