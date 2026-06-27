# Runbook: turn caveman on/off in a project

> **When to use this runbook.** You want a project's agent (Claude
> Code, Codex, Gemini) to respond in compressed caveman style and/or
> wrap MCP servers with `caveman-shrink`. This runbook walks through
> enabling, disabling, and rolling back.

## Default-on policy

**New projects bootstrapped via `python -m scripts.bootstrap <name>`
have caveman ON by default** (mode=`ultra`, all six components). The
activation runs as step 4.6 of bootstrap, after templates are copied
and before MCP configs are rendered — so the freshly-rendered
`.mcp.json` / `.gemini/settings.json` get auto-wrapped via the
post-render hook in [scripts/mcp/render.py](../../scripts/mcp/render.py).

Opt out at bootstrap time with `--no-caveman`:

```bash
python -m scripts.bootstrap acme --owner me@example.com --no-caveman
```

Or flip it off later with `python -m scripts.caveman off` (see below).

**Existing consumers** (bootstrapped before this default landed) need
to activate caveman once with `python -m scripts.caveman on` — there
is no migration script. Bootstrap-time default-on is one-shot.

The playbook itself also runs with caveman ON
(`.ai-playbook/caveman.json` is committed to the playbook repo).

## Prerequisites

- The project has an `AGENTS.md` at its root (required for
  `--components response_style`).
- For `--components mcp_shrink`: Node + `npx` available on PATH; the
  `caveman-shrink` npm package will be resolved on first MCP startup.
- Python 3.11+ available as `python` on PATH.
- The ai-playbook checkout is reachable; `PYTHONPATH` includes its
  root, or you `cd` into it before running the commands.

## Turning caveman ON

Default: enable response style with `full` intensity:

```bash
cd C:/Projects/ai-playbook
python -m scripts.caveman on --project C:/Projects/eligia-core
```

What this does:

1. Validates inputs.
2. Writes `<project>/AGENTS.md` with a new marker-fenced block:

   ```html
   <!-- BEGIN auto-managed: caveman/ruleset:full -->
   ...ruleset...
   <!-- END auto-managed -->
   ```

   The block is composed from sections in
   [skills/caveman/SKILL.md](../../skills/caveman/SKILL.md).

3. Backs up the pre-write AGENTS.md to
   `<project>/.ai-playbook/backups/agents/AGENTS.md.<ts>.bak`.
4. Writes `<project>/.ai-playbook/caveman.json` with
   `enabled: true`, `mode: "full"`, `components.response_style: true`.

On next Claude Code session start, the AGENTS.md block puts the model
in caveman mode from message one. The `UserPromptSubmit` hook
([scripts/rules/caveman-reinforce.rule.py](../../scripts/rules/caveman-reinforce.rule.py))
emits a per-turn reminder against drift.

### With MCP shrink

```bash
python -m scripts.caveman on \
  --mode full \
  --components response_style,mcp_shrink \
  --project C:/Projects/eligia-core
```

Adds:
- Wraps every stdio MCP entry in `<project>/.mcp.json` and
  `<project>/.gemini/settings.json` with
  `npx caveman-shrink -- <original-command>`.
- Backs up both files to `.ai-playbook/backups/mcp/`.

If `caveman-shrink` is not installed, the wrap still happens but the
CLI warns. Wrapped commands will fail at MCP startup until `npx`
resolves the package. Either install it (`npm i -g caveman-shrink` or
let `npx` resolve on first use) or run `mcp-restore` to undo.

### Other modes

```bash
python -m scripts.caveman on --mode lite   # gentler, ~25% reduction
python -m scripts.caveman on --mode full   # ~65%
python -m scripts.caveman on --mode ultra  # default — telegraphic, ~80%
```

Changing modes is a single in-place rewrite of the AGENTS.md marker
line + body. No need to `off` first.

## Checking status

```bash
python -m scripts.caveman status --project C:/Projects/eligia-core
```

Human-readable output:

```
caveman: ON (mode=full)
project: C:/Projects/eligia-core
state:   C:/Projects/eligia-core/.ai-playbook/caveman.json
materialised in AGENTS.md: yes
components:
  ✓ response_style
  · compress_docs
  · subagents_cavecrew
  · commit_caveman
  · review_caveman
  ✓ mcp_shrink
```

For UI / scripting:

```bash
python -m scripts.caveman status --json --project ...
```

## Turning caveman OFF

```bash
python -m scripts.caveman off --project C:/Projects/eligia-core
```

What this does:

1. Strips the marker-fenced block from AGENTS.md (idempotent — no-op
   if no block).
2. Unwraps every wrapped MCP entry, either via the in-file markers
   (preferred) or by restoring the latest backup (fallback).
3. Writes the state file with `enabled: false` and all components
   `false`.

The backup files stay in place after `off` (deliberate — they're your
safety net against accidental data loss). `--keep-backups` is a no-op
in the current version; future versions may add `--prune-backups` to
clean them up.

## Compressing a doc one-shot

Independent of `on`/`off`:

```bash
python -m scripts.caveman compress C:/Projects/ai-playbook/AGENTS.md \
  --mode full --json
```

What this does:

1. Backs up to `AGENTS.md.original.md` (refuses if a different backup
   already exists — signals an unfinalised earlier session).
2. Calls the LiteLLM proxy via `scripts._llm` with task_class
   `doc_writing_edit`.
3. Validates: every heading, code block, URL, and file path from the
   source appears byte-for-byte in the output.
4. On violation, retries with a targeted patch (up to 2 times). After
   2 failed retries, restores from `AGENTS.md.original.md` and exits 1.

Requires the LiteLLM proxy reachable at `$LITELLM_BASE_URL` (default
`http://localhost:4000`). See
[docs/concepts/model-routing.md](../concepts/model-routing.md) for the
proxy setup.

## Rolling back

### Restore the latest AGENTS.md backup

```bash
ls C:/Projects/eligia-core/.ai-playbook/backups/agents/
# pick the newest .bak
cp .ai-playbook/backups/agents/AGENTS.md.<ts>.bak ./AGENTS.md
python -m scripts.caveman off --project .  # sync the state file
```

### Restore the latest MCP backups

```bash
cp .ai-playbook/backups/mcp/.mcp.json.<ts>.bak ./.mcp.json
cp .ai-playbook/backups/mcp/settings.json.<ts>.bak ./.gemini/settings.json
# or just:
python -m scripts.caveman mcp-restore --project .
```

### Restore a `caveman-compress` source

```bash
cp some-doc.md.original.md some-doc.md
```

## Debug

### Confirm the materialise block is correct

```bash
# Show only the caveman block in AGENTS.md
grep -A 1000 "BEGIN auto-managed: caveman" C:/Projects/eligia-core/AGENTS.md \
  | grep -B 1000 "END auto-managed" | head -50
```

### Verify hook routing

The `UserPromptSubmit` hook is wired in the consumer's
`.claude/settings.json`. If the per-turn reminder is not firing,
confirm the entry exists:

```bash
cat C:/Projects/eligia-core/.claude/settings.json | python -m json.tool \
  | grep -A 5 UserPromptSubmit
```

If absent, re-render from the playbook template:

```bash
cd C:/Projects/ai-playbook
# Re-render claude-settings — exact command depends on which apply step
# the playbook ships at the time you read this (typically via
# `ai-playbook-check --select claude-settings --yes`).
```

### Verify MCP wrapping

```bash
python -c "import json; d=json.load(open(r'C:/Projects/eligia-core/.mcp.json')); print([k for k,v in d.get('mcpServers',{}).items() if v.get('_caveman_wrapped')])"
```

### Verify the toggle file is schema-valid

```bash
python -c "from scripts.caveman.toggle import read_state; from pathlib import Path; print(read_state(Path(r'C:/Projects/eligia-core')))"
```

## See also

- [docs/operations/caveman-architecture.md](../operations/caveman-architecture.md) — full architecture and UI integration contract.
- [docs/concepts/caveman-mode.md](../concepts/caveman-mode.md) — design overview.
- [specs/caveman-toggle.md](../../specs/caveman-toggle.md) — the formal state contract.
