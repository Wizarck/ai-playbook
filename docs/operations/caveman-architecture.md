# Caveman feature — architecture and UI integration contract

> **Audience.** Engineers wiring a UI (web app, desktop app, IDE plugin)
> to toggle caveman on/off across the user's projects. Also: anyone
> reading code in `scripts/caveman/` and wondering how the pieces fit.
>
> **TL;DR for the UI implementer.** The UI is a thin wrapper around two
> CLI invocations: `python -m scripts.caveman status --json` (read) and
> `python -m scripts.caveman on|off [...]` (write). Everything else is
> downstream of that single state file at
> `<project>/.ai-playbook/caveman.json`.

## 1. The state file (the contract the UI reads/writes)

**Path:** `<project>/.ai-playbook/caveman.json`

**Schema:** [`schemas/schema-caveman-toggle-v1.json`](../../schemas/schema-caveman-toggle-v1.json) — JSON Schema 2020-12, `additionalProperties: false` everywhere. Validated on every read/write via `scripts.caveman.toggle`.

**Example payloads:**

OFF (default — file may not exist, treated as OFF):

```json
{
  "schema": "caveman-toggle/v1",
  "enabled": false,
  "mode": "full",
  "components": {
    "response_style": false,
    "compress_docs": false,
    "subagents_cavecrew": false,
    "commit_caveman": false,
    "review_caveman": false,
    "mcp_shrink": false
  },
  "applied_at": "2026-05-23T10:00:00+00:00"
}
```

ON with response style + MCP shrink (typical "everything terse" setup):

```json
{
  "schema": "caveman-toggle/v1",
  "enabled": true,
  "mode": "full",
  "components": {
    "response_style": true,
    "compress_docs": false,
    "subagents_cavecrew": false,
    "commit_caveman": false,
    "review_caveman": false,
    "mcp_shrink": true
  },
  "applied_at": "2026-05-23T11:32:14+00:00",
  "applied_by": "arturo"
}
```

**UI MUST NOT touch this file directly.** Go through the CLI — the CLI
runs side effects (materialise, MCP wrap, backups) atomically. Writing
the JSON without those side effects produces inconsistent state
(toggle says ON, AGENTS.md not materialised → no actual caveman).

## 2. Public CLI surface

Every command the UI subprocess-calls. All commands accept
`--project <PATH>` to override auto-detection from cwd, and `--json`
where applicable. Exit codes follow the
[error-message-standard](../rules/error-message-standard.rule.md):

| Code | Meaning |
|-----:|---------|
| 0    | OK |
| 1    | User-actionable error (bad input, schema violation, stale backup, etc.) |
| 2    | Environment/setup error (jsonschema missing, schema file missing, proxy unreachable) |

### `status` — read

```bash
python -m scripts.caveman status --json --project /path/to/project
```

Returns the current state plus computed derived flags:

```json
{
  "project_root": "C:/Projects/eligia-core",
  "state_path": "C:/Projects/eligia-core/.ai-playbook/caveman.json",
  "state": { ... },
  "derived": {
    "materialised": true
  }
}
```

`derived.materialised` is `true` when `<project>/AGENTS.md` currently
carries a `<!-- BEGIN auto-managed: caveman/ruleset:... -->` block.

### `on` — enable

```bash
python -m scripts.caveman on \
  --mode {lite|full|ultra} \
  --components response_style,mcp_shrink,compress_docs \
  --json --project /path/to/project
```

- Validates inputs (mode in `{lite, full, ultra}`, components in the
  schema-permitted set).
- Runs side effects in order, each with its own backup:
  1. If `response_style`: materialise the ruleset block into AGENTS.md.
  2. If `mcp_shrink`: wrap stdio entries in `.mcp.json` and
     `.gemini/settings.json`.
- On any side-effect failure, returns exit 1 with a canonical error;
  the state file is NOT updated (i.e. you don't end up saying "ON"
  with no actual materialisation).
- Writes the state file last via atomic temp+rename.

`--json` output:

```json
{
  "ok": true,
  "state": { ... },
  "side_effects": {
    "agents_md_backup": "/path/.ai-playbook/backups/agents/AGENTS.md.2026-05-23T11-32-14Z.bak",
    "mcp_shrink": {
      "claude":  {"path": ".../.mcp.json", "backup": "...", "wrapped": 13},
      "gemini":  {"path": ".../.gemini/settings.json", "backup": "...", "wrapped": 13}
    }
  }
}
```

### `off` — disable

```bash
python -m scripts.caveman off --json --project /path/to/project
```

- Strips the AGENTS.md block (idempotent — no-op when no block).
- Unwraps any wrapped MCP entries (markers-first, backup-fallback).
- Resets all components to `false`, sets `enabled: false`.
- Always writes the state file (so the UI can see a clean OFF).

### `compress` — one-shot doc compression

```bash
python -m scripts.caveman compress path/to/file.md \
  --mode {lite|full|ultra} [--force-large] --json
```

- Backs up to `<file>.original.md`.
- Calls the LiteLLM proxy via `scripts._llm` (`task_class=doc_writing_edit`).
- Validates byte-preservation contract (headings, code blocks, URLs,
  paths). Retries up to 2 times on violation; restores source from
  backup on final failure.

This is independent of `enabled`/`on`/`off` — it's a one-shot operation
gated by the user, not by the toggle. (The `components.compress_docs`
flag is a UI capability indicator, not a persistent side effect.)

### `mcp-shrink` / `mcp-restore` — manual MCP wrapping

```bash
python -m scripts.caveman mcp-shrink   --json   # wrap stdio entries
python -m scripts.caveman mcp-restore --json   # unwrap them
```

These are exposed for explicit invocation but the typical flow is
`caveman on --components mcp_shrink`, which calls them automatically.

### Not implemented yet (exit 2 with FIX guidance)

- `stats`    — session-token stats from Claude Code transcripts.
- `rollback` — manual restore-from-latest-backup across all areas.

## 3. Side-effect manifest

Every component → exact set of files mutated, paired with backup paths:

| Component        | Files touched                              | Backup area                                   |
|------------------|--------------------------------------------|-----------------------------------------------|
| `response_style` | `<project>/AGENTS.md`                      | `.ai-playbook/backups/agents/AGENTS.md.<ts>.bak` |
| `mcp_shrink`     | `<project>/.mcp.json`, `<project>/.gemini/settings.json` | `.ai-playbook/backups/mcp/{mcp.json,settings.json}.<ts>.bak` |
| `compress_docs`  | *(none persistent — gates the on-demand compress command)* | per-file at `<source>.original.md` |
| `subagents_cavecrew` | *(none — capability flag for agent delegation)* | *(n/a)* |
| `commit_caveman`     | *(none — capability flag for the skill)* | *(n/a)* |
| `review_caveman`     | *(none — capability flag for the skill)* | *(n/a)* |

Backup retention: 10 newest backups per `(area, basename)`, older
backups pruned by `scripts.caveman.backup.prune_backups`. (Currently
not auto-invoked; CLI prune will land alongside the `rollback`
subcommand.)

Timestamp format: `YYYY-MM-DDTHH-MM-SSZ` (colons stripped — Windows
filenames cannot contain `:`).

## 4. State machine

```
                  ┌──────────────────────────────────────────┐
                  │             enabled = false              │
                  │  (default — caveman.json absent or OFF)  │
                  └────────────┬─────────────────────────────┘
                               │
                  python -m scripts.caveman on
                               │
                               ▼
                  ┌──────────────────────────────────────────┐
   ┌──── re-on    │             enabled = true               │
   │ (mode/comp)  │  materialised AGENTS.md if response_style │
   │              │  wrapped .mcp.json     if mcp_shrink      │
   │              └────────────┬─────────────────────────────┘
   │                           │
   │              python -m scripts.caveman off
   │                           │
   │                           ▼
   │              ┌──────────────────────────────────────────┐
   └──────────────┤             enabled = false              │
                  │  AGENTS.md block stripped (if it was on)  │
                  │  .mcp.json entries unwrapped              │
                  │  backup files retained                    │
                  └──────────────────────────────────────────┘
```

**Idempotency:** running `on` twice with the same arguments is a no-op
(materialise rewrites identical content, shrink skips already-wrapped
entries). Running `off` twice is a no-op (nothing to strip/unwrap).

**Mode change:** running `on --mode ultra` while already ON in `full`
mode rewrites the AGENTS.md marker line (`caveman/ruleset:full` →
`caveman/ruleset:ultra`) and the block body in a single step. The
shrink layer is mode-agnostic (it's about input tokens, not output).

## 5. Failure & rollback

| Failure                                       | Behavior                                         |
|-----------------------------------------------|--------------------------------------------------|
| Backup write fails (disk full, perms)         | Refuse the mutation, return exit 1 with FIX.     |
| AGENTS.md missing on `on --components response_style` | Refuse with FIX: "create AGENTS.md first".       |
| AGENTS.md has 2+ caveman blocks (manual edit) | Refuse with FIX: "resolve manually".             |
| Mode invalid                                  | Refuse with FIX: "valid modes: lite|full|ultra". |
| Compress LLM call errors                      | Source untouched, backup retained, exit 2.       |
| Compress validation fails after 2 retries     | Source restored from backup, exit 1.             |
| MCP shrink: `caveman-shrink` npm not installed | Wrap still applied; CLI warns; commands will fail at runtime. Use `mcp-restore`. |
| toggle file schema-invalid on read            | Refuse with FIX: "repair or delete state file".  |

**Rollback procedure (manual, before `rollback` subcommand exists):**

```bash
# Restore the latest AGENTS.md backup:
cp .ai-playbook/backups/agents/AGENTS.md.<ts>.bak ./AGENTS.md

# Restore the latest .mcp.json backup:
cp .ai-playbook/backups/mcp/.mcp.json.<ts>.bak ./.mcp.json

# Then write a clean OFF state:
python -m scripts.caveman off --project .
```

## 6. Telemetry (future)

When `scripts/caveman/stats.py` lands (deferred — needs Claude Code
session-log access patterns to stabilise), the UI will read:

- `<project>/.ai-playbook/.caveman-stats.json` — running lifetime
  counts: tokens saved, USD saved, sessions tracked.
- `<project>/.ai-playbook/.caveman-statusline-suffix` — short string
  the statusline displays (`⛏ 12.4k`).

For now, the UI can compute a coarse "is materialised + how long since
last toggle" from `state.applied_at` and `derived.materialised`.

## 7. Future UI integration recipe

### Python (e.g. a Textual TUI or a Django admin)

```python
import json
import subprocess

PROJECT = "C:/Projects/eligia-core"  # from a project selector

def get_state() -> dict:
    res = subprocess.run(
        ["python", "-m", "scripts.caveman", "status", "--json", "--project", PROJECT],
        cwd="C:/Projects/ai-playbook",  # CWD must be the playbook checkout
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr)
    return json.loads(res.stdout)

def toggle_on(mode: str, components: list[str]) -> dict:
    res = subprocess.run(
        [
            "python", "-m", "scripts.caveman", "on",
            "--mode", mode,
            "--components", ",".join(components),
            "--json", "--project", PROJECT,
        ],
        cwd="C:/Projects/ai-playbook",
        capture_output=True, text=True, check=False,
    )
    return json.loads(res.stdout) if res.returncode == 0 else {"ok": False, "error": res.stderr}
```

### Node (e.g. a VS Code extension or Electron app)

```ts
import { spawnSync } from "node:child_process";

const PROJECT = "C:/Projects/eligia-core";
const PLAYBOOK = "C:/Projects/ai-playbook";

function getState(): unknown {
  const r = spawnSync("python", [
    "-m", "scripts.caveman", "status", "--json", "--project", PROJECT,
  ], { cwd: PLAYBOOK, encoding: "utf-8" });
  if (r.status !== 0) throw new Error(r.stderr);
  return JSON.parse(r.stdout);
}

function toggleOn(mode: string, components: string[]): unknown {
  const r = spawnSync("python", [
    "-m", "scripts.caveman", "on",
    "--mode", mode,
    "--components", components.join(","),
    "--json", "--project", PROJECT,
  ], { cwd: PLAYBOOK, encoding: "utf-8" });
  return r.status === 0 ? JSON.parse(r.stdout) : { ok: false, error: r.stderr };
}
```

**Important: cwd must be the playbook checkout.** The `scripts.caveman`
package imports from `scripts._llm` and `scripts.auto_managed`. Running
from a different cwd works only if `c:/Projects/ai-playbook` is on
`PYTHONPATH`. The cleanest path is to set cwd to the playbook root
every time.

### Project discovery

To populate a "which project?" dropdown in the UI, read the personal
registry at `~/.ai-playbook/projects.yaml`:

```yaml
schema: ai-playbook/projects-registry/v1
projects:
  eligia-core:
    path: C:/Projects/eligia-core
    personal: true
  ai-playbook:
    path: C:/Projects/ai-playbook
  # ...
```

See [docs/concepts/projects-registry.md](../concepts/projects-registry.md)
for the registry schema.

## 8. Versioning

`schema-caveman-toggle/v1` is the only version. A `v2` bump triggers
when the schema needs breaking changes (new required field, removed
field, semantics change). Migration policy:

1. New `schemas/schema-caveman-toggle-v2.json` lands alongside `v1`.
2. `scripts/caveman/migrations/v1_to_v2.py` translates the on-disk
   state file in place, with a backup at `<project>/.ai-playbook/backups/state/caveman.json.<ts>.bak`.
3. `scripts/caveman/toggle.py.read_state` detects the version field
   and dispatches the migration before validation.
4. CLI prints a one-line "Migrated v1→v2" notice on first run.

The UI does NOT need to handle migrations — the CLI does. But the UI
SHOULD check `state.schema` matches the version it was built against
and refuse with a clear error if not (the UI may also need code
changes for a v2 schema).

## 9. Provenance

This feature is a Python port of [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) (MIT).
The original is a Node-based skill installer for ~30 AI agents; this
port is scoped to the ai-playbook and uses the playbook's existing
materialise + hook + skill infrastructure instead of shipping a
parallel hook system.

What was kept:
- The 3 intensity levels (lite / full / ultra).
- The byte-preservation compression contract.
- The `caveman-shrink` MCP middleware (we wrap, the npm package proxies).
- The cavecrew subagent pattern (investigator / builder / reviewer).
- The honest-eval discipline (compare vs `Answer concisely.`, not vs baseline).

What was dropped:
- Wenyan (classical Chinese) modes — gimmick.
- SessionStart stdout-injection trick — opaque; we use explicit AGENTS.md
  materialisation for git-diffable auditability.
- Multi-agent (Cursor/Windsurf/Cline/Copilot) installer fan-out —
  playbook-scoped first; consumer rollout is a separate effort.

## See also

- [specs/caveman-toggle.md](../../specs/caveman-toggle.md) — formal state contract.
- [docs/runbooks/caveman-toggle.md](../runbooks/caveman-toggle.md) — operator's how-to.
- [docs/concepts/caveman-mode.md](../concepts/caveman-mode.md) — the why and design overview.
- [skills/caveman/SKILL.md](../../skills/caveman/SKILL.md) — the LLM-facing ruleset.
- [scripts/caveman/](../../scripts/caveman/) — the implementation.
