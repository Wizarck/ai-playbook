# Concept: caveman mode

> *Why use many token when few token do trick.* — JuliusBrussee/caveman

## What it is

Caveman mode makes coding agents respond in a compressed, telegraphic
prose style — fragments, no articles, no filler — while preserving
full technical accuracy. Output tokens drop ~65-75% for the same
correctness; input tokens drop ~46% when the same compression is
applied to memory files (CLAUDE.md, AGENTS.md, project notes).

The ai-playbook implementation is a Python port of
[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) (MIT),
scoped to the playbook's existing infrastructure (skills, hooks,
materialise, MCP render).

## Why we want it

1. **Per-turn output savings.** ~65% reduction × every model response
   in a session. Compounds quickly in long sessions.
2. **Per-session input savings.** Compressing AGENTS.md / CLAUDE.md /
   long-form runbooks once saves ~46% of those bytes on every session
   start, forever.
3. **Per-turn MCP description savings.** Wrapping MCP servers with
   `caveman-shrink` shrinks tool descriptions sent on every turn —
   biggest win in sessions with many MCP servers.
4. **Speed.** Shorter responses mean faster wall-clock latency and
   faster human read time.
5. **Sometimes more correct.** A March 2026 paper ("Brevity Constraints
   Reverse Performance Hierarchies in Language Models") found that
   constraining large models to brief responses improved accuracy by
   26 points on some benchmarks. Verbose is not always better.

What it does NOT change:
- Thinking tokens (the model's internal reasoning is unaffected — only
  the output token budget shrinks).
- Code, tool inputs, commit messages, PR descriptions (these stay
  normal — separate skills `caveman-commit` and `caveman-review` cover
  those with opt-in compression).

## How it composes with the playbook

```
┌──────────────────────────────────────────────────────────────┐
│ <project>/.ai-playbook/caveman.json                          │
│   Single source of truth — written via scripts/caveman/cli.py │
└──────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌─────────────────┐   ┌──────────────────┐
│ AGENTS.md     │    │ UserPromptSubmit │   │ .mcp.json +      │
│ marker block  │    │ hook (per-turn   │   │ .gemini/settings │
│ (persistent)  │    │ reinforcement)   │   │ wrapped commands │
└───────────────┘    └─────────────────┘   └──────────────────┘
        │                     │                     │
        │  Claude Code session start                │
        ▼                     ▼                     ▼
┌──────────────────────────────────────────────────────────────┐
│ Agent (Claude Code, Codex, Gemini) responds in caveman style  │
│   + tool descriptions are compressed in-flight                │
└──────────────────────────────────────────────────────────────┘
```

The toggle CLI ([scripts/caveman/cli.py](../../scripts/caveman/cli.py))
orchestrates three derivable artefacts from the one state file:

1. **AGENTS.md materialise** ([scripts/caveman/materialise.py](../../scripts/caveman/materialise.py))
   — injects a marker-fenced block using the existing
   [`auto-managed-sections`](auto-managed-sections.md) convention so
   `git diff` shows the block clearly and the auto-managed drift
   checker can validate it.

2. **Per-turn reinforcement hook** ([scripts/rules/caveman-reinforce.rule.py](../../scripts/rules/caveman-reinforce.rule.py))
   — a `UserPromptSubmit` hook that emits a ~50-token nudge every turn
   when the toggle says ON. The full ruleset is already in AGENTS.md
   from step 1; this hook is just an attention anchor against drift
   from competing plugins.

3. **MCP wrap** ([scripts/caveman/mcp_shrink.py](../../scripts/caveman/mcp_shrink.py))
   — when `mcp_shrink` is on, every stdio MCP entry in the consumer's
   `.mcp.json` and `.gemini/settings.json` is rewritten to launch via
   `npx caveman-shrink -- <original>`. The proxy intercepts the MCP
   protocol and compresses tool descriptions on the wire.

Each side effect is **reversible**: backups land under
`<project>/.ai-playbook/backups/<area>/<file>.<ts>.bak` before any
mutation, and `caveman off` undoes everything.

## Why the per-project state file (not global)

A developer working across multiple projects often wants caveman ON
for, say, `eligia-core` (long-form architecture work) and OFF for
`palafito-b2b` (lots of API surface where verbose is safer). A global
state file would force all-or-nothing.

The trade-off: there's no default for projects that haven't been
toggled yet — they're OFF until explicitly turned ON. This is the
expected behavior and matches the playbook's "explicit context
injection" culture: nothing happens that isn't visible in a `git diff`.

## Honest evaluation discipline

The eval harness ([tests/evals/caveman/](../../tests/evals/caveman/))
runs a 3-arm comparison:

1. **Baseline** — no system prompt.
2. **Terse** — `Answer concisely.`
3. **Caveman** — `Answer concisely.\n\n<full SKILL.md ruleset>`.

The honest delta is **caveman vs terse**, not caveman vs baseline.
Claiming caveman saves N% vs baseline conflates the skill with generic
terseness ("Answer concisely." already cuts ~30%). Same discipline
used in the upstream JuliusBrussee/caveman `evals/` harness.

## What was deliberately NOT ported

- **Wenyan (classical Chinese) modes.** Brand gimmick from the
  original; not useful here.
- **The SessionStart stdout-injection trick.** The original injects
  the ruleset as invisible stdout from a SessionStart hook. Opaque to
  the user, invisible to `git diff`. We use explicit AGENTS.md
  materialisation instead — auditable, reversible, in-tree.
- **Multi-agent installer (Cursor / Windsurf / Cline / Copilot / 30+
  others).** The original ships a single installer for ~30 agent
  ecosystems. The playbook is scoped to Claude Code + Codex + Gemini
  via the existing `materialise_skills.py` pipeline; multi-agent
  fan-out is a separate future effort.
- **Statusline badge.** The original updates the Claude Code
  statusline with lifetime tokens saved. The plumbing is partly there
  (`.caveman-statusline-suffix` referenced in
  [docs/operations/caveman-architecture.md](../operations/caveman-architecture.md))
  but the producer (`scripts/caveman/stats.py`) is deferred until
  Claude Code session-log access patterns stabilise.

## See also

- [docs/operations/caveman-architecture.md](../operations/caveman-architecture.md) — UI integration contract (the doc to read if you're building a UI for this).
- [docs/runbooks/caveman-toggle.md](../runbooks/caveman-toggle.md) — how to turn it on/off operationally.
- [specs/caveman-toggle.md](../../specs/caveman-toggle.md) — formal state schema.
- [skills/caveman/SKILL.md](../../skills/caveman/SKILL.md) — the LLM-facing ruleset.
- [tests/evals/caveman/](../../tests/evals/caveman/) — the 3-arm eval harness.
- [ponytail-mode.md](ponytail-mode.md) — the code-minimalism twin (compresses what the agent *builds*, not how it *talks*).
- [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) — upstream source (MIT).
