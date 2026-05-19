# runbook: git-worktree-bare-setup.md — bare-repo + per-branch worktree layout

> **Audience**: tú o un teammate que va a (a) arrancar un consumer project nuevo con el layout canónico, (b) migrar un consumer existente del layout legacy single-tree, o (c) gestionar worktrees diarios (añadir/borrar por OpenSpec change).
> **Status**: v1.0.0 (2026-05-01 — introduced alongside [docs/concepts/git-worktree-bare-layout.md](../docs/concepts/git-worktree-bare-layout.md) in ai-playbook v0.9.0-rc3).
> **Prereqs**: `git ≥ 2.36` (for `git worktree repair`), `gh` autenticado, `python 3.11+`, acceso de escritura al repo + permisos para renombrar el dir local.
> **Tiempo estimado**: greenfield 5min · migrate 10–15min (Windows: +5min por la session restart) · daily 30s por worktree.

## Qué hace este runbook

Tres escenarios bajo el mismo contrato de layout (per [docs/concepts/git-worktree-bare-layout.md](../docs/concepts/git-worktree-bare-layout.md)):

```
<project-root>/
├── .bare/                 # bare repo (single git database)
├── .git                   # pointer file: "gitdir: ./.bare"
├── master/                # default-branch worktree
└── <change-id>/           # one worktree per OpenSpec change in flight
```

Pick the section for your situation:

- §1 **Greenfield** — you're creating a new consumer repo from scratch.
- §2 **Onboard existing repo** — first time cloning a repo that's already on GitHub.
- §3 **Migrate legacy single-tree** — converting an existing local clone to bare layout.
- §4 **Daily flow** — add a worktree for a new OpenSpec change; remove a finished one.

## 1. Greenfield: arrancar un consumer nuevo con bare layout

```bash
# Pick the parent directory name = repo name (lowercase, no suffix).
PROJECT=my-new-project

mkdir -p /c/Projects/$PROJECT && cd /c/Projects/$PROJECT

# 1.1 Create the bare repo (no working tree inside it).
git clone --bare https://github.com/Wizarck/$PROJECT.git .bare

# 1.2 Reconfigure remote.origin.fetch so refs land at refs/remotes/origin/*.
#     The default `--bare` clone puts remote heads in refs/heads/, which conflicts
#     with how `git worktree add` creates local tracking branches.
git -C .bare config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
git -C .bare fetch origin --prune

# 1.3 Drop the pointer file so commands run from the parent dir find the repo.
echo "gitdir: ./.bare" > .git

# 1.4 Add the default-branch worktree (auto-detect default).
DEFAULT=$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
git worktree add $DEFAULT $DEFAULT

# 1.5 (consumer projects only) Run bootstrap inside the default worktree.
cd $DEFAULT
python /c/Projects/ai-playbook/scripts/bootstrap.py $PROJECT \
    --owner <your-email> \
    --path . \
    --register-in /c/Projects/ai-playbook \
    --visibility <public|private> \
    --default-branch $DEFAULT
```

Verify:

```bash
cd /c/Projects/$PROJECT
git worktree list
# Expected:
# /c/Projects/<PROJECT>/.bare      (bare)
# /c/Projects/<PROJECT>/master     <sha>  [master]
```

## 2. Onboard existing repo (first clone, GitHub already has it)

Same as §1 with a real remote URL. The bootstrap step is skipped if the repo already has `.ai-playbook/` and `AGENTS.md`.

## 3. Migrate a legacy single-tree clone

The repo is already cloned at `/c/Projects/<repo>/` with the working tree directly inside (legacy layout). We rebuild the bare layout as a sibling, swap, then `git worktree repair` the absolute paths.

### 3.1 Pre-flight

```bash
cd /c/Projects/<repo>

# Confirm everything is committed + pushed.
git status --short                                    # must be empty (or only gitignored noise)
git log --oneline @{upstream}..HEAD                   # must be empty (no unpushed commits)

# Note any other worktrees attached to this repo:
git worktree list
```

If you have unpushed commits, `git push` first. If you have uncommitted work, commit or stash. If you have additional worktrees (e.g. `<repo>-feature-x/`), **push their branches** then plan to recreate them in §3.5.

### 3.2 Backup any untracked working files you want to keep

Untracked files (research scratch, local notes, `.env`, etc.) are not in git and won't survive the swap. Copy them aside:

```bash
mkdir -p /c/Projects/_migration-backup-<repo>
cp -R /c/Projects/<repo>/_bmad-output/research /c/Projects/_migration-backup-<repo>/ 2>/dev/null || true
cp /c/Projects/<repo>/.env /c/Projects/_migration-backup-<repo>/ 2>/dev/null || true
# … any other untracked files you care about
```

### 3.3 Build the new layout as a sibling

```bash
mkdir -p /c/Projects/<repo>-new && cd /c/Projects/<repo>-new

# Bare clone from the SAME remote (NOT from the local repo — we want clean refs).
git clone --bare $(git -C /c/Projects/<repo> remote get-url origin) .bare

git -C .bare config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
git -C .bare fetch origin --prune

echo "gitdir: ./.bare" > .git

DEFAULT=$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
git worktree add $DEFAULT $DEFAULT

# Recreate every additional worktree you noted in §3.1:
git worktree add <change-id> slice/<change-id>

# Init submodules in EACH worktree (submodules are per-working-tree).
for wt in $DEFAULT <change-id>; do
    (cd $wt && git submodule update --init --recursive)
done
```

### 3.4 Restore untracked files into the new default worktree

```bash
cp -R /c/Projects/_migration-backup-<repo>/research /c/Projects/<repo>-new/$DEFAULT/_bmad-output/ 2>/dev/null || true
cp /c/Projects/_migration-backup-<repo>/.env /c/Projects/<repo>-new/$DEFAULT/ 2>/dev/null || true
```

### 3.5 Atomic swap

**Linux/macOS** — straightforward:

```bash
cd /tmp                                              # leave the project dirs
mv /c/Projects/<repo> /c/Projects/_<repo>-OLD-trash
mv /c/Projects/<repo>-new /c/Projects/<repo>
```

**Windows** — the cwd of any open Claude Code / VS Code session is held by the OS, so renaming the locked dir fails with `Device or resource busy`. Workaround:

1. Close every Claude Code session and editor with cwd inside `/c/Projects/<repo>/`.
2. Open a fresh terminal **outside** any of those tools (Windows Terminal, PowerShell, cmd).
3. Run the rename:
   ```powershell
   Move-Item -Path C:/Projects/<repo> -Destination C:/Projects/<repo>_old
   Move-Item -Path C:/Projects/<repo>-new -Destination C:/Projects/<repo>
   ```
4. Reopen your editor / Claude Code at `C:/Projects/<repo>/master/` (or whichever worktree you want as the new cwd — **not the parent dir**, since that has no source files).

### 3.6 Repair worktree absolute paths

After the rename, the worktree metadata files inside `.bare/worktrees/*/gitdir` and the per-worktree `.git` pointer files still reference the old absolute path (`<repo>-new/...`). Fix them:

```bash
cd /c/Projects/<repo>/.bare
git worktree repair /c/Projects/<repo>/master /c/Projects/<repo>/<change-id>
git worktree list                # all paths should now show /c/Projects/<repo>/...
```

If `git worktree repair` still complains, manually verify both files:

- `<repo>/<wt>/.git` should contain `gitdir: <repo>/.bare/worktrees/<wt>` (absolute path).
- `<repo>/.bare/worktrees/<wt>/gitdir` should contain `<repo>/<wt>/.git` (absolute path).

### 3.7 Verify

```bash
git -C /c/Projects/<repo>/master status --short      # clean (or only restored untracked)
git -C /c/Projects/<repo>/master submodule status    # all submodules at expected SHAs
git -C /c/Projects/<repo>/master log --oneline -3    # last commits match origin/$DEFAULT
git -C /c/Projects/<repo>/<change-id> branch --show-current   # slice/<change-id>
```

### 3.8 Clean up the trash dirs

Once you've verified everything (run a build, run a test, open the editor in `master/`), delete the legacy directories:

```powershell
Remove-Item -Recurse -Force C:/Projects/<repo>_old
Remove-Item -Recurse -Force C:/Projects/_migration-backup-<repo>
```

The registry at `~/.ai-playbook/projects.yaml` does **not** need editing — `path: C:/Projects/<repo>` resolves cwd-in-`<repo>/master/` via the parent-of-cwd rule (per [docs/concepts/dispatcher-chain.md](../docs/concepts/dispatcher-chain.md) §Registry integration).

## 4. Daily flow: add and remove worktrees

### 4.1 Add a worktree for a new OpenSpec change

The helper script does this in one call:

```bash
cd /c/Projects/<repo>/.bare
python /c/Projects/ai-playbook/scripts/wt_add.py <change-id>
```

This creates `<repo>/<change-id>/` as a worktree on a fresh `slice/<change-id>` branch, branched from the project default. It also runs `git submodule update --init --recursive` inside the new worktree.

By default the script refuses to create a worktree whose `<change-id>` does not match an existing `openspec/changes/<id>/` folder (for parity with `/opsx:propose`). Pass `--no-slice-check` for ad-hoc branches that bypass the slicing contract.

Manual equivalent (if the script is unavailable):

```bash
cd /c/Projects/<repo>
git worktree add <change-id> -b slice/<change-id> origin/$(git -C .bare symbolic-ref --short refs/remotes/origin/HEAD | sed 's|origin/||')
(cd <change-id> && git submodule update --init --recursive)
```

### 4.2 Remove a finished worktree

After the slice's PR is squash-merged to the default branch:

```bash
cd /c/Projects/<repo>
git worktree remove --force <change-id>
rm -rf <change-id>                                   # if force-remove leaves submodule dirs
git branch -D slice/<change-id>                      # cleanup local branch (remote branch already deleted by GH)
```

`--force` is needed because the worktree contains submodule directories git's bookkeeping doesn't track. The `rm -rf` cleanup is safe — the worktree's contents were either committed (already in `.bare/`) or untracked (not in the project anyway).

## Rollback

If §3 fails partway and the new layout is unusable:

1. The original `<repo>/` is preserved at `<repo>_old/` (or `_<repo>-OLD-trash/`) — restore by reversing the §3.5 rename.
2. The bare clone at `<repo>-new/` (or wherever it ended up) can be deleted: `rm -rf <repo>-new`.
3. The remote on GitHub is untouched throughout; nothing on GitHub needs reverting.
4. Any unpushed commits would have been required in §3.1 pre-flight; if you skipped that and lost work, recover from `<repo>_old/.git/reflog`.

## Cross-references

- [docs/concepts/git-worktree-bare-layout.md](../docs/concepts/git-worktree-bare-layout.md) — the layout contract this runbook operationalises.
- [scripts/wt_add.py](../scripts/wt_add.py) — daily-flow helper.
- [docs/concepts/release-management.md](../docs/concepts/release-management.md) §3.1 — `slice/<change-id>` branch convention.
- [docs/concepts/runbook-bmad-openspec.md](../docs/concepts/runbook-bmad-openspec.md) §3.6 — branch + PR + merge contract.
- [docs/runbooks/onboard-new-project.md](onboard-new-project.md) — the broader greenfield bootstrap flow this runbook plugs into at step §1.5.
