# start-here.md

> **Status**: v1.0.0. A 60-second orientation so a new dev (or future Arturo on a fresh PC) knows the next move without having to read the full spec tree.

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

Full contract: [../docs/concepts/dispatcher-chain.md](../docs/concepts/dispatcher-chain.md). Registry format: [../docs/concepts/projects-registry.md](../docs/concepts/projects-registry.md).

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

If any of these fail, the error carries a `FIX:` line per [../docs/rules/error-message-standard.rule.md](../docs/rules/error-message-standard.rule.md). If you still need to proceed, use `--force-with-reason="..."` per [../docs/rules/break-glass.rule.md](../docs/rules/break-glass.rule.md).

## Where to go next

| Your situation | Read this first |
|---|---|
| **I want to make a change in this (or any) playbook-consuming project** | **[development-flow.md](development-flow.md)** — canonical end-to-end flow (LLM-agnostic) |
| I want the full walkthrough | [quickstart.md](quickstart.md) (25–40 min) |
| I'm contributing to a spec in this repo | [../AGENTS.md](../AGENTS.md) + [contributing.md](contributing.md) |
| I'm onboarding a new consumer project | [bootstrap-new-project.md](bootstrap-new-project.md) + [quickstart.md](quickstart.md) |
| I broke something / hit a confusing error | [../docs/rules/error-message-standard.rule.md](../docs/rules/error-message-standard.rule.md), then [../FEEDBACK.md](../FEEDBACK.md) |
| I want to run a retro | [../docs/concepts/retrospective-cadence.md](../docs/concepts/retrospective-cadence.md) + [../templates/retro/](../templates/retro/) |
| I'm wiring tracing / SessionStart hook | [session-start-hook.md](session-start-hook.md) |
| I hit a gate I think is wrong | [../docs/rules/break-glass.rule.md](../docs/rules/break-glass.rule.md) (NOT `git commit --no-verify`) |
| I want to know why the playbook is shaped this way | [why-these-choices.md](why-these-choices.md) |

## Status snapshot

- **Version**: `v0.2.0` tagged; downstream consumer repos pin to it.
- **All core specs v1.0.0**. A small number are intentionally deferred-by-design and say so in their header (e.g. [incident-response.md](../docs/concepts/incident-response.md) activates when a paying client lands; [model-migration.md](model-migration.md) activates at the first pinned-model retirement).
- **What "dogfooding" means here**: the pre-commit config in this repo runs the same validators it ships to consumers.
