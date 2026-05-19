---
schema: runbook/v1
slug: windows-dev-environment
description: Resolve non-obvious Windows + WSL2 dev-loop gotchas (Windows Store Python, Jest worker crashes on Node 24+, worktree removal under file-handle locks).
audience: developer
estimated_time: 5-15 min per gotcha
last_validated: "2026-05-19"
---

# Resolve Windows + WSL2 dev-loop gotchas

## Outcome

The Windows-specific failure pattern has been identified and the canonical fix applied. The local dev loop runs the same as on Linux / macOS: `python -m venv` works, `pip install` completes in seconds, `npm test` does not crash workers, and `git worktree remove` deletes the directory cleanly.

## When to use this

The dev loop is failing in a way that doesn't reproduce on the Linux CI runner. Each section below maps one symptom to one fix:

- **§1**: `python -m venv` says `No module named pip`.
- **§2**: `pip install --user` hangs silently for minutes.
- **§3**: `npm test` Jest workers crash with `spawn UNKNOWN errno -4094`.
- **§4**: `git worktree remove --force` errors `Device or resource busy` or leaves the directory behind.

If on Linux or macOS, this runbook does not apply.

## Prerequisites

- Windows 10/11 with PowerShell 7+ available: `pwsh --version`.
- Python 3.11+ installed via python.org (preferred) or the Microsoft Store.
- Node 24+ installed if §3 applies: `node --version`.
- Git 2.36+ for §4: `git --version`.

## Steps

### 1. Windows Store Python venv lacks pip

**Symptom**:
```
$ python -m venv .venv
$ .venv/Scripts/python -m pip install -e .
> /Scripts/python: No module named pip
```

**Cause**: the Windows Store distribution of Python ships a stripped-down `venv` module that omits `ensurepip` to comply with the Microsoft Store sandbox model. Created venvs lack pip until you bootstrap it.

**Fix**:
```bash
python -m venv .venv --upgrade-deps
# OR
python -m venv .venv && .venv/Scripts/python -m ensurepip --upgrade
```

`--upgrade-deps` (Python 3.9+) bootstraps both pip and setuptools into the new venv on creation. The flag is a no-op on the python.org installer (which already includes pip), so it is safe to apply unconditionally.

**Permanent escape**: install Python from <https://www.python.org/downloads/> instead of the Microsoft Store. The python.org installer does not suffer this issue and avoids the path-stability problems caused by the MS Store installation path including a hash that changes after Store updates.

### 2. `pip install --user` silent + glacially slow on Windows Store Python

**Symptom**:
```
$ pip install --user respx
# (10 minutes of zero stdout)
# (eventually completes silently, or another invocation overtakes it)
```

**Cause**: Windows Store Python's `--user` install path lives under `%APPDATA%\Python\PythonXY\site-packages\`. The Microsoft Store sandbox's first-write setup (directory creation + permission setup + hash-stable-symlink dance) takes minutes on the first install. Subsequent `--user` installs are fast, but the first one stalls visibly.

**Fix**: do not use `--user` with Windows Store Python. Use a venv:
```bash
python -m venv .venv --upgrade-deps
.venv/Scripts/python -m pip install respx
```

A venv install completes in seconds because it writes to a project-local directory with no Store sandbox overhead.

### 3. Jest workers crash with `spawn UNKNOWN errno -4094` on Windows + Node 24+

**Symptom**:
```
$ npm test
PASS apps/api/src/cost/cost.service.spec.ts
FAIL apps/api/src/labels/labels.service.spec.ts
  ● Test suite failed to run
    spawn UNKNOWN errno -4094
```
The error is sporadic — re-running individual files passes, but the parallel worker pool produces non-deterministic crashes.

**Cause**: Node 24+ tightened child-process spawn semantics on Windows, particularly around inherited handle counts when a parent has many open file handles. Jest's worker model spawns multiple Node child processes; once the parent exceeds a per-process file-handle threshold, new spawns fail with `errno -4094` (`UV_UNKNOWN`).

**Fix**:
```bash
npm test -- --runInBand
# OR in CI / test scripts
"test": "jest --runInBand"
```

`--runInBand` runs every test file sequentially in the parent process — no worker spawn. Slower (loses parallelism) but deterministic. The performance hit is acceptable for typical project test suites (<10 minutes serialised vs ~3 minutes parallel).

**Permanent escape**: Linux CI (the canonical target) does not reproduce this. Do not fix at the CI level — fix at the Windows-developer level by adding `--runInBand` to a local-only test script (`npm run test:windows`) or accept the serialised time hit.

### 4. `git worktree remove --force` fails on Windows

**Symptom**:
```
$ git worktree remove --force ".claude/worktrees/agent-abc123"
error: failed to delete '.claude/worktrees/agent-abc123': Device or resource busy
$ git worktree list
# branch is gone from the worktree list
$ ls .claude/worktrees/
agent-abc123  # directory still present
```

**Cause**: Windows file-system semantics — deletion fails if any process holds an open handle to a file inside the directory. Common culprits:

- VS Code / IDE language servers indexing the worktree.
- File watchers from running dev servers (`vite`, `tsc --watch`, `pnpm dev`).
- Antivirus scanning during the recursive delete walk.

Git removes the worktree registration (no longer in `git worktree list`) but leaves the directory behind.

**Fix** (in order of preference):

1. **Stop the holder**: shut down the IDE, kill the watcher process, or wait for AV to finish, then re-run the remove.

2. **Manual deletion via shell**:
   ```bash
   rm -rf ".claude/worktrees/agent-abc123" 2>/dev/null
   # or PowerShell
   powershell -Command "Remove-Item -Path '.claude/worktrees/agent-abc123' -Recurse -Force"
   ```
   If the handle is released between the failed `git worktree remove` and the manual `rm`, this succeeds. Otherwise it fails with the same error — return to option 1.

3. **Accept the empty directory**: if the worktree's branch is already removed from the worktree list, the leftover directory is harmless. Delete it manually after the session ends.

**Permanent escape**: use the bare-repo + per-branch worktree layout (per [Concept: git-worktree-bare-layout](../concepts/git-worktree-bare-layout.md)), which keeps each worktree as a peer subdirectory. Worktrees not open in any process delete cleanly; the IDE / watcher pattern only blocks worktrees the user is actively editing.

## Verification

For each gotcha:

- §1: `.venv/Scripts/python -m pip --version` reports a pip version.
- §2: `pip install <package>` completes within the expected duration (<30 s for small packages).
- §3: `npm test -- --runInBand` exits 0 with all suites passing.
- §4: `ls .claude/worktrees/` no longer lists the removed worktree directory.

## Troubleshooting

### Symptom: §1 fix applied but pip is still missing in a new venv
**Cause**: the python.org installer was added to PATH after the Store installer, but the Store one still resolves first.
**Fix**: `where python` to see all matches; remove the Store entry from PATH, OR call the python.org binary by absolute path (`C:\Python311\python.exe -m venv .venv`).

### Symptom: §3 fix applied but the test suite is too slow under `--runInBand`
**Cause**: serialised execution exceeds the acceptable wall-time (>10 min).
**Fix**: shard the test suite at the script level — split into `npm run test:unit` and `npm run test:integration`, run them sequentially in CI but in parallel on Linux. Keep `--runInBand` only on Windows by using `npm-run-all` and a platform-conditional script.

### Symptom: §4 manual `rm -rf` works but leaves a `.git` file pointer behind
**Cause**: the worktree's git registration was deleted but the directory deletion was partial.
**Fix**: re-run `git worktree prune` from the parent repo; this cleans dangling registrations and the residual pointer file.

## Related

- [Runbook: git-worktree-bare-setup](git-worktree-bare-setup.md) — bare-repo + per-branch worktree layout that mitigates §4.
- [Runbook: onboard-new-project](onboard-new-project.md) — first-day setup; this runbook supplements with Windows-specific gotchas.
- [Concept: git-worktree-bare-layout](../concepts/git-worktree-bare-layout.md) — canonical layout.
- [Concept: contributing](../concepts/contributing.md) — `--runInBand` workaround for Windows test scripts.
