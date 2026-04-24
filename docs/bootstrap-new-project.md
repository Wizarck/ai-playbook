# bootstrap-new-project.md

> **Status**: v1.0.0. Authored in T14a; full implementation landed in T22e.

## Goal

Take a fresh repo from zero to "Claude Code / Gemini CLI / Cursor / Antigravity can all honour the playbook's universal norms" in ≤10 minutes. No hand-copying, no guessing which files matter.

The entry point is `scripts/bootstrap.py` (~534 lines, fully implemented). It is idempotent: running it twice on the same repo is a no-op except for an OTel span.

## Usage

```bash
# From inside a freshly-cloned consumer repo (not inside ai-playbook itself):
python <path-to-ai-playbook>/scripts/bootstrap.py \
    --project-name acme-shop \
    --owner arturo6ramirez@gmail.com \
    --playbook-tag v0.2.0
```

Common flags:

| Flag | Effect |
|---|---|
| `--project-name <slug>` | Required. Kebab-case, matches the repo dir name. |
| `--owner <email>` | Required. Owner email stamped into `AGENTS.md` frontmatter. |
| `--playbook-tag <tag>` | Optional. Semver tag to pin the submodule to. Default: latest released tag. |
| `--playbook-path <path>` | Offline fallback — use a local playbook checkout instead of cloning. Requires `--force-with-reason` (breaks the "always pin to released tag" invariant). |
| `--personal` | Registers the project as `personal: true` in `~/.ai-playbook/projects.yaml`. Only for Arturo. |
| `--dry-run` | Print the plan without mutating disk. |

## What it does (in order)

1. **Submodule add + pin**
   - `git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook`
   - `cd .ai-playbook && git checkout <tag>`
   - Writes `.gitmodules` with the pinned tag and commits.
2. **Template copy with placeholder substitution**
   - Copies `templates/new-project/` → project root.
   - Substitutes Mustache-style placeholders: `{{PROJECT_NAME}}`, `{{TODAY}}`, `{{OWNER_EMAIL}}`, `{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}`, `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}`, `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}`, `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}`, `{{EMPTY_FILL_AS_YOU_LEARN}}`.
   - Files created:
     - `AGENTS.md` — project dispatcher.
     - `CLAUDE.md`, `GEMINI.md` — thin routers pointing at `AGENTS.md`.
     - `.cursor/rules/00-dispatcher.mdc` — Cursor router (`alwaysApply: true`).
     - `.mcp.json`, `mcp-servers.yaml` — MCP config skeleton.
     - `.claude/settings.json` — CLI hook scaffold.
     - `.pre-commit-config.yaml` — pins the playbook's hook bundle.
     - `docs/runbook.md` — project-specific runbook skeleton.
     - `.gitattributes` — LF-only for cross-OS consistency.
3. **Pre-commit hook install**
   - `pre-commit install --install-hooks`.
4. **Registry entry**
   - Appends an entry to `~/.ai-playbook/projects.yaml` so this new project resolves via `~/.claude/CLAUDE.md` without manual edits.
5. **Smoke test via `scripts/doctor.py`**
   - Runs the full prerequisite check. Must verdict `✅` before bootstrap exits.
   - Any `⚠️` is advisory (reported but non-blocking); any `❌` fails bootstrap and prints the canonical error format.
6. **Next-steps banner**
   - Prints the three human actions left: (a) edit remaining `{{PLACEHOLDER}}` tokens, (b) `git add` + commit, (c) push.

## Placeholder contract

Every template file uses Mustache-style `{{TOKEN}}` placeholders. `bootstrap.py` substitutes the ones it knows; the rest are left for the human (e.g. project-specific hard rules, the one-liner project description). Running `grep -n '{{' <file>` after bootstrap completes should show only these human-fill tokens — zero substituted tokens remaining is a bug.

## Templates

See [`templates/new-project/`](../templates/new-project/):

- `AGENTS.md.tmpl`
- `CLAUDE.md.tmpl`, `GEMINI.md.tmpl`
- `.cursor/rules/00-dispatcher.mdc.tmpl`
- `.mcp.json.tmpl`
- `mcp-servers.yaml.tmpl`
- `.claude/settings.json.tmpl`
- `.pre-commit-config.yaml.tmpl`
- `docs/runbook.md.tmpl`
- `.github/workflows/issue-sync.yml.tmpl`
- `.github/workflows/release-cut.yml.tmpl`
- `.gitattributes`

## Break-glass

`--force-with-reason "<text>"` is accepted on the following sub-gates (see [break-glass.md](../specs/break-glass.md) for the full contract):

- `--playbook-path <local>` without a released tag → breaks pinning invariant.
- Doctor failure → proceed anyway (discouraged; shows up in `overrides.log`).

`scripts/secrets_scan.py` and the schema-violation gate are `OVERRIDE: none`.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'scripts.mcp'`** when running playbook scripts from the consumer repo: use `PYTHONPATH=.ai-playbook python -m scripts.<name>` or invoke via the absolute path. See [quickstart-lessons.md](quickstart-lessons.md) §Windows.
- **Pre-commit install fails** on fresh Windows: install `pre-commit` via `pipx install pre-commit` first.
- **Registry file empty**: run `python .ai-playbook/scripts/discover_projects.py` once; bootstrap.py will then find the file.

## See also

- [quickstart.md](quickstart.md) — the manual 25–40 min walkthrough; `bootstrap.py` replaces steps 2–5.
- [quickstart-lessons.md](quickstart-lessons.md) — per-OS friction and workarounds discovered during T15 dry-runs.
- [../specs/bootstrap-directive.md](../specs/bootstrap-directive.md) — the directive the generated AGENTS.md §0 carries.
- [../specs/projects-registry.md](../specs/projects-registry.md) — format of the registry file bootstrap writes to.
