# Concept: ponytail mode

> *The best code is the code never written.* — DietrichGebert/ponytail

## What it is

Ponytail mode makes coding agents reach for the **laziest solution that
actually works** — channelling a senior dev who questions whether a task
needs to exist at all (YAGNI), prefers the standard library to custom code,
native platform features to dependencies, and one line to fifty. Output is
*less code*, not lower quality: trust boundaries (validation, error handling,
security, accessibility) are never simplified away.

It is the **code-minimalism twin of [caveman](caveman-mode.md)**. Caveman
compresses how the agent *talks* (telegraphic prose → fewer output tokens);
ponytail disciplines what the agent *builds* (fewer lines, fewer files, fewer
dependencies). The two axes are orthogonal and compose — caveman trims the
talk, ponytail trims the diff.

The ai-playbook implementation is a Python port of
[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT),
scoped to the playbook's existing infrastructure (skills, hooks, materialise)
and built on the exact same feature shape as caveman (toggle + materialise +
CLI + config-UI feature).

## Why we want it

1. **Less code per task.** The upstream benchmark (5 tasks × 3 Claude models,
   10 runs each) measured 80–94 % fewer lines vs an unguided agent, with
   47–77 % cost reduction. Ponytail's own caveman-vs-ponytail run produced
   ~2.5× less code than caveman for the same tasks.
2. **Less to maintain.** Every line not written is a line nobody debugs at 3am.
   Deletion-first, fewest-files keeps the surface small.
3. **Native over custom.** `<input type="date">` over a picker lib,
   `functools.lru_cache` over a hand-rolled TTL cache, `arr.sort()` over a
   hand-rolled quicksort. The platform team already did the work.
4. **Composes with caveman.** Run both ON for compounding savings: caveman
   shrinks the prose, ponytail shrinks the code.

What it does NOT change:
- **Thinking tokens** — the model's internal reasoning is untouched.
- **Trust-boundary code** — input validation, error handling that prevents
  data loss, security, accessibility, and hardware calibration are explicitly
  out of scope for laziness (see "When NOT to be lazy" in the SKILL).
- **Explicitly requested work** — if the user asks for the full version, build
  it; no re-arguing.

## How it composes with the playbook

```
┌──────────────────────────────────────────────────────────────┐
│ <project>/.ai-playbook/ponytail.json                         │
│   Single source of truth — written via scripts/ponytail/cli.py│
└──────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌─────────────────┐   ┌──────────────────┐
│ AGENTS.md     │    │ UserPromptSubmit │   │ Capability gates │
│ ladder block  │    │ hook (per-turn   │   │ review / audit / │
│ (code_style)  │    │ reinforcement)   │   │ debt skills      │
└───────────────┘    └─────────────────┘   └──────────────────┘
        │                     │                     │
        │  Claude Code session start                │
        ▼                     ▼                     ▼
┌──────────────────────────────────────────────────────────────┐
│ Agent (Claude Code, Codex, Gemini) builds the lazy solution   │
└──────────────────────────────────────────────────────────────┘
```

The toggle CLI ([scripts/ponytail/cli.py](../../scripts/ponytail/cli.py))
drives the side effects from the one state file:

1. **AGENTS.md materialise** ([scripts/ponytail/materialise.py](../../scripts/ponytail/materialise.py))
   — when `code_style` is on, injects a marker-fenced block using the
   [`auto-managed-sections`](auto-managed-sections.md) convention so `git diff`
   shows the block and the drift checker can validate it. The block body is
   composed from `skills/ponytail/SKILL.md`, keeping the skill the SSOT.

2. **Per-turn reinforcement hook** ([scripts/rules/ponytail-reinforce.rule.py](../../scripts/rules/ponytail-reinforce.rule.py))
   — a `UserPromptSubmit` hook that emits a ~50-token nudge each turn when
   `code_style` is on, anchoring against mid-conversation drift back to
   over-building.

3. **Capability gates** — `review_ponytail`, `audit_ponytail`, `debt_ponytail`
   are pure flags (no file mutation) that gate the
   [`/ponytail-review`](../../skills/ponytail-review/SKILL.md),
   [`/ponytail-audit`](../../skills/ponytail-audit/SKILL.md), and
   [`/ponytail-debt`](../../skills/ponytail-debt/SKILL.md) skills.

The one persistent side effect (`code_style` → AGENTS.md) is **reversible**:
AGENTS.md is backed up under `<project>/.ai-playbook/backups/agents/` before
mutation, and `ponytail off` strips the block.

## Intensity levels

| Level | What changes |
|-------|--------------|
| **lite** | Build what's asked, but name the lazier alternative in one line. User picks. |
| **full** | The ladder enforced; stdlib and native first; shortest diff, shortest explanation. Default. |
| **ultra** | YAGNI extremist. Deletion before addition. Ship the one-liner and challenge the rest of the requirement in the same breath. |

## The `ponytail:` comment convention

Deliberate simplifications are marked with a `ponytail:` comment so a shortcut
reads as intent, not ignorance. A shortcut with a known ceiling names the
ceiling and the upgrade path:

```python
# ponytail: global lock, per-account locks if throughput matters
```

The [`/ponytail-debt`](../../skills/ponytail-debt/SKILL.md) skill harvests
these into a ledger so a deferral can't quietly become permanent.

## Why the per-project state file (not global)

A developer often wants ponytail ON for a greenfield app (where lean wins) and
OFF for a codebase with strict house abstractions (where "inline it" fights the
conventions). A global state file would force all-or-nothing. Like caveman,
ponytail is **default-ON at bootstrap** (opt out with `--no-ponytail`), and the
playbook itself dogfoods it ON — the `ponytail/ruleset:full` block is committed
in this repo's `AGENTS.md`. Everything still stays visible in a `git diff`
(nothing happens that isn't materialised in-tree), matching the playbook's
"explicit context injection" culture.

## What was deliberately NOT ported

- **The ~13-agent installer fan-out.** Upstream ships installers for Cursor,
  Windsurf, Cline, Kiro, OpenCode, Copilot, Gemini-extension, etc. The playbook
  is scoped to Claude Code + Codex + Gemini via the existing materialise
  pipeline; multi-agent rollout is a separate effort.
- **The Node.js hooks + statusline badge.** Upstream activates via SessionStart
  stdout-injection and a statusline. We use explicit AGENTS.md materialisation
  (auditable, reversible, in `git diff`) plus the Python `UserPromptSubmit`
  reinforcement rule.
- **The env-var / `~/.config/ponytail/config.json` default-mode resolution.**
  The playbook's source of truth is the per-project `ponytail.json`, written
  through the CLI / config UI — not a global config file.
- **The promptfoo JS benchmark harness.** We add a ponytail arm to the
  playbook's own Python eval harness instead.

## Discipline methodology {#discipline-methodology}

The dashboard's **"Ponytail discipline"** panel reports a single honest number:
the count of deliberate simplifications taken, measured by
[scripts/ponytail/stats.py](../../scripts/ponytail/stats.py).

1. **Measure (stock).** `count_markers()` walks the consumer tree and counts
   lines carrying a `ponytail:` comment marker — the same `(#|//) ?ponytail:`
   contract that [`/ponytail-debt`](../../skills/ponytail-debt/SKILL.md) harvests,
   so the panel count and the debt ledger always agree. The vendored playbook
   checkout (`.ai-playbook` / `.skills-sources`) is skipped so the count is the
   *consumer's own* markers, not the playbook's.
2. **Measure (flow).** When the dashboard window is set, `markers_added_since()`
   counts markers ADDED in git within the window (a *flow* rate alongside the
   *stock*), so the panel can show "N in tree · M added (last 7d)". Submodule
   markers are excluded for free (the parent repo tracks submodules as pointers);
   the field is omitted — never faked to 0 — when git can't answer.
3. **Report.** The panel shows those counts plus the active mode/components. There
   is **no dollar figure**: unlike caveman (which compresses *output tokens*, a
   physical quantity measurable per session), ponytail's savings are "lines not
   written", and attributing those to a session offline is not reliable. A count
   of cuts taken is the honest signal; a fabricated `$` would not be.

This is the **rung-1** instrument (the laziest measurement that actually works).

### Rung 2 — design constraints (from a BMAD party review)

A multi-SME review of a proposed rung-2 *considered-vs-built ratio* concluded it
would be a **vanity metric**: both the numerator (`skipped`) and the denominator
(`considered`) are self-authored by the same agent being scored, on the same
turn, and `considered` has no external ground truth. It is **dropped** from any
rung-2 v1. Hard constraints any future rung-2 must honour:

1. **Observables-only headline.** Surface only transcript-observable signals
   (e.g. build-rate, skips-per-build over *observed* builds, tally-emission-rate).
   Defer any ratio to a v2 gated on an eval harness that proves the self-report
   is stable and non-self-referential.
2. **Do not read transcript bodies.** caveman reads only `message.usage` /
   `message.model`, never `message.content`. Parsing response text is *new
   collection* (C7) and can pull paths/secrets into the publishable sidecar.
   Prefer an in-tree `.ai-playbook-state/ponytail-tallies.jsonl` (gitignored, in
   `stats.py` `SKIP_DIRS`) carrying int-only fields; egress enforced by a leak test.
3. **The schema change is not "silently additive".** Both `panels.ponytail`
   `oneOf` branches set `additionalProperties: false` and the aggregator validates
   on write, so a `discipline` block needs its **own explicitly declared branch**
   (or a `dashboard-data/v2` bump) — it cannot just be appended.
4. **Unit = a `message.id` group**, never a JSONL line (text and `tool_use`
   blocks live in separate assistant events). Gate hard: arithmetic check
   (`considered == built + skipped`), a one-sided `built ≤ distinct Edit/Write`
   ceiling, a min-tally floor (~30), default-OFF, and never instruct unmined
   agents (Codex/Gemini) to emit.

## See also

- [docs/operations/ponytail-architecture.md](../operations/ponytail-architecture.md) — UI integration contract (the doc to read if you're building a UI for this).
- [docs/runbooks/ponytail-toggle.md](../runbooks/ponytail-toggle.md) — how to turn it on/off operationally.
- [specs/ponytail-toggle.md](../../specs/ponytail-toggle.md) — formal state schema.
- [skills/ponytail/SKILL.md](../../skills/ponytail/SKILL.md) — the LLM-facing ruleset.
- [docs/concepts/caveman-mode.md](caveman-mode.md) — the prose-compression twin.
- [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) — upstream source (MIT).
