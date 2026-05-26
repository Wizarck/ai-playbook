---
schema: concept/v1
slug: skills-mcps-enforcement
description: Per-consumer opt-out toggles for which Skills and MCP servers participate in the playbook's enforcement pipeline (materialisation + rendering).
audience: developer
last_validated: "2026-05-26"
---

# Skills + MCPs enforcement

## What it is

Two negative-list state files that let each consumer opt OUT of specific
Skills and MCP servers shipped by the playbook, without having to fork or
modify the playbook itself.

```
<consumer>/.ai-playbook-state/skills-enforce.json   ← schema: skills-enforce/v1
<consumer>/.ai-playbook-state/mcps-enforce.json     ← schema: mcps-enforce/v1
```

Both files share the same negative-list shape:

```json
{
  "schema": "skills-enforce/v1",
  "disabled": ["bmad-cis-storytelling", "bmad-tea"],
  "applied_at": "2026-05-26T15:00:00Z",
  "applied_by": "config-ui"
}
```

Default — when the file is absent or `disabled` is empty — is **all
enforced**, preserving exact pre-feature behaviour for every existing
consumer.

## Why negative-list

The playbook ships ~80 skills and ~10 MCP servers, and that grows over
time. A positive-list ("here are the ones I want") would require every
consumer to maintain a long enumeration of names they don't care about
and update it on every playbook bump. A negative-list ("here are the
two I don't want") stays minimal: the median consumer's state file is
either absent or carries 0–3 entries.

Skills/MCPs renamed or removed upstream become orphan IDs in the
disabled list — readers ignore them silently rather than erroring, so a
consumer's bundle never breaks because the playbook evolved.

## How the toggles are honoured

### Skills

`scripts/materialise_skills.py` reads `disabled_skills(consumer_root)`
from `scripts._enforce_state`. The disabled slug list is:

1. Excluded from the source-tree fingerprint (so an unchanged disabled
   set + an unchanged source = the same hash, and the materialiser
   correctly identifies the run as a no-op).
2. Passed to `shutil.copytree(..., ignore=...)` so the disabled
   top-level skill directories never reach the mirrors:

   ```
   <consumer>/.claude/skills/<slug>/    ← absent for disabled slugs
   <consumer>/.gemini/skills/<slug>/    ← absent for disabled slugs
   <consumer>/skills/<slug>/            ← absent for disabled slugs
   ```

Disabling a skill that was previously materialised triggers a one-off
rewrite of the three mirrors (because the source fingerprint changes).
The orphan removal pass (rmtree + copytree) wipes the previously-
mirrored copy. Re-enabling reverses this on the next materialise pass.

### MCPs

`scripts/mcp/render.py` and `scripts/mcp/validate.py` both call
`disabled_mcps(consumer_root)` after the 3-layer merge
(`merge_servers(base, project, personal)`) and strip the disabled IDs
from the merged map BEFORE downstream checks run. This means:

- `.mcp.json` (Claude Code) and `.gemini/settings.json` (Gemini CLI)
  never include the disabled servers.
- The `scope: personal` leak check ignores disabled servers (so a
  disabled entry can't block the render via an unrelated layer
  mismatch).
- `env.required` presence checks ignore disabled servers (so a
  disabled server requiring an unset env var no longer reports as
  missing).
- The validate-drift comparison treats the rendered file as authoritative
  for what's enforced; disabled servers being absent is the correct
  state.

## How operators control it

### Config UI (recommended)

Open `tools/config-ui/index.html` (file:// or `python -m http.server`
in that directory). The **Skills** and **MCPs** tabs show every shipped
entry with a default-checked checkbox. Uncheck what you don't want,
click **Export bundle**, and run:

```bash
python -m scripts.apply_config .ai-playbook/applied-config.json
```

`apply_config` writes the two state files. The next `materialise_skills`
and `mcp/render` invocations honour the new state.

### Manual edit

The state files are plain JSON and stable across playbook bumps. You
can edit them directly:

```bash
mkdir -p .ai-playbook-state
cat > .ai-playbook-state/skills-enforce.json <<EOF
{"schema": "skills-enforce/v1", "disabled": ["bmad-tea"]}
EOF
```

Then run `python -m scripts.materialise_skills` to reflect the change.

### Bundle JSON shape

Both sections in the exported config bundle are optional:

```json
{
  "schema": "ai-playbook-config/v1",
  "skills_enforce": { "disabled": ["bmad-tea", "bmad-cis-storytelling"] },
  "mcps_enforce": { "disabled": ["guardrails-mcp"] }
}
```

Omitting a section in the bundle leaves the corresponding on-disk state
file untouched. An empty `disabled` array still produces a state file
(explicit no-op intent that pins "everything enforced" against future
playbook additions).

## Refreshing the inventories

The config UI loads `tools/config-ui/skills-inventory.json` and
`tools/config-ui/mcps-inventory.json` to decide what to render. When
the playbook adds/removes a skill or MCP server, those files need a
refresh:

```bash
python -m scripts.build_enforce_inventories
git add tools/config-ui/skills-inventory.json tools/config-ui/mcps-inventory.json
git commit -m "chore(ui): refresh skills + mcps inventories"
```

The inventories are deterministic — re-running the builder on the same
playbook tree yields byte-identical files (modulo the
`generated_at` timestamp).

## Files

| File | Role |
|---|---|
| [schemas/schema-skills-enforce-v1.json](../../schemas/schema-skills-enforce-v1.json) | State-file schema for the Skills opt-out list |
| [schemas/schema-mcps-enforce-v1.json](../../schemas/schema-mcps-enforce-v1.json) | State-file schema for the MCPs opt-out list |
| [scripts/_enforce_state.py](../../scripts/_enforce_state.py) | Stdlib helper for reading the state files |
| [scripts/build_enforce_inventories.py](../../scripts/build_enforce_inventories.py) | Generator for the UI inventories |
| [scripts/apply_config.py](../../scripts/apply_config.py) | Writes the state files from a bundle |
| [scripts/materialise_skills.py](../../scripts/materialise_skills.py) | Honours the Skills opt-out list |
| [scripts/mcp/render.py](../../scripts/mcp/render.py) | Honours the MCPs opt-out list |
| [tools/config-ui/index.html](../../tools/config-ui/index.html) | Skills + MCPs tabs |
