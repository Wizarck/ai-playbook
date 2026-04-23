# quickstart-lessons.md

> **Status**: v1.0.0 skeleton. Populated in **T14c**. The per-OS friction rows themselves are filled during **T15** cross-OS dry-runs. Empty sections below are placeholders, not omissions — each run of the quickstart appends to the relevant OS section.

---

## Intent

[quickstart.md](quickstart.md) tells you what to do. This file records what actually went wrong when a real dev tried it, grouped by OS, with workarounds and realistic timing deltas against the Windows baseline. It is **append-only evidence**, not a polished tutorial.

The Windows timings in `quickstart.md`'s time-budget summary are the baseline (Arturo's primary environment). Other OS sections below record deltas rather than absolute times.

---

## Windows (baseline)

> Python 3.11 via winget, git for Windows, PowerShell 7 or Git Bash, pre-commit via pipx. This is the reference environment.

### Friction points discovered

- _Empty — populated during T15 dry-run._

### Workarounds

- _Empty — populated during T15 dry-run._

### Timing notes

Baseline from [quickstart.md](quickstart.md) time-budget summary. Deviations logged here if observed.

---

## macOS

> Apple silicon or Intel, Homebrew-managed Python, zsh default shell.

### Friction points discovered

- _Empty — populated during T15 dry-run._

### Workarounds

- _Empty — populated during T15 dry-run._

### Time deltas vs Windows baseline

- _Empty — populated during T15 dry-run._

---

## Linux (Ubuntu / Debian)

> Ubuntu 22.04+ or Debian 12+ assumed. `apt` for system packages, pyenv or distro Python.

### Friction points discovered

- _Empty — populated during T15 dry-run._

### Workarounds

- _Empty — populated during T15 dry-run._

### Time deltas vs Windows baseline

- _Empty — populated during T15 dry-run._

---

## WSL2 (Ubuntu on Windows)

> WSL2 Ubuntu 22.04+, project cloned inside the Linux filesystem (`~/projects/...`), NOT on `/mnt/c/`.

### Friction points discovered

- _Empty — populated during T15 dry-run._

### Workarounds

- _Empty — populated during T15 dry-run._

### Time deltas vs Windows baseline

- _Empty — populated during T15 dry-run._

---

## Reporting

If you hit a friction not listed above:

1. **Primary path** — append a bullet under the relevant OS section AND open a PR. Use the shape:
   ```
   - YYYY-MM-DD — <one-sentence friction> — FIX: <one-sentence workaround>
   ```
2. **Lower-friction alternative** — drop a line in [../FEEDBACK.md](../FEEDBACK.md) with the same shape minus the FIX; the weekly retro (see [../specs/retrospective-cadence.md](../specs/retrospective-cadence.md)) will promote recurring themes to this file.
3. **Systemic signal** — if the same friction appears across ≥2 OSes, promote to an RFC under `rfcs/` and link from the bullet; this is evidence the quickstart itself needs a fix, not just a per-OS note.

The goal is honest: new devs should know what's smooth and what's rough before they start, not after hour three.
