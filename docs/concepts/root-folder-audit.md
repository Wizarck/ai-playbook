# Root folder audit (v0.17.1)

Critical-eye review of every file at the playbook repo root as of
2026-05-19, before the v0.20.0 architectural reset enters slice 4
(filesystem reorg). For each file: **KEEP**, **DELETE**, or **MOVE**, with
a one-line rationale.

Companion to slice 3.5 of
`~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md`. Per
decision **D19** the cut version is v0.17.1 (additive patch — no breaking
changes for consumers, just zombie-manifest entries so they self-clean on
the next bump).

## Acceptance baseline

- Every visible file at `c:/Projects/ai-playbook/` root is accounted for.
- Every `.github/workflows/*.yml` is accounted for.
- Each MOVE updates internal script + test references.
- Each DELETE that ever shipped to a consumer gets a zombie-manifest entry.
- Each KEEP carries an explicit reason (so the next audit starts from a
  known baseline, not a hunch).

## Files at root

| File | Current purpose | Decision | Rationale |
|---|---|---|---|
| `pyproject.toml` | PEP 621 packaging metadata; enables `pip install -e .` | **KEEP** | Non-negotiable. Scripts import as Python modules; pre-commit needs the package layout. |
| `.pre-commit-config.yaml` | Pre-commit hooks for the playbook itself | **KEEP** | Standard Python hygiene; keeps playbook code clean (ruff/black/schema lint). |
| `.pre-commit-hooks.yaml` | Hooks exported to downstream consumers via `repo: <ai-playbook>` | **KEEP** | Slice 3 cleaned the file (empty list now); slice 4 adds canonical L1+L2+L3 paired hooks. |
| `.gitignore` | Standard git ignore | **KEEP** | `*.egg-info/` already covered; no edits needed in slice 3.5. |
| `.gitattributes` | LF normalization across OSes | **KEEP** | Cross-platform team hygiene. |
| `AGENTS.md` | Primary dispatcher (sec 0 bootstrap directive) | **KEEP** | Core dispatcher. Slice 4 enforces 500-line cap (D14). |
| `README.md` | Public-facing readme | **KEEP** | Slice 7 rewrites it for v0.20.0 showcase. |
| `VERSION` | Authoritative semver tag | **KEEP** | Required. Bumped to `0.17.1` in this slice. |
| `CHANGELOG.md` | Release history | **KEEP** | Required. Slice 3.5 adds the `## [0.17.1]` entry. |
| `MAINTAINERS.md` | Single maintainer + escalation contact | **KEEP** | 15 lines; legitimate root metadata; slice 5 refreshes the obsolete `rfcs/` and `docs/contributing.md` references in passing. |
| `mkdocs.yml` | MkDocs static site generator config | **KEEP** | Drives `docs/` → GitHub Pages; slice 7 polishes theme/search/navigation. |
| `consumers.yaml` | Org-level registry of downstream consumers | **KEEP** | Consumed by `.github/workflows/propagate-playbook-bump.yml`; load-bearing. Stale `skills_pins:` keys already flagged by zombie entry `skills-pins-consumers-yaml` (slice 3, v0.17.0). |
| `FEEDBACK.md` | Append-only gripe log for multi-contributor triage | **DELETE** | Sole consumer reality (Arturo only); never triaged; dead infrastructure. Error messages in `scripts/mcp/render.py` + `scripts/mcp/validate.py` that point here are rewritten to "open a GitHub issue". |
| `mcp-servers-base.yaml` | Base layer of the 3-layer MCP merge (base + project + personal) | **MOVE** → `templates/rendered/mcp-servers-base.yaml.tmpl` | It is conceptually a **template** that consumers extend; belongs with the other rendered templates. References in `scripts/mcp/validate.py`, `scripts/mcp/render.py`, `scripts/init_org.py`, `tests/test_init_org.py`, `tests/test_mcp_render.py`, `tests/test_mcp_validate.py` updated. |
| `pricing.yaml` | Pricing catalog read by `scripts/cost_report.py` | **MOVE** → `configs/pricing.yaml` | Conceptually the same shape as `configs/anthropic-retirement-list.yaml` — runtime config data driving a standalone CLI. References in `scripts/cost_report.py` + `tests/test_cost_report.py` updated. Slice 6 (v0.19.1) will continue to load from this location. |
| `ai_playbook.egg-info/` (folder) | `pip install -e .` build artefact | **DELETE** (physical only) | `.gitignore` already covers `*.egg-info/`; the directory is untracked. Removing on-disk; regenerates on next install. Consumer-side zombie entry covers the rare case it was committed by a pre-gitignore install. |

## Files NOT at root that the ledger explicitly notes

| Folder | Status | Note |
|---|---|---|
| `.ai-playbook/` | gitignored | Runtime state (`hindsight-queue.jsonl`, `notifications.jsonl`, `overrides.log`). Not in git. |
| `.claude/` | gitignored worktree state | `.claude/worktrees/` holds two locked agent worktrees from slices 2+3 — leave alone. |
| `.pytest_cache/`, `.ruff_cache/` | gitignored | Cache. |
| `runbooks/` (15 files) | **KEEP for now** | Slice 4 moves to `docs/runbooks/`. Doing it in slice 3.5 would expand scope (17 moves + ~30 cross-ref rewrites). |
| `configs/`, `docs/`, `openspec/`, `schemas/`, `scripts/`, `skills/`, `specs/`, `templates/`, `tests/` | **KEEP** | Top-level folders. Slice 4 reorganises their internals; structural decisions out of scope for slice 3.5. |

## Workflows at `.github/workflows/`

| Workflow | Decision | Rationale |
|---|---|---|
| `branch-name-validator.yml` | **KEEP** | Required gate enforcing `feat/<openspec-change-dir>` convention. |
| `check-tasks-checkboxes.yml` | **KEEP** | PR check that all `tasks.md` boxes are ticked before merge. |
| `doc-drift-check.yml` | **KEEP** | Slice 2 (v0.16.0) gate enforcing co-edit pairs. |
| `docs-deploy.yml` | **KEEP** | MkDocs → GitHub Pages deployment; slice 7 (v0.19.2) leans on it. |
| `drift-check.yml` | **KEEP** | Existing drift CI on specs vs code. |
| `issue-sync.yml` | **DELETE** | Multi-tenant Jira/GH-Issues fanout per merged `openspec/changes/**/proposal.md`. Sole consumer does not use it. Underlying `scripts/issue_sync.py` not deleted (slice 6 may absorb). |
| `pr-merge-style.yml` | **KEEP** | CodeRabbit fallback advisor. |
| `propagate-playbook-bump.yml` | **KEEP** | Auto-opens "bump playbook pin" PRs across the 5 consumer repos when a new tag is cut. Critical for v0.20.0 propagation. |
| `release.yml` | **KEEP** | Operational release stub. Slice 4 may rename for consistency. |
| `test.yml` | **KEEP** | Required pytest gate (3.11 + 3.12). |

Slice 3 already deleted `.github/workflows/propagate-skills-bump.yml`; no
ledger row needed (file no longer exists).

## Slice 3.5 result (target)

After the decisions apply:

- Root file count visible to `ls`: ≤12 (was 16 + 1 untracked dir).
- All KEEP files unchanged in place.
- Two MOVEs preserve history via `git mv`.
- Three DELETEs (one untracked) with matching zombie-manifest entries.
- VERSION = `0.17.1`; CHANGELOG `## [0.17.1]` entry citing this ledger.
