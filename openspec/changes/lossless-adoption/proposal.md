## Why

Adopting the playbook must never cost the consumer their existing content. Today
three adoption surfaces silently lose or mangle pre-existing consumer state:

- **Markerless `AGENTS.md` is overwritten (the bug that already bit us).**
  `render_agents_md` is template-authoritative: it regenerates unmarked sections
  from the template + `bundle.project_meta`. When a consumer's `AGENTS.md` is
  hand-authored *without* `ai-playbook:` markers and its content is not captured
  in `project_meta`, `bootstrap.py --update` regenerates the template over it and
  §1/§7/§8 prose is replaced by TODO defaults (the original is backed up via
  `backup_once`, so it is recoverable, not in-place lossless). The architecture's
  lossless path for unmarked content is **extraction** (`migrate_to_bundle` →
  `project_meta` → re-render), not file-prose preservation — so the durable fix
  lives in the extraction / human-gated `curate` layer, **not** the renderer
  (Design D2). This is the deferral called out by
  `bootstrap-direct-invoke-and-markerless-guard`.

- **The `inherits_from` pin is blanked.** `_extract_agents_md_frontmatter`
  (`scripts/_managed_files.py`) parses frontmatter line-by-line with
  `_KV_RE = ^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$`. The template's own frontmatter
  writes `inherits_from` as a YAML **list** (`inherits_from:` then
  `  - github.com/...@vX.Y.Z`). The `inherits_from:` line matches with an *empty*
  value; the `  - …@vX.Y.Z` continuation line never matches. So
  `compute_substitutions` sets `PLAYBOOK_PIN = ""` and the re-render emits a
  malformed, pinless `inherits_from`. Every template-shaped consumer is exposed.

- **Pre-existing MCP servers and CLAUDE.md prose are dropped.** A consumer
  adopting the playbook may already ship a hand-wired `.mcp.json` (inline servers)
  and a populated `CLAUDE.md` (project rules, gotchas). `scripts/mcp/render.py`
  renders base+project(+personal) over `.mcp.json`, clobbering inline servers that
  live in no layer. `bootstrap.copy_templates` overwrites a pre-existing
  `CLAUDE.md` with the thin-router template **without a backup**, and nothing
  re-injects its prose into `AGENTS.md`.

The throughline: *the consumer must lose nothing merely by adopting the
playbook.* The backup machinery to make adoption lossless already exists and is
generic (`_backup_helper.backup_once` / `restore_session`, the
`.ai-playbook-state/backups/index.json` index) — it is simply not wired to these
three surfaces.

## What Changes

Delivered as one capability, `lossless-adoption`, in three independently
shippable slices. Slice A ships first (it fixes a live regression); B and C
follow.

- **Slice A — frontmatter pin recovery (`AGENTS.md`).** Fix
  `_extract_agents_md_frontmatter` to parse `inherits_from` whether it is an inline
  scalar (`inherits_from: github.com/...@vX`) **or** a YAML list (key line + `-`
  items — the template's own shape, and a multi-item list prefers the `@`-bearing
  pin). `PLAYBOOK_PIN` is recovered from either; a single stderr warning fires when
  `inherits_from` is present but no pin resolves, so a future shape regression is
  loud, not silent. This fixes the pin-blanking half of the regression that bit
  gtm-advisor. Markerless hand-authored *content* preservation is deliberately NOT
  a renderer change (Design D2) — it routes through the extraction/`curate` layer
  in Slice C.

- **Slice B — MCP lossless absorb (auto-classify + audit + idempotent).** A
  pre-render absorb step in `scripts/mcp/render.py`: back up a pre-existing
  `.mcp.json` once, parse its `mcpServers`, classify each by the tenant-naming
  convention (`<server-type>-<tenant-slug>` → personal; project-unique → project;
  base-id override → project), append into the correct layer file (de-duped by
  id, never clobbering an existing layer entry), then render. An audit trail is
  always printed; `--dry-run` previews without writing.

- **Slice C — dispatcher-prose absorb (backup + curate, human-gated).** Covers
  both pre-existing `CLAUDE.md` AND hand-authored markerless `AGENTS.md`.
  `bootstrap.copy_templates` backs up a pre-existing `CLAUDE.md` (through
  `backup_once`, indexed) before writing the thin-router template; a markerless
  `AGENTS.md` is likewise backed up before the managed render regenerates it. Both
  surface a pointer to the existing human-gated `curate.py` pass that organises the
  backed-up prose into `AGENTS.md` §1/§4/§8. No new fragile classifier; reuses the
  trusted LLM-gated consolidation already in the repo. This is the
  architecture-respecting home for markerless content (the renderer stays
  template-authoritative; losslessness comes from prose → `project_meta`, not from
  preserving file prose in place).

## Capabilities

### New Capabilities

- `lossless-adoption`: adoption never destroys pre-existing consumer state.
  - **Slice A — frontmatter pin recovery**: `inherits_from` list/scalar parsing;
    pin never blanked; loud warning on an unparseable pin.
  - **Slice B — MCP absorb**: pre-render backup + classify + idempotent
    re-injection of pre-existing `.mcp.json` servers into project/personal layers.
  - **Slice C — dispatcher-prose absorb**: backup-before-overwrite (CLAUDE.md +
    markerless AGENTS.md) + curate pointer for organised re-injection of the
    backed-up prose into `AGENTS.md`.

### Modified Capabilities

- `reconcile` (from `reconcile-foundation`): unchanged behaviour. Slice A only
  hardens `compute_substitutions` (pin parsing) inside the existing STAGE path; no
  section-order, transaction, or render-base change.

## Impact

**Slice A (this PR):**

- `scripts/_managed_files.py` — `_extract_agents_md_frontmatter` parses list AND
  scalar `inherits_from`; `compute_substitutions` recovers the pin from either and
  warns once when an `inherits_from` is present but pinless.
- `tests/test_managed_files.py` — list-form pin recovered; inline-scalar pin
  regression; `@`-bearing item preferred in a multi-item list; unparseable-pin
  warning.

**Slice B (follow-up PR):** `scripts/mcp/render.py` (+ absorb helpers),
`scripts/mcp/tests/` fixtures, `docs/concepts/mcp-servers-schema.md` §10,
`docs/rules/mcp-render.rule.md`.

**Slice C (follow-up PR):** `scripts/bootstrap.py` (`copy_templates` backup of
pre-existing CLAUDE.md + markerless AGENTS.md), `docs/runbooks/onboard-new-project.md`
note, curate pointer.

**Read-only dependencies (no edits):** `scripts/_marker_blocks.py`
(`parse_blocks`/`write_blocks`), `scripts/_template_classifier.py` (`compute_sha`),
`scripts/_backup_helper.py` (`backup_once`/`restore_session` — already generic),
`scripts/curate.py` (reused by Slice C, not modified).

## Out of scope (later changes)

- A renderer-level wrap of markerless `AGENTS.md` (`seed_markers` inside
  `render`): rejected — `render_agents_md` is template-authoritative, so a wrap is
  lossless on the first apply but reverts to the template on the next (breaks
  `test_agents_md_idempotent`). Markerless content goes through Slice C instead.
- A deterministic (non-LLM) prose classifier — Slice C reuses the human-gated
  `curate.py` instead.
- Absorbing MCP servers declared inside `.claude/settings.json` — Slice B targets
  `.mcp.json` only; settings.json identity-merge is tracked elsewhere.
- The global `~/.claude/` → playbook/personal migration audit (separate
  workstream, not openspec).

## Release

Slice A → `VERSION` 0.19.20 (patch: frontmatter pin-parse bugfix, additive). Slices
B and C ship as their own minor/patch releases. Pull model.
