---
schema: tutorial/v1
slug: why-these-choices
title: Why these choices — the rationale tour
description: A guided tour through the five design decisions that shape ai-playbook — git submodule, LLM-agnosticism, MCP for tools, parallel observability, and the 3-level dispatcher. Each section walks the reader from problem to alternatives to chosen path.
estimated_time: "15 min"
prerequisite_concepts: [dispatcher-chain]
audience: developer
order: 7
---

# Why these choices — the rationale tour

> **What you'll learn**: The five design decisions that shape `ai-playbook` — distribution via git submodule, LLM-agnosticism, MCP for tool distribution, dual observability (OTel + Langfuse), and the 3-level dispatcher. For each decision you will see the problem it solves, the alternatives considered, and why the playbook went the way it did. By the end you will understand the load-bearing choices that explain most of the rest of the repo.
> **Estimated time**: 15 min
> **Prerequisites**:
> - [01-architecture-tour.md](01-architecture-tour.md) — feel the four doc types first
> - [02-start-here.md](02-start-here.md) — see the 3-level dispatcher diagram

Use this tutorial when you find yourself thinking "why is the playbook shaped this way?" Each section is short and self-contained; you can jump to any heading.

---

## 1. Why git submodule for distribution (≤3 min)

**The problem**: consumer repos need a stable, versioned reference to the playbook's docs and scripts. Upgrades must be explicit and reversible.

**Walk through the decision**:

- Open `.gitmodules` in any consumer repo. You will see a single `[submodule ".ai-playbook"]` entry with a pinned URL and a checked-out tag.
- Compare with an npm-style dependency: `npm` resolves a semver range at install time; you cannot easily say "use exactly this commit forever until I bump."
- Compare with a vendored copy-paste: vendoring loses the upstream history and forces manual diffs.

**Why submodule wins here**:

- Every consumer pins a specific semver tag — upgrades are explicit.
- Consumers can diverge on branches and still inherit a known-good base.
- Alternative considered: npm / PyPI package. Rejected because the playbook is dogma-driven (docs + scripts + specs), not a runtime artifact — package registries don't model "pin a tag, read the docs" well.

---

## 2. Why LLM-agnostic (≤3 min)

**The problem**: every LLM CLI (Claude Code, Gemini CLI, Cursor, Antigravity) has its own context-loading conventions. A playbook that picks one CLI forces duplication when a new CLI lands.

**Walk through the decision**:

- Open `AGENTS.md` at the repo root. It is the one source of truth.
- Open `CLAUDE.md` (in a consumer repo) — note it is a thin router pointing at `AGENTS.md`.
- Open `GEMINI.md` in the same consumer — also a thin router.
- Open `.cursor/rules/00-dispatcher.mdc` — same shape.

Each CLI sees the same content via its preferred entry point.

**Why this wins**:

- We use all four CLIs in parallel; the playbook serves all of them.
- A CLI-specific playbook (`CLAUDE.md`-only) would force duplication every time a new CLI emerges.
- The cost is one extra file per CLI (~10 lines each) — cheap.

---

## 3. Why MCP for tool distribution (≤3 min)

**The problem**: every LLM session needs a consistent set of tools (file system, git, Jira, Hindsight, Atlassian). Hard-coding tools per-CLI scales linearly with CLI count.

**Walk through the decision**:

- Open `mcp-servers.yaml` in any consumer repo. Each server is declared once.
- Open the per-CLI rendered configs (`.mcp.json` for Claude Code, the equivalents for Gemini/Cursor). They are generated from the YAML.
- Run `python .ai-playbook/scripts/mcp/render.py --project <name> --dry-run` to see the diff.

**Why this wins**:

- MCP (Model Context Protocol) is the emerging standard across providers.
- Consumers declare servers once in `mcp-servers.yaml` and render per-CLI configs.
- CLI hooks (Claude Code `PostToolUse`, Gemini equivalent) stay thin — they trigger, they don't enforce logic.

---

## 4. Why OTel Collector in parallel with Langfuse (≤3 min)

**The problem**: LLM-native traces (prompt, output, cost) live in Langfuse; infra signals (logs from k3s, metrics from services) live in OTel-native systems. Asking "review this infra problem" needs both joined.

**Walk through the decision**:

- Langfuse gives LLM-native views — great for agent-side debugging.
- OTel Collector + Tempo joins LLM traces with infra signals — required so a single query can correlate the two.

**Why this wins**:

- Running both adds ~1 day at MVP but unblocks the Phase 5 learning loop.
- Alternative considered: Langfuse-only with custom log exports. Rejected because correlating across providers becomes a custom pipeline you maintain forever.

---

## 5. Why 3-level dispatcher (not 2) (≤3 min)

**The problem**: there are three audiences that need different views of the same project:

1. The LLM CLI (needs project-specific rules and identity).
2. Team devs (need everything *except* the personal owner's notes).
3. The personal owner who also wants personal context loaded.

**Walk through the decision**:

- Open `~/.ai-playbook/projects.yaml`. Each entry has `personal: true|false`.
- Re-read the diagram in [02-start-here.md](02-start-here.md) §2.

**Why three levels win**:

- Team devs (future) must not see the owner's personal add-on (`ELIGIA.md`).
- Projects must stay LLM-agnostic.
- Personal overrides live at a third layer loaded only when cwd is a personal project — isolation by load-time, not by git.
- A 2-level setup (universal + project) cannot express "load this only for me" without secrets-in-git.

---

## What's next

- [Concept: dispatcher-chain](../concepts/dispatcher-chain.md) — the full normative contract behind §5.
- [Concept: mcp-servers-schema](../concepts/mcp-servers-schema.md) — the schema behind §3.
- [Concept: agent-telemetry](../concepts/agent-telemetry.md) — the observability design behind §4.
- [Concept: development-flow](../concepts/development-flow.md) — the day-to-day flow that builds on all five choices.
- [05-learning-path.md](05-learning-path.md) — internalise these choices via the self-paced learning path.
