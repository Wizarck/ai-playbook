---
schema: concept/v1
slug: cross-llm-activation
title: Cross-LLM rule activation
summary: |
  Cursor defines a 4-mode activation framework (always / auto / agent /
  manual). Other LLMs do not implement all four. This doc maps each mode
  to the closest mechanism per LLM and the degradation that results.
last_validated: "2026-05-19"
---

# Cross-LLM rule activation

## Why

ai-playbook claims cross-LLM portability (Claude Code, Gemini CLI, Cursor). Cursor was the first to ship a four-mode activation framework for rules (`.cursor/rules/*.mdc`); other harnesses came later and shipped narrower mechanisms. Without an explicit degradation matrix, a rule author who specifies `activation: auto` assumes deterministic loading everywhere, when in fact Gemini CLI loads nothing automatically and Claude Code only injects `always` rules by default.

D11 binds `.cursor/rules/*.mdc` files as auto-generated from `docs/rules/<slug>.rule.md`. D20 names the degradation matrix below as the contract that defines what "applies_to: all" actually means per LLM.

## What

### Cursor canonical four modes

| Mode | When loaded |
|---|---|
| `always` | Loaded into every turn's context unconditionally. |
| `auto` | Loaded when `globs:` matches a file in the current edit set. |
| `agent` | Loaded by description match when the agent decides it is relevant. |
| `manual` | Never auto-loaded; only when the user explicitly references it. |

### Per-LLM degradation (D20)

| LLM | `always` | `auto` | `agent` | `manual` |
|---|---|---|---|---|
| **Cursor** | native | native (globs) | native (description routing) | native |
| **Claude Code** | inlined in AGENTS.md | requires AGENTS.md pointer | handled by skill harness | requires user mention |
| **Gemini CLI** | injected by `scripts/gemini_start.py` | not supported — degrades to manual | not supported — degrades to manual | requires user mention |

### Co-constraints validated at PR time

`scripts/validate_pairing.py` checks each rule's frontmatter:

- `activation: auto` requires `globs:` populated.
- `activation: agent` requires `description:` ≤300 chars (Cursor description routing matches on the description field).
- `activation: manual` cannot also list a `triggers:` set.
- A rule with non-`always` activation that lists Gemini in `applies_to` is warned: Gemini cannot honour it deterministically.

### Materialisation pipeline (D11)

`scripts/materialise_cursor_rules.py` reads each `docs/rules/<slug>.rule.md`, extracts the relevant frontmatter, and emits `.cursor/rules/<slug>.mdc` (gitignored mirror, regenerated on every session start). The same source-of-truth doc therefore drives all three LLMs: Cursor reads the `.mdc`, Claude Code reads the `.md` via the skill harness or AGENTS.md pointer, Gemini CLI receives an inlined excerpt at `gemini_start.py` boot.

## How it relates to other concepts

- The activation modes feed L2 enforcement — see `enforcement-layers.md` for how L2 composes with L1 hooks and L3 CI gates.
- The boot-time injection mechanism for Gemini (and the equivalent Claude / Cursor session-start) is described in `session-start-hook.md`.
- Routing decisions that select an LLM in the first place are documented in `model-routing.md`.
- The taxonomy of "rule", "skill", and "activation mode" is locked in `taxonomy.md`.

## Concrete example

Consider the rule `verdict-contract` (one of the six always-loaded universal rules per D16). Its frontmatter declares:

```yaml
schema: rule/v1
slug: verdict-contract
activation: always
applies_to: all
```

Behaviour per LLM:

- **Cursor**: `materialise_cursor_rules.py` emits `.cursor/rules/verdict-contract.mdc` with `activation: always`. Cursor loads it into every session unconditionally.
- **Claude Code**: the AGENTS.md always-loaded section inlines the binding clause (~50 tokens) and points at the full doc via `docs/rules/INDEX.md`. Loaded into every Claude session because AGENTS.md is itself always loaded.
- **Gemini CLI**: `scripts/gemini_start.py` reads the rule corpus filtered by `activation: always`, concatenates the binding clauses, and injects them into the system prompt at session start.

Now consider a hypothetical `python-test-runner` rule with `activation: auto, globs: ["tests/**/*.py"]`:

- **Cursor**: loads the rule when the user edits a file under `tests/`.
- **Claude Code**: AGENTS.md cannot intercept arbitrary file globs; the rule loads only via an explicit AGENTS.md "Rule Map" pointer that the user is expected to consult, or via a skill that invokes it.
- **Gemini CLI**: not loaded automatically; the user mentions it manually or the rule degrades to "informational doc".

The validator warns the rule author at PR time: `python-test-runner: activation=auto incompatible with applies_to=all (Gemini will not honour globs)`.

## Further reading

- D11 (Cursor `.mdc` auto-generated) and D20 (cross-LLM degradation) — Slice-5 plan decisions doc.
- Cursor rules documentation: `https://docs.cursor.com/context/rules` (Cursor).
- Anthropic skills + harness reference: `https://docs.anthropic.com/en/docs/agents` (Anthropic).
- Gemini CLI extension model: `https://github.com/google-gemini/gemini-cli` (Google).
