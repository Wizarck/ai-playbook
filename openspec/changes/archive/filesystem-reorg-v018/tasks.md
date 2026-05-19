# Tasks — filesystem-reorg-v018

Single PR with three sequential commit phases (4.A → 4.B → 4.C). Each phase is a set of logical commits, not separate PRs.

## Phase 4.A — `git mv` only (history preservation)

- [x] Move paired script files: `scripts/<name>.py` → `scripts/rules/<slug>.rule.py`
- [x] Move rule-style specs: `specs/<rule>.md` → `docs/rules/<slug>.rule.md`
- [x] Move concept-style specs: `specs/<reference>.md` → `docs/concepts/<slug>.md`
- [x] Move tutorial-style docs: `docs/<learning>.md` → `docs/tutorials/<numbered>.md`
- [x] Move runbooks: `runbooks/<recipe>.md` → `docs/runbooks/<slug>.md`
- [x] Move JSON schemas to top-level: `specs/*.schema.json` → `schemas/schema-*.json`
- [x] Rename paired workflows: `.github/workflows/<gate>.yml` → `.github/workflows/<slug>.rule.yml`
- [x] Each commit groups ≤30 files by category and ends with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

## Phase 4.B — cross-reference rewrites

- [x] Author `scripts/migrate_paths_v0.18.py` with static rename mapping
- [x] Run migration locally; verify no broken known paths
- [x] Commit the migration content changes (one commit)
- [x] Delete `scripts/migrate_paths_v0.18.py` (separate commit; CHANGELOG is the historical record)

## Phase 4.C — config updates + new tooling

- [x] Update `pyproject.toml` `[tool.setuptools.packages.find]` to include `scripts.rules`
- [x] Update `.pre-commit-config.yaml` paths if any reference moved files
- [x] Update `.pre-commit-hooks.yaml` with `validate-pairing` / `check-doc-language` / `check-link-integrity` / `check-agents-md-size` hooks
- [x] Aggregate workflows: rename existing gates `.github/workflows/<gate>.yml` → `.github/workflows/<slug>.rule.yml` for the paired ones; add 5 grouped rule-workflows
- [x] Add `scripts/validate_pairing.py` (meta-validator, eats own dogfood)
- [x] Add `scripts/validate_pairing_oracle.sh` (parallel shell tripwire)
- [x] Add `scripts/materialise_cursor_rules.py` (`.cursor/rules/*.mdc` generator)
- [x] Add `scripts/check_doc_language.py` (langdetect-based)
- [x] Add `scripts/check_link_integrity.py` (broken-link detector)
- [x] Add `scripts/hook_dispatcher.py` (single-process L1 dispatcher, ≤50ms SLA)
- [x] Add `scripts/gen_indexes.py` (auto-generates per-folder INDEX.md from frontmatter)  — already exists; verify
- [x] Add `scripts/check_agents_md_size.py` (fails when AGENTS.md > 500 lines)
- [x] Add `scripts/check_deprecated_rules.py` (warns at PR-time when touching `status: deprecated` rules)
- [x] Add `schemas/schema-rule-v1.json` (rule frontmatter; forbids fields that concept schema requires)
- [x] Add `schemas/schema-concept-v1.json` (concept frontmatter; disjoint from rule schema)
- [x] Add placeholder docs:
  - [x] `docs/concepts/enforcement-layers.md`
  - [x] `docs/concepts/cross-llm-activation.md`
  - [x] `docs/concepts/enforcement-pairing-exceptions.md`
  - [x] `docs/concepts/taxonomy.md` (move from specs/ if exists)
  - [x] `docs/concepts/STYLE.md`
  - [x] `docs/tutorials/01-architecture-tour.md`
- [x] Add tests:
  - [x] `tests/test_validate_pairing.py` (30+ drift fixtures)
  - [x] `tests/test_hook_latency.py` (≤50ms SLA enforcer)
  - [x] `tests/test_check_doc_language.py`
  - [x] `tests/test_check_link_integrity.py`
- [x] Extend `specs/zombies-manifest.yaml` with v4 path-migration entries; bump `manifest_version`
- [x] Bump `VERSION` 0.17.1 → 0.18.0
- [x] Append `CHANGELOG.md` v0.18.0 BREAKING entry with full migration table

## Validation

- [x] `pytest tests/` — green (846+ baseline + new tests; 2 e2e env-gated skips OK)
- [x] `python scripts/validate_pairing.py` → exit 0
- [x] `python scripts/check_link_integrity.py docs/` → exit 0
- [x] `python scripts/check_agents_md_size.py` → exit 0 (AGENTS.md ≤ 500 lines)
- [x] `python scripts/check_doc_language.py docs/` → exit 0
- [x] `python scripts/cleanup_zombies.py validate` → exit 0 (v4 entries valid)
- [x] `pip install -e .` succeeds in a fresh venv
- [x] `pre-commit run --all-files` — green or pre-existing failures documented

## PR

- [x] Push branch `feat/filesystem-reorg-v018`
- [x] Open PR with title `feat(v0.18.0)!: filesystem reorg + paired enforcement tooling [no-doc-impact]`
- [x] PR body includes: Summary, BREAKING changes (migration table), Sub-phases delivered, New tooling, Deferred to Slice 5, Test plan, Versioning note
