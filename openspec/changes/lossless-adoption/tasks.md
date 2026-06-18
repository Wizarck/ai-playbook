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

## 3. Slice C — dispatcher-prose absorb (backup + curate, follow-up release)

- [ ] 3.1 In `scripts/bootstrap.py` `copy_templates`, before writing
  `CLAUDE.md.tmpl`, if `<consumer>/CLAUDE.md` exists call `backup_once` (indexed)
  under the run's session id. Markerless `AGENTS.md` is already backed up by the
  COMMIT phase; assert + surface it.
- [ ] 3.2 Emit a pointer: "pre-existing CLAUDE.md / markerless AGENTS.md backed up
  → run `python -m scripts.curate` to absorb its prose into AGENTS.md §1/§4/§8."
- [ ] 3.3 Tests: pre-existing CLAUDE.md backed up + indexed before overwrite;
  restore round-trips. Note in `docs/runbooks/onboard-new-project.md`.

## 4. Slice B — MCP absorb (auto-classify + audit + idempotent, follow-up release)

- [ ] 4.1 `scripts/mcp/render.py`: pre-render `absorb_existing_mcp_json(consumer_root,
  dry_run)` — `backup_once_mcp_json`, `parse_mcp_json_servers`,
  `classify_server_layer` (base-key→project; `<base-id>-<tenant>`→personal;
  unique→project), `write_absorbed_servers_to_files` (de-dupe by id, add `scope`).
- [ ] 4.2 CLI: `--skip-absorption`, `--absorption-only`; audit trail in `_summary`;
  `--dry-run` previews without writing.
- [ ] 4.3 Tests + fixtures (existing `.mcp.json` with base-override, tenant-named,
  project-unique servers); idempotent re-run; docs `mcp-servers-schema.md` §10 +
  `mcp-render.rule.md` (co-edit pair if a rule doc is added).
