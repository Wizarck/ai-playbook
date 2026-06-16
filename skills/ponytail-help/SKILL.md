---
name: ponytail-help
description: Use when the user asks how ponytail mode works, what intensity levels exist, what the slash commands are, how to toggle it, or wants a quick-reference card before turning the mode on. One-shot display, not a persistent mode. Trigger: /ponytail-help, "ponytail help", "what ponytail commands", "how do I use ponytail".
license: MIT
metadata:
  author: ai-playbook (ported from DietrichGebert/ponytail, MIT)
  version: "1.0"
---

# ponytail help

Display this reference card when invoked. One-shot: do NOT change mode, write
state files, or persist anything.

## What it is

Ponytail is the code-minimalism twin of caveman. Caveman compresses how the
agent *talks* (telegraphic prose, fewer output tokens); ponytail disciplines
what the agent *builds* (YAGNI → stdlib → native → installed dep → one line →
minimum). The two are orthogonal and run together.

## Levels

| Level | Trigger | What changes |
|-------|---------|--------------|
| **lite** | `/ponytail lite` | Build what's asked, name the lazier alternative in one line. |
| **full** | `/ponytail` | The ladder enforced: YAGNI → stdlib → native → one line → minimum. Default. |
| **ultra** | `/ponytail ultra` | YAGNI extremist. Deletion before addition. Challenges the requirement before building. |

Level persists until changed or session end.

## Skills

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **ponytail** | `/ponytail` | Lazy mode itself — simplest solution that works. |
| **ponytail-review** | `/ponytail-review` | Over-engineering review of the current diff: `L42: yagni: factory, one product. Inline.` |
| **ponytail-audit** | `/ponytail-audit` | Same lens, whole-repo instead of a diff. |
| **ponytail-debt** | `/ponytail-debt` | Harvest `ponytail:` comments into a tracked ledger. |
| **ponytail-help** | `/ponytail-help` | This card. |

## Toggle it (per project)

Ponytail is a per-project feature; state lives at `.ai-playbook/ponytail.json`
and is written only through the CLI or the config UI — never by hand.

```bash
python -m scripts.ponytail status [--json]
python -m scripts.ponytail on  --mode full --components code_style
python -m scripts.ponytail off
```

Components: `code_style` (inject the ladder into `AGENTS.md` + per-turn
reinforcement — the only one with a side effect), `review_ponytail`,
`audit_ponytail`, `debt_ponytail` (capability gates for the companion skills).

Or toggle it from the config UI (Features tab) — see
[docs/runbooks/ponytail-toggle.md](../../docs/runbooks/ponytail-toggle.md).

## Deactivate

Say "stop ponytail" or "normal mode", or run `python -m scripts.ponytail off`.
Resume anytime with `/ponytail`.

## More

- Concept + design: [docs/concepts/ponytail-mode.md](../../docs/concepts/ponytail-mode.md)
- Architecture + UI contract: [docs/operations/ponytail-architecture.md](../../docs/operations/ponytail-architecture.md)
