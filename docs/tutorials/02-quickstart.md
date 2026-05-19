# quickstart.md

> **Status**: v1.0.0. Honest 25–40 min walkthrough for a new dev bootstrapping a fresh consumer project called `acme-shop`. Per-OS friction and timing deltas land in [quickstart-lessons.md](quickstart-lessons.md) after T15 dry-runs.

---

## Prereqs (one-time, ~10 min if you don't have them)

| Tool | Why | Install (pick one) |
|---|---|---|
| Python 3.11+ | All playbook scripts | `pyenv install 3.11`, `winget install Python.Python.3.11`, `brew install python@3.11` |
| git 2.40+ | submodules, worktrees | OS package manager |
| pipx | isolated CLI installs (pre-commit, gh) | `python -m pip install --user pipx` |
| pre-commit | hook runner | `pipx install pre-commit` |
| Node.js 20+ + npx | runs `openspec` CLI | `nvm install 20`, `winget install OpenJS.NodeJS.LTS`, `brew install node` |
| gh CLI (authenticated) | PRs, issues | `gh auth login` |
| sops + age | secrets workflow | `brew install sops age`, `scoop install sops age`, `apt install sops age` |

Verify with step 6's doctor run. Missing any? The doctor output names the exact install command per OS.

---

## Step 1 — Clone the playbook as a submodule (≈3 min)

From inside the new project repo (created, `git init` done, first commit made):

```bash
# In C:/Projects/acme-shop (or wherever)
git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook
cd .ai-playbook && git checkout v0.1.0 && cd ..
git add .gitmodules .ai-playbook
git commit -m "feat: add ai-playbook submodule pinned at v0.1.0"
```

The submodule MUST be pinned to a semver tag, never a branch. This is the inheritance anchor for `AGENTS.md` frontmatter.

### What can go wrong

- **"fatal: repository ... not found"** → check `gh auth status` and SSH config. Use HTTPS URL if org SSH keys aren't set up.
- **Already committed a non-submodule `.ai-playbook/` dir from an earlier attempt** → `git rm -rf --cached .ai-playbook && rm -rf .ai-playbook` then retry.
- **Corporate proxy blocks github.com submodules** → mirror the playbook internally, update the URL in `.gitmodules`.

---

## Step 2 — Bootstrap (≈2 min)

```bash
python -m scripts.bootstrap --project-name acme-shop --owner you@example.com
```

Full flag list and contract live in [bootstrap-new-project.md](bootstrap-new-project.md). Summary of what runs:

1. Adds the playbook as a submodule at `.ai-playbook/`, pinned to the current released tag.
2. Copies `templates/new-project/` → project root with `{{PLACEHOLDER}}` substitution for the tokens it knows (`{{PROJECT_NAME}}`, `{{OWNER_EMAIL}}`, `{{TODAY}}`).
3. Installs pre-commit hooks.
4. Registers the project in `~/.ai-playbook/projects.yaml` via `scripts/discover_projects.py`.
5. Runs `scripts/doctor.py` as a smoke test (must verdict `✅` before exit).
6. Prints the remaining human-fill tokens and the next-step banner.

### What can go wrong

- **`ModuleNotFoundError: scripts`** → run with `PYTHONPATH=.ai-playbook python -m scripts.bootstrap ...` or invoke the script by absolute path (see the Windows section of [quickstart-lessons.md](quickstart-lessons.md)).
- **Template already exists** → bootstrap refuses to clobber. Move the old file aside or pass `--force-with-reason="..."` per `break-glass.md`.
- **Windows vs POSIX paths** — the template writes forward slashes; Windows handles them fine but some editors auto-convert. Leave them as `/`.

---

## Step 3 — Write your AGENTS.md (≈8 min)

Edit the freshly-copied `AGENTS.md`. Fill every `{{PLACEHOLDER}}`:

- `{{TODAY}}` — ISO date, e.g. `2026-04-23`.
- `{{PROJECT_NAME}}` — `acme-shop` (lowercase, no spaces).
- `{{OWNER_EMAIL}}` — a real contact email.
- `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}` — what acme-shop IS. Two sentences max.
- `{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}` — `none (bootstrap)` is fine at this stage.
- `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}` — things that are true for acme-shop but NOT for every playbook consumer.
- `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}` — usually `None.`
- `{{EMPTY_FILL_AS_YOU_LEARN}}` — leave empty; populate as you hit gotchas.

Validate:

```bash
python .ai-playbook/scripts/schema_validate.py AGENTS.md
```

Expected: `✅ AGENTS.md valid against schema agents-md/v1`.

### What can go wrong

- **`❌ AGENTS.md missing required field inherits_from`** → the template already has it; you deleted it. Put it back.
- **`❌ inherits_from pin is not a semver tag`** → use `v0.1.0`, not `main` or `HEAD`.
- **Forgot to fill a `{{PLACEHOLDER}}`** — `schema_validate.py` doesn't catch Mustache leftovers (it validates structure, not content). Grep the file: `grep -n '{{' AGENTS.md` should return nothing.

---

## Step 4 — Register the project in the local registry (≈1 min)

```bash
python -m scripts.discover_projects        # run from inside .ai-playbook/
# or from anywhere:
python .ai-playbook/scripts/discover_projects.py
```

This scans conventional roots plus `$AIPLAYBOOK_PROJECTS_ROOTS`, finds every directory with a v1 `AGENTS.md`, and writes `~/.ai-playbook/projects.yaml`. Verify:

```bash
python -m scripts.discover_projects --list
```

Your `acme-shop` entry should appear with `path`, `owner`, `version`, `inherits_from` populated from the frontmatter. Reference layout: [../templates/projects.yaml.example](../templates/projects.yaml.example). Schema: [../docs/concepts/projects-registry.md](../docs/concepts/projects-registry.md).

### What can go wrong

- **Not under a scanned root** → set `$AIPLAYBOOK_PROJECTS_ROOTS=C:/wherever` (comma or OS-pathsep separated) and rerun.
- **Two projects with the same logical name** → first occurrence wins; duplicate emits a warning. Rename one.
- **Registry file doesn't appear** → check `$AIPLAYBOOK_PROJECTS_FILE`; if unset, path is `~/.ai-playbook/projects.yaml`.

---

## Step 5 — Wire MCP servers (≈4 min)

Open `mcp-servers.yaml` (copied in Step 2). Declare the MCP servers this project uses, per the schema at [../docs/concepts/mcp-servers-schema.md](../docs/concepts/mcp-servers-schema.md). Minimal shape:

```yaml
schema: mcp-servers/v1
project: acme-shop
servers:
  hindsight:
    transport: stdio
    command: hindsight-mcp
    args: []
    env:
      HINDSIGHT_PROJECT: acme-shop
```

Dry-run the render to see what `.mcp.json` will look like:

```bash
python .ai-playbook/scripts/mcp/render.py --project acme-shop --dry-run
```

If the diff looks right, rerun without `--dry-run` to write `.mcp.json`. Commit both files.

### What can go wrong

- **`❌ mcp-servers.yaml fails schema validation`** → the error names the field. Common: missing `transport`, unknown `command` binary, env var reference without a `$` prefix.
- **Drift between `mcp-servers.yaml` and committed `.mcp.json`** — pre-commit will block. Rerun `mcp/render.py` without `--dry-run`.

---

## Step 6 — Install pre-commit hooks (≈2 min)

```bash
pre-commit install
pre-commit run --all-files
```

First `--all-files` pass will be slow (hooks compile). Subsequent commits hit only changed files. Hooks registered by the playbook include `schema_validate`, `secrets_scan`, `verdict_lint`, `block_manual_spec_edit`, and `drift_check`.

### What can go wrong

- **`secrets_scan` flags an example value** — if the string is genuinely synthetic, prefix with `EXAMPLE_` or move to a fixture file. There is NO break-glass for secrets (`OVERRIDE: none`).
- **`schema_validate` fails on `.ai-playbook/AGENTS.md`** — you edited the submodule tree directly. Revert; edit in the playbook repo itself and bump the pin.
- **Hooks hang on Windows** — ensure Python is on PATH, not just inside pipx's venv.

---

## Step 7 — Your first OpenSpec change (≈8 min)

Pick a tiny feature to bootstrap the rhythm. Create the change folder:

```bash
mkdir -p openspec/changes/acme-shop-bootstrap
```

Write `openspec/changes/acme-shop-bootstrap/proposal.md` — one paragraph on problem, one on approach. Then `specs/` and `tasks.md` per the per-artefact sequence in [../docs/concepts/runbook-bmad-openspec.md](../docs/concepts/runbook-bmad-openspec.md) §3.1. Validate:

```bash
python .ai-playbook/scripts/openspec_validate.py acme-shop-bootstrap
```

If you're using Claude Code, the slash command flow is:

```
/opsx:propose  → creates proposal + specs + design + tasks
/opsx:apply    → implements tasks with worker→QA pairing
/opsx:archive  → promotes specs to openspec/specs/ and runs post-archive retro
```

Verdict contract for each artefact: [../docs/rules/verdict-contract.rule.md](../docs/rules/verdict-contract.rule.md). After archive, drop a retro per [../templates/retro/post-archive.md.tmpl](../templates/retro/post-archive.md.tmpl).

### What can go wrong

- **`❌ openspec change missing proposal.md`** → you skipped step 1 of the artefact sequence.
- **Tried to edit `openspec/specs/` by hand** — blocked by `block_manual_spec_edit.py`. Archive a change instead.
- **Verdict lint fails** — the verdict line must be the literal string from `verdict-contract.md` §1, emoji and capitalisation included.

---

## Step 8 — Wire the SessionStart hook (≈3 min)

If you use Claude Code, add the Hindsight context-injection hook so prior-session memory lands in every new session. Follow [session-start-hook.md](session-start-hook.md) end-to-end — it ships a ready-to-paste `~/.claude/settings.json` snippet.

If you use Gemini CLI / Cursor / Antigravity, the same `scripts/inject_context.py` can be wrapped in the CLI's equivalent startup hook; see the end of that doc for variants.

### What can go wrong

- **Hook fires but Hindsight MCP is down** — degradation state flips to `DEGRADED_CONTEXT` (see [../docs/concepts/degradation-modes.md](../docs/concepts/degradation-modes.md)). The session continues without memory; the warning is expected.
- **Hook times out** — raise the harness timeout to 15 s; memory reads can be slow on cold cache.

---

## Time budget summary

| Step | Budget | Cumulative |
|---|---|---|
| Prereqs (one-time) | 10 min | — |
| 1. Submodule | 3 min | 3 |
| 2. Bootstrap | 2 min | 5 |
| 3. AGENTS.md | 8 min | 13 |
| 4. Register | 1 min | 14 |
| 5. MCP | 4 min | 18 |
| 6. Hooks | 2 min | 20 |
| 7. First OpenSpec change | 8 min | 28 |
| 8. SessionStart hook | 3 min | 31 |

**Realistic total: 25–40 min** depending on OS, existing toolchain, and network. Cross-OS deltas logged in [quickstart-lessons.md](quickstart-lessons.md) after T15.

---

## You're live. Next steps

- First retro: use [../templates/retro/post-archive.md.tmpl](../templates/retro/post-archive.md.tmpl) after your first archive.
- Hit friction? Append a bullet to [../FEEDBACK.md](../FEEDBACK.md). One sentence, dated, signed.
- Read [../docs/concepts/runbook-bmad-openspec.md](../docs/concepts/runbook-bmad-openspec.md) before your first real PRD.
