# anti-drift-gates

> **Status**: SCRATCH. Satisfies branch-name-validator. openspec/changes/ gitignored — force-added.

## Why

2026-07-13 geeplo incident (representative of a recurring class across consumers):
a feature wave merged with 41 ruff errors (CI lint step red, merged anyway — no
branch protection on free-plan private repos) and two migrations (`0070`, `0072`)
that added NOT NULL columns the e2e seed script never learned about. Backend CI
died at lint before pytest; Playwright died at DB bootstrap before any test.
Both signals existed in CI the moment they were born; nothing made them gate,
and nothing caught them earlier (pre-commit does not run ruff; no CI job
exercises the migrate→seed contract).

## What

- New concept `docs/concepts/anti-drift-gates.md` — the defense-in-depth model
  (laptop → PR CI → merge lock → continuous), the breakage-class → layer map,
  and ratchet-baseline guidance (block growth + lower-on-improvement).
- New rule `lint-parity-precommit` (md + hardrule + tests): linters that gate CI
  must also run at pre-commit with the same pin; `apply` appends the
  ruff-pre-commit block with the CI-detected pin.
- New rule `migrate-seed-smoke` (md + hardrule + tests, validate-only): repos
  with alembic migrations AND a DB seed script must have a CI job applying
  migrations to a fresh DB and running the seed twice; template at
  `templates/ci/migrate-seed-smoke.yml`.
- Regenerated rule indexes / enforce inventories.

## Release

`VERSION` → 0.19.28. Minor feature (2 rules + 1 concept + template). Pull model.
