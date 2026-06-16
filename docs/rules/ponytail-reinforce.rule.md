---
schema: rule/v1
slug: ponytail-reinforce
description: Use when ponytail is ON for the consumer project — emits a brief per-turn reinforcement on UserPromptSubmit so the model keeps building the lazy/minimal solution mid-conversation, defending against drift back to over-building.
paired_hardrule: scripts/rules/ponytail-reinforce.rule.py
activation: auto
status: advisory
applies_to: all
triggers: [UserPromptSubmit]
last_validated: "2026-06-16"
---

# ponytail-reinforce — per-turn lazy-mode reminder

When ``<project>/.ai-playbook/ponytail.json`` has ``enabled: true`` and
``components.code_style: true``, this hook emits a short nudge on every
``UserPromptSubmit`` event to keep the model in lazy mode. The full ruleset is
already materialised into ``AGENTS.md`` (see
[ponytail/ruleset materialisation](../../scripts/ponytail/materialise.py)); this
hook is just an attention anchor against mid-conversation drift back to
over-building.

## Trigger

``UserPromptSubmit`` — fires once per user turn, before the model responds.
Shipped in the bootstrap settings template
([templates/new-project/.claude/settings.json.tmpl](../../templates/new-project/.claude/settings.json.tmpl))
alongside ``caveman-reinforce`` — the two coexist in the same ``hooks`` list and
each silently no-ops when its own feature is OFF. Registered in the consumer's
``.claude/settings.json``:

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python .ai-playbook/scripts/rules/ponytail-reinforce.rule.py",
        "timeout": 5
      }
    ]
  }
]
```

The hook's stdout is injected into the turn as system context (Claude Code
UserPromptSubmit convention).

## Behavior

1. Walk up from ``cwd`` to locate the project root (directory containing
   ``AGENTS.md``).
2. Read ``<project>/.ai-playbook/ponytail.json`` if present.
3. If the file is missing, ``enabled`` is false, or ``components.code_style``
   is false → exit 0 silently. Emit nothing.
4. Otherwise emit a one-paragraph nudge to stdout and exit 0.

## Output (when active)

A single paragraph, ≤ 50 tokens:

> Ponytail mode active (intensity: ``<mode>``). Build the minimum that works:
> YAGNI, then stdlib, native, installed dep, one line. No unrequested
> abstractions, deps, or boilerplate. Deletion over addition. Never simplify
> away validation, error handling, security, or accessibility. Mark deliberate
> shortcuts with a ``ponytail:`` comment.

## Trust boundary

This hook is a **reinforcement**, not the canonical rule. The full ponytail
ruleset lives in [skills/ponytail/SKILL.md](../../skills/ponytail/SKILL.md) and
is materialised into ``AGENTS.md`` when ``code_style`` is enabled. This hook
never reads ``SKILL.md`` at runtime (too slow — must stay under 5ms for the
UserPromptSubmit SLA); the nudge text is hardcoded.

If the materialised block and the hardcoded nudge ever disagree, the
materialised block wins — it carries the full rule, the hook only carries an
anchor.

## Failure modes

The hook MUST NOT block the user turn. Any error short-circuits to exit 0 with
no output:

- Toggle file missing → no-op.
- Toggle file malformed JSON → no-op.
- Toggle file schema-invalid → no-op (the hook does not validate; that's the
  CLI's job at write time).
- Project root not found → no-op.
- ``cwd`` inaccessible / permission denied → no-op.

## Performance

The hook performs at most: one ``Path.cwd()`` call, one walk-up loop, one small
JSON read (<1 KB), one ``print``. P50 budget: ≤ 5 ms. It does not import
jsonschema, yaml, or any heavy module — stdlib ``json`` only.

## See also

- [skills/ponytail/SKILL.md](../../skills/ponytail/SKILL.md) — full ponytail ruleset.
- [scripts/ponytail/materialise.py](../../scripts/ponytail/materialise.py) — sibling materialise step (persistent block in AGENTS.md).
- [docs/concepts/ponytail-mode.md](../concepts/ponytail-mode.md) — design overview.
- [docs/rules/caveman-reinforce.rule.md](caveman-reinforce.rule.md) — the prose-compression twin hook.
