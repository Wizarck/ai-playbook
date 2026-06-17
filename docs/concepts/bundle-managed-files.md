# Bundle-managed files

> Files-as-SSOT redesign landed under `feat/bootstrap-dispatch`.
> See CHANGELOG `[Unreleased]` for the commit-by-commit narrative.

## Why this exists

Re-running `python -m scripts.bootstrap <project>` on an already-bootstrapped
consumer used to clobber `AGENTS.md`, `CLAUDE.md`, `.gitignore`,
`mcp-servers.project.yaml`, and other files that consumers had carefully
customised. `copy_templates` overwrote unconditionally.

This redesign moves the responsibility for those files from copy_templates to
a per-file render pipeline that preserves consumer content via **marker
blocks** (delimited canonical regions) plus an **ephemeral bundle JSON**
that carries free-form consumer content.

## Mental model

```
FILES = SSOT (each file is the authoritative source for its own content)
BUNDLE = ephemeral transfer format (UI ↔ apply_config)

  UI open               apply_config <bundle>
   │                          │
   ▼                          ▼
   parse(files) → bundle      bundle + templates → rendered files
   classify(sections)         backup_once(original)
   show in Files tab          atomic write
   user edits / curates       update file_states manifest
   export bundle              regenerate files-state.js
```

The bundle is NOT the canonical store. Re-opening the UI re-parses the
files. If the user edits `AGENTS.md` directly in their editor, the next
UI open reads those edits — no drift between bundle and file.

`<consumer>/.ai-playbook/applied-config.json` is an **audit trail** of
the last bundle applied, not the source of truth.

## Mode classification

| Mode | Behaviour | Files |
|---|---|---|
| **Canonical** | Section wrapped in `<!-- ai-playbook:begin id=... -->` marker. Overwritten on every apply with the new template content (after substitution + project_meta projection). | §0 / §2 / §5 / §6 of AGENTS.md, playbook-managed pre-commit hooks, .gitignore playbook patterns, mcp-servers.project.yaml hindsight baseline |
| **Custom** | Text OUTSIDE any marker block. Preserved verbatim across apply runs. | §1 / §3 / §4 / §7 / §8 of AGENTS.md, consumer .gitignore patterns, consumer pre-commit extras |
| **Drifted** | Inside a marker block, but the content SHA mismatches the manifest. Surfaced in the UI Files tab as a drift badge. Apply does NOT silently overwrite — the operator reviews + decides. | (any block whose content was edited locally) |
| **Seed-only** | Created once if missing; bootstrap / apply NEVER overwrites afterwards. | `.claude/settings.local.json` |

## Marker grammar

Three comment styles, one grammar:

```
HTML / markdown:
   <!-- ai-playbook:begin id=<slug> sha=<12hex> -->
   ...content...
   <!-- ai-playbook:end <slug> -->

shell / yaml / gitignore:
   # >>> ai-playbook:begin id=<slug> sha=<12hex> >>>
   ...content...
   # <<< ai-playbook:end <slug> <<<

JSON5 / JS:
   // ai-playbook:begin id=<slug> sha=<12hex>
   ...content...
   // ai-playbook:end <slug>
```

* `id` is a stable semantic slug from the template (e.g. `bootstrap-directive`).
* `sha` is the first 12 hex chars of SHA-256 of the canonical content
  (computed by `_template_classifier.compute_sha`). Optional in templates;
  filled by `render_agents_md` post-substitution.
* Block ids must be unique within a file. Nested blocks are NOT supported.

## End-to-end flow

> **One door.** Fresh install, `--update`, and `--check` all funnel through the
> same operation: `apply_config.apply` (the *reconcile* door). CHECK is
> `apply --dry-run`; REMEDY is `apply`. There is no second file-writing path.
> caveman activation, skills materialisation, and MCP render are ordered
> *sections* of the door (`SECTION_ORDER` in `scripts/apply_config.py`), not
> separate inline steps. `bootstrap` is just the *first reconcile* plus the
> one-time `git submodule add` precondition.

### Fresh install (`python -m scripts.bootstrap <project>`)

1. `copy_templates` copies the templates as before. Markers are baked in.
2. `reconcile(first_run=True)` synthesises the "everything ON" defaults bundle
   (all skills + MCP servers enforced; caveman and ponytail default-on with
   every component, omitted iff `--no-caveman` / `--no-ponytail`) and runs it
   through `apply_config.apply`. The
   synthesised bundle carries no managed-file trigger sections, so the
   freshly-copied templates are left untouched; caveman + ponytail activation +
   skills materialise + MCP render run as the door's sections.
3. The freshly-bootstrapped consumer has marker blocks visible in
   AGENTS.md / .gitignore / etc.

### Updating an existing consumer (`bootstrap --update`)

1. Locate `<consumer>/.ai-playbook/applied-config.json`. If missing, run
   `migrate_to_bundle` to extract consumer state into a bundle (parses
   AGENTS.md sections, .gitignore lines, mcp-servers.project.yaml entries,
   .claude/settings.local.json permissions).
2. `reconcile(first_run=False)` invokes `apply_config.apply` on the resolved
   bundle — the same door as fresh install. Per managed file:
   - Read template from `<playbook>/templates/new-project/<file>.tmpl`.
   - Compute substitutions from `<consumer>/AGENTS.md` frontmatter.
   - Run the renderer for that file.
   - If destination exists AND content differs from rendered output:
     `backup_once` → atomic write.
   - Update `bundle.file_states[<rel_path>]` with the new SHA manifest.
   The door also re-applies caveman / graphify / ponytail intent, re-materialises
   skills, and re-renders MCP configs as its own sections (idempotent).
3. Advisory drift check.

### Drift-CI gate (`bootstrap --check`)

1. `reconcile(first_run=False)` runs `apply_config.apply` in `--dry-run` mode
   against an existing consumer (resolving its `applied-config.json`, or
   synthesising defaults when none exists). Nothing is written.
2. The dry-run report IS the drift report; the command exits non-zero when any
   section differs from desired state.

### Curating via the UI

1. Open `config-ui/index.html` (double-click — `file://` works).
2. The `files-state.js` sidecar (built by `apply_config` or
   `python -m scripts.build_files_state`) populates the Files tab.
3. Each file's sections show with a badge: canonical (green), drifted
   (orange), custom (blue).
4. The right inspector shows previews + SHA info per section.
5. **v1 ships read-only.** Per-section curate is the deferred v3 scope
   (see follow-up below).
6. Restore from `.bak` dropdown surfaces every backup recorded in the
   index. Restore itself is CLI-only — `mv <consumer>/<rel_path>.bak <consumer>/<rel_path>`.

## Backup preferences

UI-configurable via `bundle.backup_preferences`:

```json
{
  "backup_preferences": {
    "location": "next",         // or "central"
    "with_timestamp": true,     // false ⇒ single-slot .bak
    "keep_per_file": 10
  }
}
```

* `location: "next"` (default): `<file>.<ISO>.bak` next to the source.
* `location: "central"`: `<consumer>/.ai-playbook-state/backups/<rel-path>.<ISO>.bak`.
* Discovery is location-agnostic via
  `<consumer>/.ai-playbook-state/backups/index.json` (a single registry
  records every backup with `rel_path`, `backup_rel_path`, `location`,
  `timestamp`, `sha256`, `source_size`, `session_id`).

## Caveman never-compress list (LLM safety)

Per the AI-expert roundtable, certain content MUST NEVER be caveman-compressed
regardless of the user's global toggle:

* Marker block ids: `bootstrap-directive`, `dispatcher-index`,
  `capability-map`, `mcp-sources` (AGENTS.md §0/§2/§5/§6). LLMs rely on
  precise imperative grammar + link table semantics here.
* `project_meta.hard_rules` — contains negations like "never", "must not",
  "do not". Caveman drops exactly those tokens.
* MCP server descriptions — default OFF, per-server opt-in only.

Authoritative module: [`scripts/caveman/policy.py`](../../scripts/caveman/policy.py).

## Uninstall

`python -m scripts.uninstall [--target PATH] [--dry-run]`:

1. Read `<consumer>/.ai-playbook-state/backups/index.json`.
2. For each managed file, restore the OLDEST `.bak` (pre-playbook snapshot).
3. For files without a pre-playbook `.bak`, strip marker blocks (keeping
   consumer custom segments verbatim).
4. `git submodule deinit -f .ai-playbook` + `git rm -f .ai-playbook`.
5. Remove `.ai-playbook-state/` (unless `--keep-state-dir`).

Pre-commit hooks in templates ship with graceful shims
(`bash -c '[ -d .ai-playbook ] && python ... || exit 0'`) so simply
deleting the submodule does NOT block commits.

## Follow-up scope (NOT in this PR)

- **v2 curate flow**: file-level "keep mine / take playbook / merge"
  buttons in the Files tab inspector. The roundtable PM recommended
  this over per-section checkboxes (200 checkboxes overwhelm).
- **v3 per-section curate**: granular checkboxes per drifted section.
  Defer until a real user explicitly demands it.
- **Workflow-level shims**: each `.github/workflows/*.yml.tmpl` could
  also receive an early-exit step when `.ai-playbook/` is absent. Today
  only pre-commit hooks have shims.
- **`.coderabbit.yaml` proper YAML merge**: today extras are appended as
  comments. A future iteration may parse + merge the YAML AST.
- **Schema migrations**: when the bundle schema changes (e.g.
  v0.20.0 introduces a new section), provide declarative migration
  scripts under `migrations/`.

## File index

| Purpose | Location |
|---|---|
| Backup helper + index registry | [scripts/_backup_helper.py](../../scripts/_backup_helper.py) |
| Marker block parser/writer | [scripts/_marker_blocks.py](../../scripts/_marker_blocks.py) |
| Classifier (canonical/drifted/custom) | [scripts/_template_classifier.py](../../scripts/_template_classifier.py) |
| Bundle schema | [schemas/schema-ai-playbook-config-v1.json](../../schemas/schema-ai-playbook-config-v1.json) |
| Per-file renderers | [scripts/_renderers/](../../scripts/_renderers/) |
| Apply orchestrator (managed files section) | [scripts/_managed_files.py](../../scripts/_managed_files.py) |
| Apply entrypoint | [scripts/apply_config.py](../../scripts/apply_config.py) |
| Migrate legacy state → bundle | [scripts/migrate_to_bundle.py](../../scripts/migrate_to_bundle.py) |
| Bootstrap update flag | [scripts/bootstrap.py](../../scripts/bootstrap.py) `--update` |
| Uninstall | [scripts/uninstall.py](../../scripts/uninstall.py) |
| UI files-state sidecar builder | [scripts/build_files_state.py](../../scripts/build_files_state.py) |
| UI Files tab | [config-ui/index.html](../../config-ui/index.html) + [app.js](../../config-ui/app.js) |
| Caveman never-compress policy | [scripts/caveman/policy.py](../../scripts/caveman/policy.py) |
