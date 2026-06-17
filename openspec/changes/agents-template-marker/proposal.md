# agents-template-marker

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator (feat/fix `<change-id>` needs `openspec/changes/<id>/`).
> `openspec/changes/` is gitignored — force-added.

## Why

`templates/new-project/AGENTS.md.tmpl` carried a prose EXAMPLE marker
`<!-- ai-playbook:begin id=… -->` inside explanatory text. `parse_blocks`
matched it as a real (unclosed) marker, so `render_agents_md` raised
`marker mismatch: begin id='…', end id='bootstrap-directive'` — breaking
`bootstrap --update` managed_files for every consumer that renders AGENTS.md
(found by dogfooding the v0.19.15 upgrade flow on a real consumer).

## What

- Escape the prose example on `AGENTS.md.tmpl:23` (drop the `<!-- -->`
  delimiters so it is not parsed as a marker).
- Regression test: the shipped template renders + round-trips its 4 managed
  blocks without raising.

## Release

`VERSION` → 0.19.16. Patch (bugfix). Pull model.
