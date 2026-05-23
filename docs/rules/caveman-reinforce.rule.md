---
schema: rule/v1
slug: caveman-reinforce
description: Use when caveman is ON for the consumer project — emits a brief per-turn reinforcement on UserPromptSubmit so the model stays terse mid-conversation, defending against drift from competing plugin instructions.
paired_hardrule: scripts/rules/caveman-reinforce.rule.py
activation: auto
status: advisory
applies_to: all
triggers: [UserPromptSubmit]
last_validated: "2026-05-23"
---

# caveman-reinforce — per-turn caveman reminder

When ``<project>/.ai-playbook/caveman.json`` has ``enabled: true`` and
``components.response_style: true``, this hook emits a short nudge on every
``UserPromptSubmit`` event to keep the model in caveman style. The full
ruleset is already materialised into ``AGENTS.md`` (see
[caveman/ruleset materialisation](../../scripts/caveman/materialise.py));
this hook is just an attention anchor against mid-conversation drift.

## Trigger

``UserPromptSubmit`` — fires once per user turn, before the model
responds. Registered via the consumer's ``.claude/settings.json``:

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python .ai-playbook/scripts/rules/caveman-reinforce.rule.py",
        "timeout": 5
      }
    ]
  }
]
```

The hook's stdout is injected into the turn as system context (Claude Code
SessionStart/UserPromptSubmit convention).

## Behavior

1. Walk up from ``cwd`` to locate the project root (directory containing
   ``AGENTS.md``).
2. Read ``<project>/.ai-playbook/caveman.json`` if present.
3. If the file is missing, ``enabled`` is false, or
   ``components.response_style`` is false → exit 0 silently. Emit nothing.
4. Otherwise emit a one-paragraph nudge to stdout and exit 0.

## Output (when active)

A single paragraph, ≤ 50 tokens:

> Caveman mode active (intensity: ``<mode>``). Drop articles, filler,
> pleasantries. Fragments OK. Code unchanged. Auto-clarity exceptions:
> security warnings, irreversible actions, multi-step sequences,
> user confused.

## Trust boundary

This hook is a **reinforcement**, not the canonical rule. The full caveman
ruleset lives in [skills/caveman/SKILL.md](../../skills/caveman/SKILL.md)
and is materialised into ``AGENTS.md`` when ``response_style`` is enabled.
This hook never reads ``SKILL.md`` at runtime (too slow — must stay under
5ms for the UserPromptSubmit SLA); the nudge text is hardcoded.

If the materialised block and the hardcoded nudge ever disagree, the
materialised block wins — it carries the full rule, the hook only
carries an anchor.

## Failure modes

The hook MUST NOT block the user turn. Any error short-circuits to exit 0
with no output:

- Toggle file missing → no-op.
- Toggle file malformed JSON → no-op.
- Toggle file schema-invalid → no-op (the hook does not validate; that's
  the CLI's job at write time).
- Project root not found → no-op.
- ``cwd`` inaccessible / permission denied → no-op.

## Performance

The hook performs at most:
- One ``Path.cwd()`` call.
- One walk-up loop (bounded by filesystem depth).
- One small JSON read (<1 KB).
- One ``print`` call.

P50 budget: ≤ 5 ms. The hook does not import jsonschema, yaml, or any
heavy module — it uses stdlib ``json`` only.

## See also

- [skills/caveman/SKILL.md](../../skills/caveman/SKILL.md) — full caveman ruleset.
- [scripts/caveman/materialise.py](../../scripts/caveman/materialise.py) — sibling materialise step (persistent block in AGENTS.md).
- [docs/concepts/caveman-mode.md](../concepts/caveman-mode.md) — design overview (Phase H).
