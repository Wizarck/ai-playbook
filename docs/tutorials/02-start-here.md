---
schema: tutorial/v1
slug: start-here
title: Start here — 60-second orientation
description: A one-minute orientation for anyone landing in the ai-playbook tree cold. Learn what the repo is, the three-level dispatcher chain, and the five commands you most often need.
estimated_time: "1 min"
prerequisite_concepts: []
audience: new-contributor
order: 2
---

# Start here — 60-second orientation

> **What you'll learn**: What the playbook is in one paragraph, how its three-level dispatcher chain composes universal norms with per-project specifics, and the five commands you will type most often. If you have 15 minutes instead of 1, go straight to [01-architecture-tour.md](01-architecture-tour.md) — it covers the same ground with hands-on commands.
> **Estimated time**: 1 min
> **Prerequisites**: none — this is the shortest doc in the repo

---

## 1. What this repo is (≤15 s)

`ai-playbook` is the universal norms + tooling repo consumed as a git submodule by every Wizarck project. It is **LLM-agnostic** — Claude Code, Gemini CLI, Cursor, and Antigravity all read the same files — and it **dogfoods** its own schemas, hooks, and validators. Most files here are thin contracts; implementation lives in the consumer projects that inherit.

If you came here to make a change, jump to step 3.

---

## 2. The three-level dispatcher chain (≤25 s)

```
┌────────────────────────────────────────────────────────────────┐
│  Level 1 — Universal                                           │
│  ai-playbook/  (this repo; docs/, scripts/, schemas/)          │
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
│  e.g. eligia-core/ELIGIA.md                                    │
│  Loaded conditionally via ~/.ai-playbook/projects.yaml.        │
└────────────────────────────────────────────────────────────────┘
```

Full contract: [dispatcher-chain.md](../concepts/dispatcher-chain.md). Registry format: [projects-registry.md](../concepts/projects-registry.md).

---

## 3. The five commands you will type most often (≤20 s)

Assume you are inside a consumer repo that already has the playbook installed as a submodule. If you are not, go to [03-quickstart.md](03-quickstart.md).

```bash
# 1. Health check — names every missing dep with a FIX line
python .ai-playbook/scripts/doctor.py

# 2. Validate your project's AGENTS.md frontmatter
python .ai-playbook/scripts/schema_validate.py AGENTS.md

# 3. Re-register projects after moving a repo
python .ai-playbook/scripts/discover_projects.py

# 4. Confirm the playbook's pairing invariant holds
python .ai-playbook/scripts/validate_pairing.py

# 5. Confirm docs/ is English-clean
python .ai-playbook/scripts/check_doc_language.py docs/
```

Each of these prints either `OK` / `✅` or an error line with a `FIX:` suggestion per [error-message-standard.rule.md](../rules/error-message-standard.rule.md). If something blocks you and you genuinely need to proceed, the escape hatch is [break-glass.rule.md](../rules/break-glass.rule.md) — never `git commit --no-verify`.

---

## What's next

| Your situation | Read this |
|---|---|
| I want hands-on contact with the repo | [01-architecture-tour.md](01-architecture-tour.md) — 15 min |
| I want the full walkthrough on a fresh consumer project | [03-quickstart.md](03-quickstart.md) — 25–40 min |
| I'd rather a script does the bootstrap for me | [04-bootstrap-new-project.md](04-bootstrap-new-project.md) — 10 min |
| Something broke on my OS | [05-quickstart-lessons.md](05-quickstart-lessons.md) — 10 min |
| I want the 4-week onboarding curriculum | [06-curriculum.md](06-curriculum.md) |
| I want the rationale behind the architecture | [07-why-these-choices.md](07-why-these-choices.md) — 15 min |
