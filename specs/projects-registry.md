# projects-registry.md

> **Status**: v1.0.0. The registry is load-bearing for dispatcher resolution across CLIs.

## Purpose

A **per-dev, gitignored YAML file** mapping project logical names to absolute paths on the current machine. Dispatchers resolve project locations through the registry, NOT through hardcoded paths.

Benefit:
- Arturo moves `openTrattOS` from `C:\OpenTrattOS` to `C:\Projects\openTrattOS` → rerun discovery → dispatchers keep working. No markdown edits.
- A second dev clones projects under `/Users/jane/code/` → same dispatcher files work.
- Mac / Linux / Windows / WSL coexist with the same sources.

## File location

| Tier | Path | Purpose |
|---|---|---|
| Default | `~/.ai-playbook/projects.yaml` | Arturo + team default. |
| Override | `$AIPLAYBOOK_PROJECTS_FILE` | Testing, sandboxes, CI. |

The file lives in the **user's home** (not in any repo) because it encodes local truths.

## Format (v1)

```yaml
schema: ai-playbook/projects-registry/v1
projects:
  openTrattOS:
    path: C:/Projects/openTrattOS
    owner: arturo6ramirez@gmail.com
    version: 1.0.0
    inherits_from:
      - github.com/Wizarck/ai-playbook@v0.1.0
  eligia-core:
    path: C:/Projects/eligia-core
    owner: arturo6ramirez@gmail.com
    version: 1.0.0
    inherits_from:
      - github.com/Wizarck/ai-playbook@v0.1.0
    personal: true
    personal_addon: C:/Projects/eligia-core/ELIGIA.md
```

### Fields

| Field | Required | Source | Meaning |
|---|---|---|---|
| `path` | yes | discovered | Absolute path to project root. |
| `owner` | no | `AGENTS.md` frontmatter | Contact email. |
| `version` | no | `AGENTS.md` frontmatter | Project's AGENTS.md version. |
| `inherits_from` | no | `AGENTS.md` frontmatter | Playbook pin list. |
| `personal` | no | `AGENTS.md` frontmatter | `true` if this is Arturo's personal repo (loads the add-on). Default `false`. |
| `personal_addon` | no | computed | Absolute path to the add-on file (e.g. `ELIGIA.md`). Resolved from frontmatter `personal_addon` relative to project root. |

## Discovery script

`scripts/discover_projects.py`:

- Scans roots from `$AIPLAYBOOK_PROJECTS_ROOTS` (comma or OS-pathsep separated) + conventional dirs (`~/Projects`, `~/projects`, `C:/Projects`, `/opt`, `/srv`).
- Finds any directory with `AGENTS.md` whose frontmatter declares `schema: agents-md/v1`.
- Parses frontmatter; builds a `ProjectEntry`; writes/merges the registry.
- Max scan depth: 3. Skips `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `Library`, `AppData`, etc.
- Duplicate project names: the first occurrence wins; subsequent duplicates emit a warning.

Usage:
```bash
python -m scripts.discover_projects                    # refresh
python -m scripts.discover_projects --dry-run          # preview
python -m scripts.discover_projects --list             # print current
python -m scripts.discover_projects --add <PATH>       # explicit add
python -m scripts.discover_projects --roots ~/work     # custom roots
```

## Resolution rule (used by dispatchers)

Given a current working directory `cwd`:

1. Load registry from `$AIPLAYBOOK_PROJECTS_FILE` or `~/.ai-playbook/projects.yaml`.
2. For each project entry, check if `cwd == path` or `cwd` is under `path`.
3. First match wins → load that project's `AGENTS.md`.
4. If `personal: true` and `personal_addon` is set → also load the add-on.
5. If no match → fall back to `./AGENTS.md` if it exists; otherwise the agent operates without a dispatcher.

## Gitignore

`projects.yaml` MUST NOT be committed to any repo. It's per-dev truth. The root `.gitignore` of this playbook excludes `.ai-playbook/` (Arturo's local registry dir if ever placed inside a repo). Consumers SHOULD add `projects.yaml` to their own `.gitignore` too.

## Maintenance

- Run `discover_projects.py` during project bootstrap (`scripts/bootstrap.py` calls it).
- Run again manually after moving / renaming a project.
- `doctor.py` (T14a) verifies the registry resolves cwd to a valid project and warns otherwise.

## Env vars introduced by this spec

See `specs/env-vars.md`:
- `AIPLAYBOOK_PROJECTS_FILE` — override registry path.
- `AIPLAYBOOK_PROJECTS_ROOTS` — comma or OS-pathsep-separated extra scan roots.
