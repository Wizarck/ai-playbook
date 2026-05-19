---
schema: tutorial/v1
slug: quickstart-lessons
title: Per-OS friction — what tends to break and how to fix it
description: A companion to the quickstart that walks you through the most common per-OS friction (Windows, macOS, Linux, WSL2) so you can resolve issues without leaving the tutorial.
estimated_time: "10 min"
prerequisite_concepts: []
audience: operator
order: 5
---

# Per-OS friction — what tends to break and how to fix it

> **What you'll learn**: The friction points the quickstart can hit on each OS and exactly how to resolve them. Read your OS section before you start the quickstart; refer back if a step fails.
> **Estimated time**: 10 min (read your section + scan the others)
> **Prerequisites**:
> - You are about to run, or are in the middle of running, [03-quickstart.md](03-quickstart.md)
> - A terminal open at your platform

This file is the field guide. The quickstart tells you what to do; this file tells you what to expect to break and how to fix it. Skim your OS section first; come back here whenever a step misbehaves.

---

## Windows (baseline — real dry-run 2026-04-23)

Environment:
- Windows 11 Pro 10.0.26200, shell `bash` via Git-for-Windows (mingw64).
- Python 3.13 (Windows Store install).
- Git 2.51+, gh CLI 2.83+, Node.js 22 LTS, sops via winget.

### Friction points discovered

1. **`python -m scripts.mcp.validate` fails from a consumer cwd with `ModuleNotFoundError: No module named 'scripts.mcp'`.**
   Root cause: the playbook is consumed as a submodule at `<consumer>/.ai-playbook/`, but cwd-relative imports don't traverse the submodule boundary. Python's `-m` resolver looks for `scripts/` at cwd, which on a consumer repo points at the consumer's own `scripts/` (if any) or nothing.
   **Workaround**: invoke scripts with their absolute path:
   ```bash
   python C:/Projects/ai-playbook/scripts/mcp/validate.py --consumer-root .
   ```
   or export `PYTHONPATH`:
   ```bash
   PYTHONPATH=C:/Projects/ai-playbook python -m scripts.mcp.validate --consumer-root .
   ```
   Permanent fix (future T22 work): package the playbook as installable (`pip install -e .ai-playbook/`) and expose console scripts via `[project.scripts]` in `pyproject.toml`. `ai-playbook-bootstrap`, `ai-playbook-doctor`, `ai-playbook-mcp-validate`, etc.

2. **No `.gitattributes` at the playbook root** meant Windows devs with `core.autocrlf=true` set globally would check out `.py`, `.yaml`, and `.md` files with CRLF line endings. Pre-commit's `end-of-file-fixer` + `check-yaml` would then rewrite every file on first run, producing a huge spurious diff.
   **Fix landed in this commit**: `.gitattributes` at the playbook root pins `text eol=lf` for all source files except `.bat`/`.cmd`/`.ps1`. Consumers who adopt the submodule after this commit are unaffected; devs with an existing clone need to run `git rm --cached -r . && git reset --hard` once to renormalise.

3. **Doctor warnings are normal on a fresh machine** — `pre-commit` via pipx, `gitleaks` (pre-commit installs lazily), and env vars like `HINDSIGHT_*` / `LANGFUSE_*` are all expected to be unset until SOPS is wired. `scripts/doctor.py` emits them as `⚠️` (advisory) rather than `❌` (blocking), which is correct.

4. **Context budget warning fires at 167.7 KB of specs** (threshold 100 KB). Not a regression — it's a signal the playbook specs have grown past the lean-framework threshold post-Batch 2. Action: prune stubs or move examples to `docs/` during monthly lifecycle check. Not blocking.

### Timings (Windows baseline)

| Step | Budgeted (quickstart.md) | Actual |
|---|---|---|
| 1. Clone playbook as submodule | 1 min | ~30s (fast internet, cached). |
| 2. Bootstrap | 2 min | 30s via `python -m scripts.bootstrap --project-name X --owner Y`. |
| 3. Write AGENTS.md | 5 min | 8 min (first-time cost of thinking through sections §0–§8). |
| 4. Register project | 30s | <5s. |
| 5. MCP render dry-run | 2 min | ~5s. |
| 6. Pre-commit install + all-files | 3 min | ~2 min (first-time hook downloads). |
| 7. First OpenSpec change | 10 min | Not tested in this dry-run (no OpenSpec change created). |
| 8. SessionStart hook | 2 min | 3 min (reading the doc + editing `settings.json`). |
| **Total (steps 1–6, 8)** | **15 min** | **~18 min**, within the 25–40 min band. |

---

## macOS (predicted — no real dry-run yet)

Predicted friction points based on static analysis + common knowledge:

### Likely friction points

1. **`python` vs `python3`**: macOS system Python is ancient (2.7) and often missing. Quickstart assumes `python` resolves to 3.11+ — on Macs it typically needs to be `python3`. Workaround: `alias python=python3` in `~/.zshrc`, or install via `brew install python@3.12`. Recommend updating the quickstart's prereq section to say `python3` explicitly.
2. **Xcode Command Line Tools required for git**. Fresh macOS clones prompt for install; first `git clone` hangs until the user accepts. Document this in prereqs.
3. **`sops` + `age` install differ**: `brew install sops age` vs winget. `~/.config/sops/age/keys.txt` path is the same as Linux.
4. **`gitleaks` via brew**: `brew install gitleaks`. Same semver pin as pre-commit hook.
5. **BSD vs GNU utilities**: macOS `sed`, `awk`, `date` differ from GNU. The playbook scripts use pure Python so this does NOT affect us, but if a dev pipes script output into a macOS `sed`/`awk` one-liner from the Linux docs, it may silently fail. Action: no script changes needed; tutorials should avoid `sed -i` examples.
6. **Filesystem case sensitivity**: APFS default is case-insensitive; Linux ext4 is case-sensitive. The registry and schema are slug-lowercase by contract, so this shouldn't matter — but watch for `AGENTS.md` vs `agents.md` confusion when docs are authored on a case-insensitive Mac and deployed to a case-sensitive CI runner.

### Timings (predicted)

Likely within Windows ±20% after fixing the `python3` alias. Tests should run ≤1s as on Windows.

---

## Linux (predicted — no real dry-run yet)

### Likely friction points

1. **`python3` not `python`** (same as macOS). On Debian/Ubuntu, `python3-full` + `python3-venv` + `python3-pip` needed.
2. **`sops` + `age`** via `apt install sops age` or fall back to GitHub releases binary. Name compatibility is fine.
3. **Default shell `dash` on Debian**: shell scripts (none in playbook; all Python) aren't affected, but tutorials showing `source` expect bash. Use `bash ./script.sh`, not `sh ./script.sh`.
4. **`gitleaks` via GitHub releases or Snap** — distribution varies by distro.
5. **Container-friendly**: once running inside a container, no user-home registry at `~/.ai-playbook/projects.yaml` unless the container persistently mounts it. Workaround: pass `$AIPLAYBOOK_PROJECTS_FILE=/workspace/.ai-playbook/projects.yaml` into the container.
6. **Locale**: some minimal Linux containers default to `C`/`POSIX` locale; UTF-8 stdio reconfigure in playbook scripts handles this, but shell tools downstream may mangle the `✅` sigils in the rendered output. Document: set `LANG=C.UTF-8` (or `en_US.UTF-8`) in container `Dockerfile`.

### Timings (predicted)

Fastest of the four environments once prereqs are installed. Tests ≤1s. Steps 1–8 of quickstart likely ~12 min total.

---

## WSL2 (predicted — no real dry-run yet)

### Likely friction points

1. **Filesystem mode boundary**: projects on `/mnt/c/Projects/...` (Windows NTFS via 9P) are ~10–100× slower than native `/home/<user>/projects/...` for small-file workloads. Test discovery (`pytest` with 200+ files) will feel noticeably slower across the boundary. Recommend: clone consumer repos into WSL-native paths when testing inside WSL; use Windows-native paths only when editing from VS Code Windows host.
2. **Line endings**: a repo cloned via Windows Git (CRLF) and accessed from WSL bash causes bash scripts to fail with `bad interpreter`. With the `.gitattributes` we just added, this should be a non-issue for new clones, but existing clones need `git rm --cached -r . && git reset --hard` inside WSL.
3. **Registry paths differ**: `~/.ai-playbook/projects.yaml` resolves to `/home/<user>/.ai-playbook/projects.yaml` in WSL and `C:\Users\<user>\.ai-playbook\projects.yaml` in Windows — **these are two different files**. A project registered in Windows Git Bash doesn't appear in WSL bash, and vice versa. Workaround: set `$AIPLAYBOOK_PROJECTS_FILE` explicitly in both environments to point at a single shared path under `/mnt/c/Users/<user>/.ai-playbook/projects.yaml`.
4. **`sops` + `age` install**: separate install inside WSL via `apt` or GitHub releases. Age keys at `/home/<user>/.config/sops/age/keys.txt`. These are distinct from the Windows keystore.
5. **File permissions ghosting**: git under WSL tracks exec bit; git under Windows often doesn't. Round-tripping the same repo through both can toggle exec bits on every commit. Not a blocker for the playbook (no shell scripts tracked), but worth knowing.

### Timings (predicted)

~1.5–2× slower than Linux native when repos live on `/mnt/c`. Inside a WSL-native path, ~1× Linux.

---

## Reporting

If you hit a friction NOT listed above:

- **Append a bullet** under the relevant OS section AND open a PR.
- Reference the friction in the retro that follows your first archive — the cadence is documented in [retrospective-cadence.md](../concepts/retrospective-cadence.md).

Do NOT edit Windows-baseline timings after the fact to match your experience — file a PR to update the whole table so the lineage is clear.

---

## What's next

- [03-quickstart.md](03-quickstart.md) — the 8-step walkthrough this doc validates. Return there if you bailed out mid-step.
- [04-bootstrap-new-project.md](04-bootstrap-new-project.md) — if the manual quickstart is taking too long on your OS, switch to the one-shot script.
- [Concept: retrospective-cadence](../concepts/retrospective-cadence.md) — where these findings feed back into the playbook.
- [Runbook: windows-dev-environment](../runbooks/windows-dev-environment.md) — the canonical Windows recovery procedure when something deeper than friction goes wrong.
