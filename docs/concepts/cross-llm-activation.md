---
schema: concept/v1
slug: cross-llm-activation
title: Cross-LLM rule activation — placeholder
summary: |
  Per-LLM mapping of Cursor's 4 activation modes (always / auto / agent /
  manual). Documents the degradation matrix for Claude Code, Gemini CLI,
  and Cursor. Content rewrite scheduled in Slice 5.
---

# Cross-LLM rule activation — placeholder

> **Slice 4 placeholder**: stub for Slice 5 content rewrite (target v0.18.1).

## Activation modes (Cursor canonical)

| Mode | When loaded |
|---|---|
| `always` | Loaded into every turn's context unconditionally. |
| `auto` | Loaded when `globs:` matches a file in the current edit set. |
| `agent` | Loaded by description match when the agent decides it is relevant. |
| `manual` | Never auto-loaded; only when user explicitly references it. |

## Per-LLM degradation (D20)

| LLM | always | auto | agent | manual |
|---|---|---|---|---|
| **Cursor** | native | native (globs) | native (description routing) | native |
| **Claude Code** | inlined in AGENTS.md | requires AGENTS.md pointer | handled by skill harness | requires user mention |
| **Gemini CLI** | injected by `scripts/gemini_start.py` | NOT supported — degrades to manual | NOT supported — degrades to manual | requires user mention |

Validator (`scripts/validate_pairing.py`) warns if a rule uses non-`always`
activation AND lists Gemini in `applies_to`.

## See also

- [`enforcement-layers.md`](enforcement-layers.md)
- [`session-start-hook.md`](session-start-hook.md)
