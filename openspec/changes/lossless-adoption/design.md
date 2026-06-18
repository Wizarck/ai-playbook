# Design — lossless-adoption

## Context

Verified surfaces (read at `scripts/` HEAD `14b0857`, v0.19.19):

- `scripts/_managed_files.py`
  - `_FRONTMATTER_RE = ^---\n(.*?)\n---` (DOTALL), `_KV_RE = ^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$`.
  - `_extract_agents_md_frontmatter` (L161-178) iterates frontmatter lines, applies
    `_KV_RE` to each. A YAML list value spans the key line (empty capture) plus
    `-` continuation lines (no capture) → the key resolves to `""`.
  - `compute_substitutions` (L181-195) L194:
    `"PLAYBOOK_PIN": fm.get("inherits_from", "").split("@")[-1] if fm.get("inherits_from") else ""`.
  - `MANAGED_FILES` (L76+) registers `AGENTS.md` with `renderer=render_agents_md`;
    the apply path passes `current_text` to the renderer.
- `scripts/_renderers/agents_md.py`
  - `render()` = `_apply_substitutions` → `_apply_project_meta` → `_apply_curate_intents`
    → `_inject_sha_into_markers`. The template is the authoritative base.
  - `_apply_curate_intents` only overrides blocks that exist in BOTH rendered and
    `current_text`. A markerless `current_text` yields zero overrides → the
    template body wins → consumer prose outside markers is dropped.
- `scripts/_renderers/_wrap_legacy.py` — `seed_markers(current_text, template)`:
  additively appends template blocks ABSENT from `current_text`, preserves all
  prose byte-for-byte, idempotent. `grep` confirms it is imported **nowhere** in
  `scripts/` → dead code.
- `scripts/_backup_helper.py` — `backup_once` / `restore_session` /
  `.ai-playbook-state/backups/index.json`; fully generic over file path; already
  invoked by the managed-files COMMIT phase for any existing file.

## Constraints

- **C1 — Don't break the template-regeneration contract.** `render_agents_md`
  regenerates `AGENTS.md` from the template + `project_meta`; `test_managed_files`
  / `test_renderers` encode this. Slice A must not change the render base (the
  rejected `seed_markers` wrap violated this — see D2).
- **C2 — Idempotent.** A second `bootstrap --update` with the same inputs is a
  no-op (pin parsing must be stable, no pin churn).
- **C3 — No regression on the inline-scalar pin.** Consumers that write
  `inherits_from: github.com/...@vX` on one line must keep working.
- **C4 — Touch only `compute_substitutions` / `_extract_agents_md_frontmatter`.**
  No change to the STAGE/COMMIT transaction, the render base, or the conflict gate.
- **C5 — Python 3.11 + 3.12, ruff-clean, stdlib-only** (no YAML dependency added
  just to parse one frontmatter key).
- **C6 — Additive, no consumer-facing removal** → no zombies-manifest entry for
  Slice A.

## Goals / Non-Goals

- **Goal:** the `inherits_from` pin is recovered from list OR scalar frontmatter,
  so `bootstrap --update` never blanks a template-shaped consumer's pin.
- **Goal:** an unparseable/pinless `inherits_from` is surfaced loudly, not silent.
- **Non-goal (Slice A):** preserving markerless hand-authored *content* in place
  (Slice C, via backup + curate) — and absorbing CLAUDE.md / MCP (Slices C / B).
- **Non-goal:** a general YAML parser — parse only the one multi-line key we need.

## Decisions

### D1 — Fix `inherits_from` parsing in-place, two-shape aware

Extend `_extract_agents_md_frontmatter` to recognise a list value: when a key line
matches `_KV_RE` with an empty value, look ahead at subsequent lines; while they
match `_LIST_ITEM_RE = ^\s*-\s*(.+?)\s*$`, collect them. Store the **`@`-bearing
item** if any (the pinned ref), else the first item. Scalars keep current
behaviour. `compute_substitutions` then derives `PLAYBOOK_PIN` only when the value
contains `@` (`split("@")[-1]`), so a non-pin value yields an empty pin instead of
echoing the whole string.

- **Why not add PyYAML?** stdlib-only constraint (C5); the frontmatter we parse is
  a tiny, well-known shape. A short look-ahead is cheaper and dependency-free.
- **Why prefer the `@`-bearing item?** A multi-entry `inherits_from` (e.g. a
  project spec plus the playbook pin) must still resolve the playbook pin
  regardless of list order; the pin is the entry carrying `...@vX.Y.Z`.
- **D1b — defensive empty-pin warning.** If `inherits_from` is present in the
  frontmatter but no pin resolves, emit a single advisory stderr `warning:` (not
  the `❌` error shape — this does not block) so a future frontmatter-shape
  regression is loud, not silent.

### D2 — Markerless content is an extraction/curate concern, NOT a renderer wrap

A `seed_markers(current_text, template)` wrap inside `render_agents_md` was
prototyped and **rejected**. `render` is template-authoritative: it computes the
output from the template, fills unmarked sections from `bundle.project_meta`, and
uses `current_text` only for `keep_mine` block overrides. The wrap is lossless on
the FIRST apply (consumer prose preserved as custom segments) but on the SECOND
apply `current_text` now has markers, so the render base reverts to the bare
template and the prose is regenerated away. Empirically this broke
`test_agents_md_idempotent_no_backup_no_write` and
`test_agents_md_rendered_when_project_meta_present` (which encode the
template-regeneration contract). The renderer is the wrong layer.

The architecture's lossless path for unmarked content is **extraction**:
`migrate_to_bundle.build_bundle` pulls the consumer's §1/§3/§4/§7/§8 prose out of
the existing `AGENTS.md` into `project_meta`, and the re-render refills it. A
hand-authored markerless file whose structure the deterministic extractor cannot
parse is exactly the fuzzy case the human-gated `curate.py` (LLM) already handles.

**Decision:** Slice A ships the deterministic D1 pin fix only. Markerless
`AGENTS.md` content preservation is folded into Slice C alongside CLAUDE.md: back
up the file before the managed render regenerates it (the COMMIT phase already
calls `backup_once` on existing files, so the original is recoverable today), and
point the operator at `curate` to absorb the backed-up prose into `project_meta`
→ `AGENTS.md` sections. No renderer change; no `seed_markers` wiring.
`scripts/_renderers/_wrap_legacy.py` (`seed_markers`) stays unused for now; it is
NOT wired by this change.

### D3 — Slice ordering

Ship A alone first: it is a live-regression fix with the smallest blast radius
(two functions + tests, no new files, no doc-drift pairs). B and C are additive
adoption features with their own test surface and docs; sequencing them after A
keeps each PR reviewable and each release independently revertable. (User-approved
sequencing.)

### D4 — Slice C reuses `curate.py`, no new classifier

`copy_templates` backs up a pre-existing `CLAUDE.md` via `backup_once` before
overwriting, then prints a pointer to `python -m scripts.curate` (the existing
human-gated LLM consolidation that already maps CLAUDE.md prose → AGENTS.md
§1/§4/§8). Rationale: a deterministic prose classifier was assessed as
"inherently imperfect"; reusing the gated path is lossless (backup) AND organised
(curate) without new fragile heuristics. (User-approved.)

### D5 — Slice B classifies, never clobbers

The absorb step writes to layer files only when the server id is not already
present there (de-dupe by id, prefer existing). Classification: id equal to a base
template key → project (override); id matching `<base-id>-<tenant-slug>` → personal;
id unique to the consumer → project. Every absorbed server gets an explicit
`scope` so the validator's `scope:personal` rule is satisfied. Audit trail always
printed; `--dry-run` previews. (User-approved: auto-classify + audit + idempotent.)

## Risks

- **R1 — list look-ahead mis-parses an edge frontmatter** (e.g. a multi-line
  scalar). Mitigation: only treat as a list when the continuation line matches
  `_LIST_ITEM_RE` exactly; otherwise fall back to the empty scalar (current
  behaviour). Covered by tests for list, scalar, multi-item, and pinless shapes.
- **R2 — the stricter pin derivation (`@`-required) changes behaviour for a value
  with no `@`.** Previously `split("@")[-1]` echoed the whole string; now it yields
  an empty pin (plus the D1b warning). This is intended (a pinless `inherits_from`
  was never a valid pin) and is covered by the unparseable-pin test.
- **R3 — markerless content still regenerates to template on update.** Out of
  scope for Slice A by decision D2; the original is backed up (recoverable) and the
  durable fix lands in Slice C (backup + curate). Documented in the upgrade runbook
  when Slice C ships.
