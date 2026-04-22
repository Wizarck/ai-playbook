# migration-guide.md

> **Status**: stub, v0.1.0. Populated in **T03b**.

## v0 → v1 of `AGENTS.md`

v0 = files without `schema: agents-md/v1` frontmatter.

### Migration stance (v0.1.0 of the playbook)

- **Warning, not hard fail.** `scripts/schema_validate.py` emits a warning and applies sensible defaults when frontmatter is missing.
- Defaults applied:
  ```yaml
  schema: agents-md/v1
  version: 0.0.1
  inherits_from: [github.com/Wizarck/ai-playbook@<pinned-version>]
  updated: <today>
  project: <repo-basename>
  owner: <git-user-email>
  capabilities_map: false
  ```
- **At playbook v2.0**, this becomes a hard fail — deprecation window gives consumers one major cycle.

### Per-project migration recipe

1. Add frontmatter at the top of `AGENTS.md`.
2. Move any universal content to a playbook override (`specs/*` PR if widely useful).
3. Ensure sections 0–8 follow the canonical order (see `specs/dispatcher-chain.md`).
4. Run `python scripts/schema_validate.py AGENTS.md` — verdict `✅` before commit.

## Populated in T03b

Worked example per consumer (consumer-c-legacy, consumer-d), the deprecation watcher that surfaces pending migrations (T22), and the autofix script.
