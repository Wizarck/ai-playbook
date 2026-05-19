# Design — root-folder-audit (v0.17.1)

## Goal

Reduce root visual noise to ≤12 files by deleting dead infrastructure and
relocating two files that have a better folder home. Every other root entry
keeps its current location; the ledger documents the rationale so future
audits start from a known baseline.

## Decisions per move

### `mcp-servers-base.yaml` → `templates/rendered/mcp-servers-base.yaml.tmpl`

`mcp-servers-base.yaml` is the **base layer** of the 3-layer MCP merge
(base + project + personal → rendered `.mcp.json` / `.gemini/settings.json`).
The other two layers live at the consumer side; the base layer is shipped by
the playbook to give consumers a starting catalogue of well-known MCP
servers.

Semantically it is a **template** that consumers extend, not a runtime
config. It belongs alongside the other rendered templates in
`templates/rendered/`. The `.tmpl` suffix signals to the bootstrap walker
that the file is materialised on the consumer side.

Loading code (`scripts/mcp/validate.py:resolve_playbook_root` and
`scripts/mcp/validate.py:load_layers`) updates its sentinel path. The merge
semantics do not change.

### `pricing.yaml` → `configs/pricing.yaml`

`pricing.yaml` is **runtime configuration data** read by
`scripts/cost_report.py` to compute USD estimates from `gen_ai.usage.*`
events. It is conceptually the same shape as
`configs/anthropic-retirement-list.yaml` (already in `configs/`): a YAML
data file that drives a standalone CLI.

Slice 6 (telemetry, v0.19.1) will absorb `cost_report.py` into
`scripts/telemetry/report.py`; the pricing data will still load from
`configs/pricing.yaml`. Moving now puts the file in its final home so the
telemetry slice ships without an additional move.

### `FEEDBACK.md` (DELETE)

Append-only gripe log designed for multi-contributor triage. Sole consumer
reality means no second author has ever appended. Every consumer-facing
spec / doc that references it is already obsolete material for slice 5
content rewrite. Removing the physical file now prevents new agents from
treating it as live infrastructure.

Error messages in `scripts/mcp/render.py` and `scripts/mcp/validate.py`
that say "report with full stacktrace to FEEDBACK.md" are rewritten to
point at a GitHub issue — the canonical sole-consumer channel.

### `ai_playbook.egg-info/` (DELETE physical, gitignore confirmed)

`.gitignore` already lists `*.egg-info/`. `git ls-files
ai_playbook.egg-info/` reports zero tracked entries — the directory was
created by an earlier `pip install -e .` and is purely build output. We
delete the on-disk directory (it regenerates on next install) and add an
explicit zombie entry so consumers that committed it pre-`*.egg-info/`-gate
get it cleaned up.

### `.github/workflows/issue-sync.yml` (DELETE)

The workflow opens Jira tickets or GH Issues for every merged
`openspec/changes/**/proposal.md`. Sole consumer does not use it — Jira
already covers the GPLO project end-to-end without this fanout. The
underlying `scripts/issue_sync.py` is **not** deleted here; slice 6 may
absorb it. Deleting only the workflow removes the GitHub-side trigger
surface.

## What stays at root and why

| File | Reason |
|---|---|
| `pyproject.toml` | PEP 621 packaging metadata; `pip install -e .` needs it at root. |
| `.pre-commit-config.yaml` | Pre-commit framework expects it at root. |
| `.pre-commit-hooks.yaml` | Pre-commit's published hooks for downstream `repo:` consumption — root is the canonical location. |
| `.gitignore` | Git convention. |
| `.gitattributes` | LF normalization; git convention. |
| `AGENTS.md` | Primary dispatcher (sec 0 bootstrap directive). |
| `README.md` | Public-facing readme. |
| `VERSION` | Authoritative semver tag. |
| `CHANGELOG.md` | Release history. |
| `MAINTAINERS.md` | Single-line maintainer table; legitimate at root. |
| `mkdocs.yml` | MkDocs convention; slice 7 polishes theme. |
| `consumers.yaml` | Consumed by `.github/workflows/propagate-playbook-bump.yml`; load-bearing. |
| `runbooks/` (folder) | Stays for slice 3.5; slice 4 moves to `docs/runbooks/`. |
| `configs/`, `docs/`, `openspec/`, `schemas/`, `scripts/`, `skills/`, `specs/`, `templates/`, `tests/` | Folders, not files; out of scope for slice 3.5. |

Hidden-but-essential dot-folders kept: `.github/` (workflows + tooling),
`.claude/` (worktree state, gitignored at `.claude/worktrees/`).

## Why not delete MAINTAINERS.md too

It references `rfcs/` (slice 3 deleted that folder) and
`docs/contributing.md` (TBD). Critical-eye says it's stale, but the file
itself is 15 lines and answers the question "who do I email if there's a
security issue?" — answer is non-trivial to find without it. Slice 5
rewrites docs and will refresh this in passing. **Decision: KEEP** with
a note in the ledger.

## Why not move runbooks/

Slice 4 moves `runbooks/*` → `docs/runbooks/*`. Doing it in slice 3.5
would require 17 file moves + ~30 cross-reference rewrites — fully in
slice 4's scope. Slice 3.5 stays surgical.
