# tasks — `single-source-skills-reset`

> Implementation checklist for slice 3 of the ai-playbook architectural reset
> (v0.15.0 to v0.20.0 plan, v9). Per-acceptance criteria are mirrored from
> `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md` §"Slice 3".

## owns write_paths

- `scripts/materialise_skills.py`
- `scripts/_skills_materialiser.py`
- `scripts/propagate_skills_bump.py`
- `scripts/validate_skills_mirror.py`
- `scripts/gemini_start.py`
- `scripts/bootstrap.py`
- `tests/test_materialise_skills.py`
- `tests/test_skills_materialiser.py`
- `tests/test_propagate_skills_bump.py`
- `tests/test_validate_skills_mirror.py`
- `.github/workflows/propagate-skills-bump.yml`
- `schemas/schema-agents-md-v1.json`
- `specs/agents-md-v1.schema.json`
- `specs/skills-distribution.md`
- `specs/zombies-manifest.yaml`
- `.pre-commit-hooks.yaml`
- `.pre-commit-config.yaml`
- `rfcs/RFC-0001-skills-distribution.md`
- `rfcs/README.md`
- `templates/new-project/scripts/gemini_start.py.tmpl`
- `templates/new-project/scripts/install-playbook-hooks.sh.tmpl`
- `VERSION`
- `CHANGELOG.md`

## Deletions (use `git rm`)

- [ ] `scripts/propagate_skills_bump.py`
- [ ] `scripts/validate_skills_mirror.py`
- [ ] `tests/test_propagate_skills_bump.py`
- [ ] `tests/test_validate_skills_mirror.py`
- [ ] `tests/test_skills_materialiser.py` (replaced by `tests/test_materialise_skills.py`)
- [ ] `.github/workflows/propagate-skills-bump.yml`
- [ ] `rfcs/RFC-0001-skills-distribution.md`
- [ ] `rfcs/README.md`
- [ ] `rfcs/` folder itself (no other files remain)

## Rewrites

- [ ] Rename `scripts/_skills_materialiser.py` to `scripts/materialise_skills.py` (single-source-only).
  Reads `.ai-playbook/skills/`, writes `skills/`, `.claude/skills/`, `.gemini/skills/`.
  Idempotent (fingerprint hashes detect no-op). Removes orphan skills.
  No `skills_sources:` frontmatter parsing, no submodule logic.
- [ ] Rewrite `specs/skills-distribution.md` to reflect single-source design (cite D1, D2, D17).

## Edits

- [ ] `git mv specs/agents-md-v1.schema.json schemas/schema-agents-md-v1.json` (slice 3.5 prep).
  Drop the `skills_sources` and `skills_pins` properties from the v1 schema.
- [ ] `scripts/bootstrap.py` — update import to `materialise_skills`; drop AGENTS.md
  frontmatter-driven path inside `--refresh-skills`.
- [ ] `.pre-commit-hooks.yaml` — drop the `validate-skills-mirror` entry; document
  the new sync workflow.
- [ ] `.pre-commit-config.yaml` — drop the local `validate-skills-mirror` hook entry.
- [ ] `specs/zombies-manifest.yaml` — extend with **8 v2 entries**:
  - [ ] `propagate-skills-bump-script` (Tier 3 advisory)
  - [ ] `validate-skills-mirror-script` (Tier 3 advisory)
  - [ ] `propagate-skills-bump-workflow` (Tier 3 advisory)
  - [ ] `rfcs-folder-removed` (Tier 3 advisory)
  - [ ] `skills-sources-submodule-v2` (Tier 1 safe-delete; tightens existing entry)
  - [ ] `skills-sources-frontmatter` (Tier 3 advisory; expands existing entry)
  - [ ] `skills-pins-consumers-yaml` (Tier 3 advisory)
  - [ ] `validate-skills-mirror-precommit-hook` (Tier 3 advisory)
  - [ ] Bump `manifest_version` to `2026-05-19.2`.

## Additions

- [ ] `scripts/gemini_start.py` — Gemini CLI wrapper (port from consumer-a, upstream-adapted).
- [ ] `templates/new-project/scripts/gemini_start.py.tmpl` — bootstrap template.
- [ ] `templates/new-project/scripts/install-playbook-hooks.sh.tmpl` — bash installer.
- [ ] `tests/test_materialise_skills.py` — at least 10 tests:
  1. fresh consumer with no targets yet
  2. idempotency: second run is a no-op (fingerprint hash unchanged)
  3. orphan removal: skill removed from source disappears from all mirrors
  4. mirror parity Claude vs Gemini (byte-identical after run)
  5. dry-run prints planned writes, touches no FS
  6. source missing exits non-zero with canonical error shape
  7. partial mirror (only `.claude/skills/` exists) regenerates the others
  8. nested skill assets (subdirectories under SKILL.md) copy correctly
  9. quiet mode suppresses stdout
  10. `--source` override accepts an arbitrary path

## Release

- [ ] Bump `VERSION` to 0.17.0
- [ ] `CHANGELOG.md` v0.17.0 BREAKING entry with migration table

## Validation

- [ ] `pytest tests/` green
- [ ] `python scripts/cleanup_zombies.py validate` exits 0 with 18 entries
- [ ] `python scripts/materialise_skills.py --dry-run` on a fresh tmp dir runs idempotent
- [ ] No new Spanish strings in `docs/`, `schemas/`, `templates/`, `tests/`, `.github/workflows/`, `AGENTS.md`, `README.md`, `CHANGELOG.md`
- [ ] `pre-commit run --all-files` green (or document pre-existing failures)
