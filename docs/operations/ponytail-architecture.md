# Ponytail feature — architecture and UI integration contract

> **Audience.** Engineers wiring a UI (web app, desktop app, IDE plugin) to
> toggle ponytail on/off across the user's projects. Also: anyone reading code
> in `scripts/ponytail/` and wondering how the pieces fit.
>
> **TL;DR for the UI implementer.** The UI is a thin wrapper around two CLI
> invocations: `python -m scripts.ponytail status --json` (read) and
> `python -m scripts.ponytail on|off [...]` (write). Everything else is
> downstream of the single state file at `<project>/.ai-playbook/ponytail.json`.

## 1. The state file (the contract the UI reads/writes)

**Path:** `<project>/.ai-playbook/ponytail.json`

**Schema:** [`schemas/schema-ponytail-toggle-v1.json`](../../schemas/schema-ponytail-toggle-v1.json) — JSON Schema 2020-12, `additionalProperties: false` everywhere. Validated on every read/write via `scripts.ponytail.toggle`.

**Example payloads:**

OFF (default — file may not exist, treated as OFF):

```json
{
  "schema": "ponytail-toggle/v1",
  "enabled": false,
  "mode": "full",
  "components": {
    "code_style": false,
    "review_ponytail": false,
    "audit_ponytail": false,
    "debt_ponytail": false
  },
  "applied_at": "2026-06-16T10:00:00+00:00"
}
```

ON with the lazy ruleset materialised, full intensity:

```json
{
  "schema": "ponytail-toggle/v1",
  "enabled": true,
  "mode": "full",
  "components": {
    "code_style": true,
    "review_ponytail": true,
    "audit_ponytail": true,
    "debt_ponytail": true
  },
  "applied_at": "2026-06-16T11:32:14+00:00",
  "applied_by": "arturo"
}
```

**UI MUST NOT touch this file directly.** Go through the CLI — it runs the side
effect (materialise) and its backup atomically. Writing the JSON without the
side effect produces inconsistent state (toggle says ON, AGENTS.md not
materialised → no actual ponytail block).

## 2. Public CLI surface

Every command the UI subprocess-calls. All commands accept `--project <PATH>`
to override auto-detection from cwd, and `--json` where applicable. Exit codes
follow the [error-message-standard](../rules/error-message-standard.rule.md):

| Code | Meaning |
|-----:|---------|
| 0    | OK |
| 1    | User-actionable error (bad input, schema violation, multiple blocks) |
| 2    | Environment/setup error (jsonschema missing, schema file missing, project root unresolved) |

### `status` — read

```bash
python -m scripts.ponytail status --json --project /path/to/project
```

Returns the current state plus computed derived flags:

```json
{
  "project_root": "C:/Projects/eligia-core",
  "state_path": "C:/Projects/eligia-core/.ai-playbook/ponytail.json",
  "state": { ... },
  "derived": { "materialised": true }
}
```

`derived.materialised` is `true` when `<project>/AGENTS.md` currently carries a
`<!-- BEGIN auto-managed: ponytail/ruleset:... -->` block.

### `on` — enable

```bash
python -m scripts.ponytail on \
  --mode {lite|full|ultra} \
  --components code_style,review_ponytail,audit_ponytail,debt_ponytail \
  --json --project /path/to/project
```

- Validates inputs (mode in `{lite, full, ultra}`, components in the
  schema-permitted set).
- If `code_style` is requested: materialise the ladder block into AGENTS.md
  (backed up first). This runs **before** the state write, so a side-effect
  failure returns exit 1 with the state file untouched (no "ON but not
  materialised" drift).
- Writes the state file last via atomic temp+rename.

`--json` output:

```json
{
  "ok": true,
  "state": { ... },
  "side_effects": {
    "agents_md_backup": "/path/.ai-playbook/backups/agents/AGENTS.md.2026-06-16T11-32-14Z.bak"
  }
}
```

### `off` — disable

```bash
python -m scripts.ponytail off --json --project /path/to/project
```

- Strips the AGENTS.md ladder block (idempotent — no-op when no block; backs up
  first if a block existed).
- Resets all components to `false`, sets `enabled: false`.
- Always writes the state file (so the UI can see a clean OFF).

## 3. Side-effect manifest

| Component         | Files touched         | Backup area |
|-------------------|-----------------------|-------------|
| `code_style`      | `<project>/AGENTS.md` | `.ai-playbook/backups/agents/AGENTS.md.<ts>.bak` |
| `review_ponytail` | *(none — capability flag for the /ponytail-review skill)* | *(n/a)* |
| `audit_ponytail`  | *(none — capability flag for the /ponytail-audit skill)*  | *(n/a)* |
| `debt_ponytail`   | *(none — capability flag for the /ponytail-debt skill)*   | *(n/a)* |

Ponytail's only persistent mutation is the AGENTS.md block. There is no MCP
wrapping and no doc compression (those are caveman-specific); the review / audit
/ debt components are pure capability gates with no on-disk effect.

Backups are written by `scripts.caveman.backup.make_backup` (the shared,
area-namespaced backup helper — area `agents`). Timestamp format:
`YYYY-MM-DDTHH-MM-SSZ` (colons stripped — Windows filenames cannot contain `:`).

## 4. State machine

```
                  ┌──────────────────────────────────────────┐
                  │             enabled = false              │
                  │ (default — ponytail.json absent or OFF)  │
                  └────────────┬─────────────────────────────┘
                               │
                 python -m scripts.ponytail on
                               │
                               ▼
                  ┌──────────────────────────────────────────┐
   ┌──── re-on    │             enabled = true               │
   │ (mode/comp)  │  materialised AGENTS.md if code_style     │
   │              └────────────┬─────────────────────────────┘
   │                           │
   │                python -m scripts.ponytail off
   │                           │
   │                           ▼
   │              ┌──────────────────────────────────────────┐
   └──────────────┤             enabled = false              │
                  │  AGENTS.md block stripped (if it was on)  │
                  │  backup files retained                    │
                  └──────────────────────────────────────────┘
```

**Idempotency:** running `on` twice with the same arguments is a no-op
(materialise rewrites identical content). Running `off` twice is a no-op.

**Mode change:** running `on --mode ultra` while already ON in `full` rewrites
the AGENTS.md marker line (`ponytail/ruleset:full` → `ponytail/ruleset:ultra`)
and the block body in a single step. No need to `off` first.

## 5. Failure & rollback

| Failure                                          | Behavior                                         |
|--------------------------------------------------|--------------------------------------------------|
| Backup write fails (disk full, perms)            | Refuse the mutation, return exit 1 with FIX.     |
| AGENTS.md missing on `on --components code_style` | Refuse with FIX: "create AGENTS.md first".       |
| AGENTS.md has 2+ ponytail blocks (manual edit)   | Refuse with FIX: "resolve manually".             |
| Mode invalid                                     | Refuse with FIX: "valid modes: lite\|full\|ultra". |
| SKILL.md missing a required H2 section            | Refuse with FIX: "fix skills/ponytail/SKILL.md".  |
| toggle file schema-invalid on read               | Refuse with FIX: "repair or delete state file".  |

**Rollback procedure (manual):**

```bash
# Restore the latest AGENTS.md backup:
cp .ai-playbook/backups/agents/AGENTS.md.<ts>.bak ./AGENTS.md

# Then write a clean OFF state:
python -m scripts.ponytail off --project .
```

## 6. Future UI integration recipe

### Python (e.g. a Textual TUI or a Django admin)

```python
import json
import subprocess

PROJECT = "C:/Projects/eligia-core"
PLAYBOOK = "C:/Projects/ai-playbook"  # cwd MUST be the playbook checkout

def get_state() -> dict:
    res = subprocess.run(
        ["python", "-m", "scripts.ponytail", "status", "--json", "--project", PROJECT],
        cwd=PLAYBOOK, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr)
    return json.loads(res.stdout)

def toggle_on(mode: str, components: list[str]) -> dict:
    res = subprocess.run(
        ["python", "-m", "scripts.ponytail", "on",
         "--mode", mode, "--components", ",".join(components),
         "--json", "--project", PROJECT],
        cwd=PLAYBOOK, capture_output=True, text=True, check=False,
    )
    return json.loads(res.stdout) if res.returncode == 0 else {"ok": False, "error": res.stderr}
```

**Important: cwd must be the playbook checkout.** The `scripts.ponytail`
package imports from `scripts.auto_managed` and `scripts.caveman.backup`.
The cleanest path is to set cwd to the playbook root every time.

The config UI (`config-ui/index.html`, Features tab) already does exactly this
through `scripts/apply_config.py` — see
[docs/runbooks/use-config-ui.md](../runbooks/use-config-ui.md).

## 7. Versioning

`ponytail-toggle/v1` is the only version. A `v2` bump triggers when the schema
needs breaking changes. Migration policy mirrors caveman's: a new schema file
lands alongside v1, a `scripts/ponytail/migrations/v1_to_v2.py` translates the
on-disk file in place (with a backup), and `read_state` dispatches on the
`schema` field. The UI SHOULD check `state.schema` matches the version it was
built against and refuse with a clear error if not.

## 8. Provenance

This feature is a Python port of [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT),
the code-minimalism sibling of JuliusBrussee/caveman. The port reuses the
playbook's caveman feature shape (toggle + materialise + CLI + config-UI
feature + `apply_config` delegation) and the shared utilities
(`scripts._project_root`, `scripts.auto_managed`, `scripts.caveman.backup`).

What was kept: the lazy-senior-dev ladder, the 3 intensity levels, the
`ponytail:` comment + debt-ledger convention, the review/audit skills.

What was dropped: the ~13-agent installer fan-out, the Node hooks + statusline,
the env-var/config-file default-mode resolution, the promptfoo JS harness. See
[docs/concepts/ponytail-mode.md](../concepts/ponytail-mode.md#what-was-deliberately-not-ported).

## See also

- [specs/ponytail-toggle.md](../../specs/ponytail-toggle.md) — formal state contract.
- [docs/runbooks/ponytail-toggle.md](../runbooks/ponytail-toggle.md) — operator's how-to.
- [docs/concepts/ponytail-mode.md](../concepts/ponytail-mode.md) — the why and design overview.
- [skills/ponytail/SKILL.md](../../skills/ponytail/SKILL.md) — the LLM-facing ruleset.
- [scripts/ponytail/](../../scripts/ponytail/) — the implementation.
