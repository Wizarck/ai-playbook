# Runbook: turn ponytail on/off in a project

> **When to use this runbook.** You want a project's agent (Claude Code, Codex,
> Gemini) to build the laziest solution that works — YAGNI, stdlib and native
> first, shortest diff. This runbook walks through enabling, disabling, and
> rolling back.

## Default-on policy

Like caveman, **new projects bootstrapped via `python -m scripts.bootstrap
<name>` have ponytail ON by default** (mode `ultra`, all four components). The
playbook itself also dogfoods ponytail ON (the `ponytail/ruleset:full` block is
committed in this repo's `AGENTS.md`).

Opt out at bootstrap time with `--no-ponytail`:

```bash
python -m scripts.bootstrap acme --owner me@example.com --no-ponytail
```

Or flip it off later with `python -m scripts.ponytail off` (see below), or from
the config UI (Features tab).

## Prerequisites

- The project has an `AGENTS.md` at its root (required for
  `--components code_style`).
- Python 3.11+ available as `python` on PATH.
- The ai-playbook checkout is reachable; `PYTHONPATH` includes its root, or you
  `cd` into it before running the commands.

## Turning ponytail ON

Default: enable the lazy ruleset with `full` intensity:

```bash
cd C:/Projects/ai-playbook
python -m scripts.ponytail on --project C:/Projects/eligia-core
```

What this does:

1. Validates inputs.
2. Backs up the pre-write AGENTS.md to
   `<project>/.ai-playbook/backups/agents/AGENTS.md.<ts>.bak`.
3. Writes `<project>/AGENTS.md` with a new marker-fenced block:

   ```html
   <!-- BEGIN auto-managed: ponytail/ruleset:full -->
   ...the ladder + mode + when-not-to-be-lazy + boundaries...
   <!-- END auto-managed -->
   ```

   The block is composed from sections in
   [skills/ponytail/SKILL.md](../../skills/ponytail/SKILL.md).

4. Writes `<project>/.ai-playbook/ponytail.json` with `enabled: true`,
   `mode: "full"`, `components.code_style: true`.

On next Claude Code session start, the AGENTS.md block puts the model in lazy
mode from message one. The `UserPromptSubmit` hook
([scripts/rules/ponytail-reinforce.rule.py](../../scripts/rules/ponytail-reinforce.rule.py))
emits a per-turn reminder against drift back to over-building.

### Enabling the companion skills

```bash
python -m scripts.ponytail on \
  --mode full \
  --components code_style,review_ponytail,audit_ponytail,debt_ponytail \
  --project C:/Projects/eligia-core
```

`review_ponytail` / `audit_ponytail` / `debt_ponytail` are pure capability
flags — they gate the `/ponytail-review`, `/ponytail-audit`, and
`/ponytail-debt` skills, with no file mutation.

### Other modes

```bash
python -m scripts.ponytail on --mode lite   # name the lazier alternative, user picks
python -m scripts.ponytail on --mode full   # the ladder enforced
python -m scripts.ponytail on --mode ultra  # default — YAGNI extremist, challenge the requirement
```

Changing modes is a single in-place rewrite of the AGENTS.md marker line +
body. No need to `off` first.

## Checking status

```bash
python -m scripts.ponytail status --project C:/Projects/eligia-core
```

Human-readable output:

```
ponytail: ON (mode=full)
project: C:/Projects/eligia-core
state:   C:/Projects/eligia-core/.ai-playbook/ponytail.json
ladder block in AGENTS.md: yes
components:
  ✓ code_style
  · review_ponytail
  · audit_ponytail
  · debt_ponytail
```

For UI / scripting: `python -m scripts.ponytail status --json --project ...`.

## Turning ponytail OFF

```bash
python -m scripts.ponytail off --project C:/Projects/eligia-core
```

What this does:

1. Strips the marker-fenced block from AGENTS.md (idempotent — no-op if no
   block; backs up first if a block existed).
2. Writes the state file with `enabled: false` and all components `false`.

The backup files stay in place after `off` (deliberate — they're your safety
net against accidental data loss).

## Rolling back

### Restore the latest AGENTS.md backup

```bash
ls C:/Projects/eligia-core/.ai-playbook/backups/agents/
# pick the newest .bak
cp .ai-playbook/backups/agents/AGENTS.md.<ts>.bak ./AGENTS.md
python -m scripts.ponytail off --project .  # sync the state file
```

## Debug

### Confirm the materialise block is correct

```bash
grep -A 1000 "BEGIN auto-managed: ponytail" C:/Projects/eligia-core/AGENTS.md \
  | grep -B 1000 "END auto-managed" | head -50
```

### Verify hook routing

The `ponytail-reinforce.rule.py` `UserPromptSubmit` hook ships in the bootstrap
settings template
([templates/new-project/.claude/settings.json.tmpl](../../templates/new-project/.claude/settings.json.tmpl),
alongside `caveman-reinforce`), so new projects get it from message one. It is
silent-fail: present always, emits only when `code_style` is ON. If the per-turn
reminder is not firing, confirm the entry exists:

```bash
cat C:/Projects/eligia-core/.claude/settings.json | python -m json.tool \
  | grep -A 8 UserPromptSubmit
```

If absent (the project was bootstrapped before ponytail landed), add the hook to
the `UserPromptSubmit` array in `.claude/settings.json` — it coexists with
`caveman-reinforce` in the same `hooks` list:

```json
{
  "type": "command",
  "command": "python .ai-playbook/scripts/rules/ponytail-reinforce.rule.py",
  "timeout": 5
}
```

or re-copy the canonical surface from the playbook template (the same step the
caveman runbook uses for its hook).

### Verify the toggle file is schema-valid

```bash
python -c "from scripts.ponytail.toggle import read_state; from pathlib import Path; print(read_state(Path(r'C:/Projects/eligia-core')))"
```

## See also

- [docs/operations/ponytail-architecture.md](../operations/ponytail-architecture.md) — full architecture and UI integration contract.
- [docs/concepts/ponytail-mode.md](../concepts/ponytail-mode.md) — design overview.
- [specs/ponytail-toggle.md](../../specs/ponytail-toggle.md) — the formal state contract.
