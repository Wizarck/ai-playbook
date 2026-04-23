# start-here.md

> **Status**: v1.0.0. Supersedes T02-pre stub. Populated in **T14b**. A 60-second orientation so a new dev (or future Arturo on a fresh PC) knows the next move without having to read the full spec tree.

## What this repo is

`ai-playbook` is the universal norms + tooling repo consumed as a git submodule by every Wizarck project. It is **LLM-agnostic** (Claude Code, Gemini CLI, Cursor, Antigravity all read the same files) and it **dogfoods** its own schemas, hooks, and validators. Most files here are thin contracts; implementation lives in consumer projects that inherit.

## 3-level dispatcher chain

```
┌────────────────────────────────────────────────────────────────┐
│  Level 1 — Universal                                           │
│  ai-playbook/  (this repo; specs/, scripts/, templates/)       │
│  Consumed via git submodule at <consumer>/.ai-playbook/        │
└────────────────────────────────────────────────────────────────┘
                             │ inherits_from
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Level 2 — Project                                             │
│  <consumer>/AGENTS.md  (project dispatcher; thin)              │
│  Identity, active work, hard rules, capability map.            │
└────────────────────────────────────────────────────────────────┘
                             │ personal: true (Arturo only)
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Level 3 — Personal add-on (optional)                          │
│  e.g. consumer-d/consumer-d.md                                    │
│  Loaded conditionally via ~/.ai-playbook/projects.yaml.        │
└────────────────────────────────────────────────────────────────┘
```

Full contract: [../specs/dispatcher-chain.md](../specs/dispatcher-chain.md). Registry format: [../specs/projects-registry.md](../specs/projects-registry.md).

## First 5 commands you should run

Assumes you are inside a consumer repo (or this repo for self-hosted work).

```bash
# 1. Add the playbook as a submodule (skip if already present)
git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook
cd .ai-playbook && git checkout v0.1.0 && cd ..

# 2. Install pre-commit hooks (schema, secrets, verdict lint)
pipx install pre-commit && pre-commit install

# 3. Run the health check — reports missing deps with FIX lines
python .ai-playbook/scripts/doctor.py

# 4. Register this project into ~/.ai-playbook/projects.yaml
python -m scripts.discover_projects            # run from .ai-playbook/

# 5. Validate your project's AGENTS.md frontmatter
python .ai-playbook/scripts/schema_validate.py AGENTS.md
```

If any of these fail, the error carries a `FIX:` line per [../specs/error-message-standard.md](../specs/error-message-standard.md). If you still need to proceed, use `--force-with-reason="..."` per [../specs/break-glass.md](../specs/break-glass.md).

## Where to go next

| Your situation | Read this first |
|---|---|
| I want the full walkthrough | [quickstart.md](quickstart.md) (25–40 min) |
| I'm contributing to a spec in this repo | [../AGENTS.md](../AGENTS.md) + [contributing.md](contributing.md) |
| I'm onboarding a new consumer project | [bootstrap-new-project.md](bootstrap-new-project.md) + [quickstart.md](quickstart.md) |
| I broke something / hit a confusing error | [../specs/error-message-standard.md](../specs/error-message-standard.md), then [../FEEDBACK.md](../FEEDBACK.md) |
| I want to run a retro | [../specs/retrospective-cadence.md](../specs/retrospective-cadence.md) + [../templates/retro/](../templates/retro/) |
| I'm wiring tracing / SessionStart hook | [session-start-hook.md](session-start-hook.md) |
| I hit a gate I think is wrong | [../specs/break-glass.md](../specs/break-glass.md) (NOT `git commit --no-verify`) |
| I want to know why the playbook is shaped this way | [why-these-choices.md](why-these-choices.md) |

## Status snapshot

- **Version**: `v0.1.0` (scaffold committed; baseline branch for rollback).
- **Active track**: T14 EX package (start-here, quickstart, FEEDBACK, notification-policy, governance stub, retro templates, retrospective cadence).
- **Downstream**: T15 cross-OS dry-run → T17 live docs → T19 dashboard → T22 governance.
- **Most `specs/*.md` are v1.0.0** with a handful still at stub pending their dedicated track. Every file declares its status in the first header line.
- **What "dogfooding" means here**: the pre-commit config in this repo runs the same validators it ships to consumers.
