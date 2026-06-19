> Legend: `[x]` done & verified · `[~]` done with a noted deviation · `[ ]` pending.
> Ship order: Slice A (1-2) first as its own release; Slices C (3) and B (4) follow.

## 1. Frontmatter pin parsing (slice A)

- [x] 1.1 Extend `_extract_agents_md_frontmatter` (`scripts/_managed_files.py`) to
  parse a YAML-list value: on an empty-value key line, look ahead while lines match
  `_LIST_ITEM_RE = ^\s*-\s*(.+?)\s*$`, collect items, store the `@`-bearing item
  (else first). Inline scalars unchanged.
- [x] 1.2 `compute_substitutions` derives `PLAYBOOK_PIN` only when the value carries
  `@` (`split("@")[-1]`), so a pinless value → empty pin; emit a single advisory
  `warning:` (not the `❌` error shape) when `inherits_from` is present but pinless (D1b).
- [x] 1.3 Tests: list-form pin recovered; inline-scalar pin still works (C3
  regression); `@`-bearing item preferred in a multi-item list; pinless `inherits_from`
  → empty pin + warning.

## 2. Slice A integration + ship

- [ ] 2.1 `uvx ruff check .` clean; `uv run --extra dev pytest -q` green (the
  template-regeneration tests in `test_managed_files`/`test_renderers` unchanged, C1).
- [ ] 2.2 Doc gates: this slice touches no co-edit-pair code → `[no-doc-impact]` in
  the PR title (no doc edit).
- [ ] 2.3 `VERSION` → 0.19.20; prepend CHANGELOG `## [0.19.20]` (Fixed: AGENTS.md
  `inherits_from` list-form pin blanked on re-render). Commit, PR, merge, tag, release.
- [ ] 2.4 Dogfood: re-pin gtm-advisor (hand-authored markerless AGENTS.md) through
  v0.19.20 and confirm `bootstrap --update` no longer blanks its pin.

## 3. Slice C — dispatcher-prose absorb (backup + curate) — v0.19.21

- [x] 3.1 In `scripts/bootstrap.py` `copy_templates` (first-run only; `--update`
  skips it), capture any pre-existing `dst` as a BASE snapshot via `backup_base`
  before the template overwrites it. DEVIATION: used `backup_base` (CENTRAL,
  session `base`, idempotent — never re-captures) covering ALL pre-existing files
  (CLAUDE.md, markerless AGENTS.md, GEMINI.md, configs), not just CLAUDE.md via
  `backup_once`. BASE is the true pre-playbook anchor with `restore_base` recovery.
- [x] 3.2 `_report_adoption_backups` prints the preserved files and, for dispatcher
  files, points at `python -m scripts.curate --dry-run` (then `--yes`).
- [x] 3.3 Tests (`test_bootstrap.py`): pre-existing CLAUDE.md → BASE captured +
  `restore_base` round-trips; fresh target captures none; capture idempotent;
  dry-run captures none. Note added to `docs/runbooks/onboard-new-project.md`.

## 4. Slice B — MCP absorb (auto personal / project-by-hand) — v0.19.22

- [x] 4.1 `scripts/mcp/absorb.py` (`absorb_mcp_json`): parse inline `.mcp.json`,
  classify each new server (`<base-id>-<tenant>` → personal; else project),
  AUTO-WRITE only tenant instances to the personal layer (de-dupe by id, env NAMES
  only — no secret values, backup + rollback-on-parse-fail), REPORT project
  candidates (NEVER auto-write the committed project layer), and back up the
  `.mcp.json` as a BASE snapshot. DEVIATION: safe-default per user decision — auto
  only to personal, project by hand (the original "auto-write both layers" could
  leak a personal server into the committed file). Separate module, not inline.
- [x] 4.2 CLI: `--absorb` opt-in flag in `render.py` (runs before load_layers so
  the absorbed personal servers are part of the render); audit trail printed;
  `--dry-run` previews without writing.
- [x] 4.3 Tests (`tests/test_mcp_absorb.py`, 8): tenant→personal, project→reported-
  not-written, env-names-not-values, idempotent, dry-run, no-clobber, classify,
  to_layer_entry. CLI smoke green. Doc note in `onboard-new-project.md` (schema-doc
  §10 deferred — its co-edit pair is `validate.py`, untouched here).
