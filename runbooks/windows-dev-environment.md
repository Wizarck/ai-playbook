# runbooks/windows-dev-environment.md

> **Status**: v1.0.0. New in ai-playbook v0.10.0. Surfaces non-obvious
> Windows-specific dev-loop quirks that have surprised contributors across
> consumer projects. The list is short (4 entries) but each one cost real
> time to discover. CI runs on Linux; these are Windows-developer pain
> only.

## Scope

This runbook covers Windows + WSL2 dev-loop gotchas surfaced during
2026-Q2 across consumer-c-legacy (Node 24+ Jest, Python tools), consumer-e
(git worktrees, Python venv), and consumer-d (poetry, MS Store Python).

If you're on Linux or macOS, ignore this file.

---

## 1. Windows Store Python: `python -m venv` does NOT include pip

### Symptom

```bash
$ python -m venv .venv
$ .venv/Scripts/python -m pip install -e .
> /Scripts/python: No module named pip
```

### Root cause

The Windows Store distribution of Python ships a stripped-down
`venv` module that omits `ensurepip` to comply with the Microsoft
Store sandbox model. Created venvs lack pip until you bootstrap it.

### Fix

```bash
python -m venv .venv --upgrade-deps
# OR
python -m venv .venv && .venv/Scripts/python -m ensurepip --upgrade
```

`--upgrade-deps` (Python 3.9+) bootstraps both pip and setuptools into
the new venv on creation. This is the simplest fix and works the same
on the python.org installer (which DOES include pip — the flag is a
no-op there but harmless).

### Permanent escape

Install Python from <https://www.python.org/downloads/> instead of the
Microsoft Store. The python.org installer doesn't suffer this issue
and avoids related path-stability problems (the MS Store installation
path includes a hash that changes after Store updates).

---

## 2. `pip install --user` on Windows Store Python: silent + glacially slow

### Symptom

```bash
$ pip install --user respx
# (10 minutes of zero stdout)
# (eventually completes silently, or another invocation overtakes it)
```

### Root cause

Windows Store Python's `--user` install path lives under
`%APPDATA%\Python\PythonXY\site-packages\`. The directory creation
+ permission setup + hash-stable-symlink dance the Store sandbox
forces on first write takes minutes on first install. Subsequent
`--user` installs are fast, but the *first* one stalls visibly.

### Fix

Don't use `--user` with Windows Store Python. Use a venv:

```bash
python -m venv .venv --upgrade-deps
.venv/Scripts/python -m pip install respx
```

A venv install completes in seconds because it writes to a project-
local directory (no Store sandbox overhead).

---

## 3. Jest workers crash with `spawn UNKNOWN errno -4094` on Windows + Node 24+

### Symptom

```bash
$ npm test
PASS apps/api/src/cost/cost.service.spec.ts
FAIL apps/api/src/labels/labels.service.spec.ts
  ● Test suite failed to run
    spawn UNKNOWN errno -4094
```

The error is sporadic — re-running individual files passes, but the
parallel worker pool produces non-deterministic crashes.

### Root cause

Node 24+ tightened child-process spawn semantics on Windows
(particularly around inherited handle counts when a parent has many
open file handles). Jest's worker model spawns multiple Node child
processes; once the parent exceeds a per-process file-handle threshold,
new spawns fail with `errno -4094` (`UV_UNKNOWN`).

### Fix

```bash
npm test -- --runInBand
# OR in CI / test scripts
"test": "jest --runInBand"
```

`--runInBand` runs every test file sequentially in the parent process,
no worker spawn. Slower (loses parallelism) but deterministic. The
performance hit is acceptable for the typical project test suite (<10
minutes serialised vs ~3 minutes parallel).

### Permanent escape

Linux CI (the canonical target) doesn't reproduce this. Don't fix at
the CI level — fix at the Windows-developer level by adding
`--runInBand` to the local-only test script (e.g. `npm run
test:windows`) or accept the serialised time hit.

---

## 4. `git worktree remove --force` fails "Device or resource busy" / "Directory not empty" on Windows

### Symptom

```bash
$ git worktree remove --force ".claude/worktrees/agent-abc123"
error: failed to delete '.claude/worktrees/agent-abc123': Device or resource busy
$ git worktree list
# branch is gone from the worktree list
$ ls .claude/worktrees/
agent-abc123  # directory still present
```

### Root cause

Windows file-system semantics: deletion fails if any process holds an
open handle to a file inside the directory. Common culprits:

- **VS Code / IDE language servers** indexing the worktree.
- **File watchers** from running dev servers (`vite`, `tsc --watch`,
  `pnpm dev`).
- **Antivirus** scanning during the recursive delete walk.

Git worktree removes the *registration* (the worktree no longer
appears in `git worktree list`) but leaves the directory behind.

### Fix

Three options, in order of preference:

**1. Stop the holder**: shut down the IDE / kill the watcher process /
wait for AV scan to finish, then re-run the remove.

**2. Manual deletion via shell**:

```bash
rm -rf ".claude/worktrees/agent-abc123" 2>/dev/null
# or PowerShell
powershell -Command "Remove-Item -Path '.claude/worktrees/agent-abc123' -Recurse -Force"
```

If the handle is released between the failed `git worktree remove`
and the manual `rm`, this succeeds. Otherwise it'll fail with the
same error — go back to option 1.

**3. Accept the empty directory**: if the worktree's branch is
already deleted from the worktree list, the leftover directory is
harmless. Delete it manually after the session ends (when the IDE /
watcher / AV holder has exited).

### Permanent escape

Use the bare-repo + per-branch-worktree layout (per
`specs/git-worktree-bare-layout.md`) which keeps each worktree as a
peer subdirectory. Worktrees that aren't open in any process delete
cleanly; the IDE / watcher pattern only blocks worktrees the user
is actively editing in.

---

## Cross-references

- [`specs/git-worktree-bare-layout.md`](../specs/git-worktree-bare-layout.md) — bare-repo + per-branch-worktree canonical layout
- [`runbooks/onboard-new-project.md`](onboard-new-project.md) — first-day setup; this runbook supplements with Windows-specific gotchas
- [`docs/contributing.md`](../docs/contributing.md) §5 (test discipline) — `--runInBand` workaround for Windows test scripts
