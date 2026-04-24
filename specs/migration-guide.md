# migration-guide.md

> **Status**: v1.0.0.

Procedure for migrating an existing `AGENTS.md` (or equivalent ad-hoc dispatcher file) from **v0** (pre-schema) to **v1** (compliant with `C:\Projects\ai-playbook\specs\agents-md-v1.schema.json`).

---

## What "v0" means

A file is treated as **v0** if ANY of the following is true:

- It has no YAML frontmatter block at all (just markdown prose).
- It has a frontmatter block but is missing the `schema: agents-md/v1` line.
- It has `schema: agents-md/v1` but is missing one or more required fields
  (`version`, `updated`, `project`, `owner`).
- It carries values that violate v1 type/pattern constraints (for example, `project: "my shop"`
  with a space, or `updated: "April 2026"` not in ISO-8601).

Any other shape — legacy `CLAUDE.md`, `.cursorrules`, `GEMINI.md` with arbitrary content, etc. —
is also v0 for the purpose of migration: it needs a v1 AGENTS.md alongside it, not a rename.
CLI routers (see `C:\Projects\ai-playbook\specs\dispatcher-chain.md`) stay as thin pointers.

---

## Migration stance at playbook v0.1.x (CURRENT)

**Warning, not hard fail.**

- `python scripts/schema_validate.py <path>` emits a `⚠️ warning` verdict for v0 files
  but exits 0 so pre-commit hooks don't block unrelated work.
- `--autofix` (see below) injects sensible defaults in-place; the dev reviews the diff and commits.
- Projects registry (`scripts/discover_projects.py`) skips v0 files silently and logs them
  under `~/.ai-playbook/migration-pending.log` for the deprecation watcher.
- Dispatcher resolution still works for v0 files (falls back to `./AGENTS.md` literal read)
  but inheritance is disabled — the agent loses the playbook norms.

## Migration stance at playbook v2.0 (FUTURE)

**Hard fail.**

- `schema_validate.py` exits non-zero on any v0 file. Pre-commit blocks the commit.
- `discover_projects.py` refuses to write a registry entry for v0 files.
- Dispatcher resolution prints a hard error and stops.

**Deprecation window** = 1 major playbook cycle. v0.1.x through v1.x.x are warn-only;
v2.0.0 flips the switch. Consumers get the entire v1 lifecycle to migrate.

---

## Per-project migration recipe

Ordered steps. Do NOT skip or reorder.

1. **Add frontmatter at the top of `AGENTS.md`.** If no file exists, create one.
   Minimum required block:
   ```yaml
   ---
   schema: agents-md/v1
   version: 0.1.0
   inherits_from:
     - github.com/Wizarck/ai-playbook@v0.1.0
   updated: 2026-04-23
   project: <your-repo-slug>
   owner: <your-email@example.com>
   capabilities_map: false
   ---
   ```

2. **Move universal content upstream.** Grep the old file for anything that applies to
   every project in your org (commit-message conventions, generic TDD rules, secrets-scan
   guidance, etc.). Open a PR against `ai-playbook/specs/*` instead of carrying it locally.
   Then DELETE it from your project AGENTS.md.

3. **Enforce canonical section order.** v1 files follow sections §0–§8:
   - §0 Bootstrap directive
   - §1 Project identity
   - §2 Dispatcher index
   - §3 Active work
   - §4 Hard rules (project-specific, NOT duplicating universals)
   - §5 Capability map (required if `capabilities_map: true`)
   - §6 MCP sources (pointer to SSOT)
   - §7 Overrides inherited from playbook
   - §8 Gotchas

   Reference: `C:\Projects\openTrattOS\AGENTS.md` for a populated example.

4. **Validate.** Run:
   ```bash
   python C:\Projects\ai-playbook\scripts\schema_validate.py AGENTS.md
   ```
   Verdict must be `✅ APPROVED` before commit.

5. **Register.** Run:
   ```bash
   python -m scripts.discover_projects
   ```
   from the playbook repo to refresh `~/.ai-playbook/projects.yaml`.

6. **Commit** with a Conventional Commits message: `docs: migrate AGENTS.md to playbook v1`.

---

## Autofix behavior

`python scripts/schema_validate.py <path> --autofix` is fully implemented as of
`schema_validate.py` v1. This section is the normative contract; the script honours it.

**What autofix WILL do:**
- Inject a missing frontmatter block using the defaults below.
- Repair `updated` from common near-ISO variants (`2026/04/23`, `April 23 2026`) to `2026-04-23`.
- Slugify `project` by lowercasing and replacing spaces/underscores with hyphens, BUT only
  when the existing value violates the pattern. Already-valid slugs are preserved verbatim.
- Add `capabilities_map: false` if absent.
- Pin `inherits_from` to the playbook tag currently checked out in `.ai-playbook/`.

**Defaults injected** (same as the manual recipe):
```yaml
schema: agents-md/v1
version: 0.0.1
inherits_from: [github.com/Wizarck/ai-playbook@<pinned-version>]
updated: <today>
project: <repo-basename>
owner: <git-user-email>
capabilities_map: false
```

**What autofix WILL NOT do:**
- Change `owner` if already set (even if invalid — the dev must fix it manually; contact info is sensitive).
- Delete existing fields, even unknown ones (additionalProperties is true).
- Touch prose below the frontmatter.
- Move sections around or rewrite headings.
- Add `personal: true` (this flag is load-bearing for the personal add-on; never auto-inferred).
- Change `project` when it's already a valid slug, even if it mismatches the directory name
  (that's a human decision — renaming a project has non-local consequences).

---

## Worked example

A hypothetical `acme-shop` team repo that predates the playbook.

### BEFORE (`C:\Code\acme-shop\AGENTS.md`, v0)

```markdown
# Acme Shop — Instructions for Claude

Hey Claude, when you work on this repo:

- Always run `npm test` before committing.
- Use conventional commits.
- The owner is jane@acme.example.
- Last updated: April 12 2026.

## Architecture
Next.js 14 + Prisma. Postgres on Supabase.

## Secrets
.env.local is gitignored. Don't ever print its contents.
```

No frontmatter, no section numbering, mixes universal norms (conventional commits) with
project-specific ones (stack). Fails validation.

### AFTER (v1)

```markdown
---
schema: agents-md/v1
version: 0.1.0
inherits_from:
  - github.com/Wizarck/ai-playbook@v0.1.0
updated: 2026-04-23
project: acme-shop
owner: jane@acme.example
capabilities_map: false
---

# acme-shop — AGENTS.md

> Project dispatcher. Lean. For universal norms see `.ai-playbook/specs/*`.

## 0 Bootstrap directive

1. Read `.ai-playbook/specs/dispatcher-chain.md`.
2. Only then act.

## 1 Project identity

acme-shop — Next.js 14 storefront backed by Prisma and Supabase Postgres.

## 2 Dispatcher index

| Topic | Pointer |
|---|---|
| Playbook norms | [.ai-playbook/specs/](.ai-playbook/specs/) |

## 3 Active work

None tracked at v0.1.0.

## 4 Hard rules (project-specific)

- `.env.local` is gitignored. Never print its contents or commit it.
- `npm test` must pass before any commit touching `apps/`.

## 5 Capability map

(Omitted — `capabilities_map: false`.)

## 6 MCP sources

None at v0.1.0.

## 7 Overrides inherited from playbook

None.

## 8 Gotchas

Empty at v0.1.0.
```

### Diff summary

- Added 9-line frontmatter block.
- Removed "use conventional commits" (universal — belongs upstream in the playbook).
- Removed "last updated: April 12 2026" prose (replaced by structured `updated` field).
- Restructured into §0–§8 canonical sections.
- Kept project-specific rules (`.env.local`, `npm test` gate) in §4.

---

## Common pitfalls

1. **`inherits_from` pin format wrong.** `github.com/Wizarck/ai-playbook@main` or
   `@0.1` both fail. It MUST be `github.com/<org>/<repo>@v?<MAJOR>.<MINOR>.<PATCH>` —
   a real semver tag, not a branch, not a truncated version.

2. **`updated` in wrong format.** `2026-4-23` (no leading zero) fails `format: date`.
   Use exactly `YYYY-MM-DD` with zero-padding: `2026-04-23`.

3. **`project` has spaces or path separators.** `"Acme Shop"` or `"acme/shop"` fail the
   slug pattern. Use `acme-shop`. The slug MUST match the repo directory name too, or the
   projects registry won't resolve `cwd`.

4. **Frontmatter delimiters missing or misplaced.** The `---` lines MUST be on their own
   line, at column 0, with the opening `---` on line 1. A BOM, leading whitespace, or
   anything (even a blank line) before the opening `---` breaks YAML parsers.

5. **Duplicating universal content in §4.** Hard rules like "use conventional commits" or
   "no `any` types in TypeScript across ALL projects" belong in `ai-playbook/specs/*`, not
   your project AGENTS.md. The review checklist is: "if this rule applies to more than one
   project, it should be upstream." Exceptions documented in §7 Overrides with a `Why:` line.

---

## See also

- `C:\Projects\ai-playbook\specs\agents-md-v1.schema.json` — the schema itself.
- `C:\Projects\ai-playbook\specs\dispatcher-chain.md` — 3-level inheritance model.
- `C:\Projects\ai-playbook\specs\projects-registry.md` — how the registry consumes valid v1 files.
- `C:\Projects\ai-playbook\specs\taxonomy.md` — glossary of terms used throughout.
