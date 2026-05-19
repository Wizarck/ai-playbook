# proposal — `single-source-skills-reset`

> **Status**: draft (slice `feat/single-source-skills-reset`).
> **Wave**: ai-playbook v0.17.0 candidate (BREAKING — schema field drop).
> **Authored**: 2026-05-19.
> **Plan**: vamos-a-identificar-los-elegant-marshmallow v9 §"Slice 3".

## Problem

RFC-0001 (skills distribution, accepted 2026-04-26) introduced a **multi-source**
skills pattern: each consumer declared `skills_sources: [<owner>/<repo>@<tag>, ...]`
in AGENTS.md frontmatter, the materialiser added each source as a sparse-checkout
git submodule under `.skills-sources/<repo>/`, merged them into `<consumer>/skills/`,
and regenerated per-LLM mirrors at `.claude/skills/` and `.gemini/skills/`.

That architecture cost — measured against the use-case it serves — is wrong:

- **2 git submodules** per consumer (`.ai-playbook/` + `.skills-sources/<source>/`).
- **3 scripts** (`_skills_materialiser.py`, `propagate_skills_bump.py`, `validate_skills_mirror.py`).
- **1 workflow** (`propagate-skills-bump.yml`, with both `push` + `repository_dispatch` triggers).
- **1 pre-commit guard** (`validate-skills-mirror`) on every consumer.
- **2 frontmatter fields** (`skills_sources` in AGENTS.md, `skills_pins` in `consumers.yaml`).

Cost paid for a feature that **nobody uses**. The sole consumer (Arturo's 5 sister
repos) consumes exactly one skills source: the playbook itself. `consumer-d-skills`
exists as a source but no consumer pins it independently — every active consumer's
`skills_pins` lists the same `ai-playbook` + `consumer-d-skills` tags as a quasi-duplicate
of `inherits_from`. Multi-source has zero in-flight use cases.

Worse, **consumer-a already deviated** locally (PR #125, 2026-05-18): a single-source
`scripts/sync_skills_local.py` reads directly from `.ai-playbook/skills/` and
writes the same three mirrors. The pattern is simpler, works, and ships in
production. The upstream playbook still carries the multi-source machinery
nobody touches.

## Proposed change

**Drop the RFC-0001 multi-source pattern entirely.** Promote consumer-a's local
pattern upstream. One source (`.ai-playbook/skills/`), three mirror destinations
(`skills/`, `.claude/skills/`, `.gemini/skills/`), all gitignored at consumer
side. Idempotent materialiser, no submodule logic, no propagation workflow.

Architectural decisions driving this slice:

- **D1** Single-source skills (no multi-source, no `skills_sources:` frontmatter)
- **D2** Scripts not mirrored (hooks invoke direct path `.ai-playbook/scripts/...`)
- **D17** Skills perpendicular Rules (one-way arrow: skills MAY depend on rules; rules MUST NOT depend on skills)
- **D19** Versioning: free use v0.16.x to v0.19.x; final v0.20.0

See `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow-decisions.md`
for the full decision rationale.

## Deliverables

### Deletions

- `scripts/propagate_skills_bump.py` + `tests/test_propagate_skills_bump.py`
- `scripts/validate_skills_mirror.py` + `tests/test_validate_skills_mirror.py`
- `tests/test_skills_materialiser.py` (replaced by `tests/test_materialise_skills.py`)
- `.github/workflows/propagate-skills-bump.yml`
- `rfcs/RFC-0001-skills-distribution.md` + `rfcs/README.md` (entire `rfcs/` folder)
- `validate-skills-mirror` entry in `.pre-commit-hooks.yaml` + `.pre-commit-config.yaml`

### Rewrites

- `scripts/_skills_materialiser.py` to `scripts/materialise_skills.py` — single-source
  only. Reads from `.ai-playbook/skills/`, writes the three mirrors. Idempotent.
  Removes orphans. No `skills_sources:` frontmatter parsing, no `.skills-sources/`
  submodule logic.
- `docs/concepts/skills-distribution.md` — full rewrite reflecting single-source design.
  References D1 + D2 + D17 explicitly.

### Edits

- `schemas/schema-agents-md-v1.json` (currently at `specs/agents-md-v1.schema.json` —
  `git mv` to canonical top-level path as slice 3.5 prep). Drops `skills_sources`
  and `skills_pins` properties from the v1 schema. `additionalProperties: true`
  means older consumers carrying these fields stay valid but the canonical schema
  no longer documents them.
- `scripts/bootstrap.py` — update import from `_skills_materialiser` to
  `materialise_skills`; drop the `--refresh-skills` AGENTS.md frontmatter check
  (single-source no longer reads frontmatter).
- `specs/zombies-manifest.yaml` — extend with **8 v2 entries** (see Design).

### Additions

- `scripts/gemini_start.py` — Gemini CLI wrapper ported from consumer-a
  (`c:/Projects/consumer-a/.ai-playbook/scripts/gemini_start.py`). Adapted for upstream
  context (no `consumer-a` hard-codes; `--bank-id` becomes optional via env).
- `templates/new-project/scripts/gemini_start.py.tmpl` — bootstrap template.
- `templates/new-project/scripts/install-playbook-hooks.sh.tmpl` — bash installer
  that points `core.hooksPath` at `scripts/git-hooks/` and runs the first skills
  sync. Replaces consumer-a's `install-skills-hooks.sh`.
- `tests/test_materialise_skills.py` — at least 10 tests covering fresh consumer,
  idempotency, orphan removal, mirror parity (Claude + Gemini).

### Release

- `VERSION`: 0.15.0 to 0.17.0 (Slice 2 lands v0.16.0 between this PR and the
  current main; if Slice 3 lands first the user merges Slice 2 and that branch
  rebases. Target is v0.17.0 regardless of merge order.)
- `CHANGELOG.md` v0.17.0 BREAKING entry with a migration table.

## File-ownership note

Concurrent with Slice 2 (Agent A, `feat/doc-drift-enforcement`, v0.16.0).
Ownership matrix: this slice OWNS `scripts/materialise_skills.py`, `rfcs/*` deletions,
schema edits, `scripts/gemini_start.py`; SHARED (first-lander wins, second rebases):
`CHANGELOG.md`, `VERSION`. DO NOT TOUCH: `scripts/check_doc_drift.py`,
`specs/co-edit-pairs.yaml`.

## Non-goals

This slice does NOT:

- Add new skill files (skills inventory unchanged).
- Re-shape `consumers.yaml` (`skills_pins` lingers harmlessly; cleanup is advisory
  via zombies-manifest Tier 3).
- Touch the per-LLM mirror format (still byte-identical copies).
- Cover slice 3.5 root-folder audit decisions (`FEEDBACK.md` keep/delete,
  `pricing.yaml` move, etc.) — those run sequential after slices 2+3 merge.
