---
schema: tutorial/v1
slug: bootstrap-new-project
title: Bootstrap a new consumer project with one command
description: Replace the 5-step manual quickstart with one invocation of scripts/bootstrap.py. Idempotent, schema-validated, ends with a green doctor verdict.
estimated_time: "10 min"
prerequisite_concepts: [dispatcher-chain, projects-registry]
audience: operator
order: 4
---

# Bootstrap a new consumer project with one command

> **What you'll learn**: How to use `scripts/bootstrap.py` to take a fresh repo from zero to "Claude Code / Gemini CLI / Cursor / Antigravity can all honour the playbook's universal norms" in ≤10 minutes. By the end you will have run the one-shot script, watched the doctor verdict turn green, and know what every flag does.
> **Estimated time**: 10 min
> **Prerequisites**:
> - The quickstart ([03-quickstart.md](03-quickstart.md)) — at least skimmed, so you know what `bootstrap.py` is automating
> - All quickstart prereqs (Python 3.11+, git 2.40+, pipx, pre-commit, Node 20+, gh CLI, sops + age)

The entry point is `scripts/bootstrap.py`. It is idempotent: running it twice on the same repo is a no-op except for an OTel span.

## Usage

```bash
# From inside a freshly-cloned consumer repo (not inside ai-playbook itself).
# project_name is a POSITIONAL argument, not a --flag:
python <path-to-ai-playbook>/scripts/bootstrap.py acme-shop \
    --owner you@example.com \
    --playbook-pin v0.19.4
```

Common flags (`bootstrap.py --help` is the source of truth):

| Flag | Effect |
|---|---|
| `project_name` (positional) | Required. Kebab-case slug, matches the repo dir name. Pattern `[a-zA-Z0-9][a-zA-Z0-9_-]*`. |
| `--owner <email>` | Owner email stamped into `AGENTS.md` frontmatter. Default: `$GIT_AUTHOR_EMAIL` then `git config user.email`. |
| `--path <dir>` | Target directory. Default: `<cwd>/<project_name>`. |
| `--playbook-pin <tag>` | Semver tag to pin the submodule to. Default: `DEFAULT_PIN` in `bootstrap.py` (currently `v0.19.4` — kept in sync with each playbook release). |
| `--playbook-path <path>` | Offline fallback — copy from a local playbook checkout instead of cloning. Requires `--force-with-reason` (breaks the "always pin to released tag" invariant). |
| `--personal` | Marks the generated `AGENTS.md` with `personal: true`. Only for the maintainer's personal repos. |
| `--dry-run` | Report planned actions without side effects. |
| `--refresh-skills` | Skip the full bootstrap flow and only run skills materialisation against `--path` (or cwd). Reads `skills_sources` from the consumer's AGENTS.md frontmatter (RFC-0001 §2). |
| `--force-with-reason <text>` | Override a blocking gate with an audit trail. Reason must be ≥10 non-whitespace chars; logged to `.ai-playbook/overrides.log`. |

## What it does (in order)

1. **Submodule add + pin**
   - `git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook`
   - `cd .ai-playbook && git checkout <tag>`
   - Writes `.gitmodules` with the pinned tag and commits.
2. **Template copy with placeholder substitution**
   - Copies `templates/new-project/` → project root.
   - Substitutes the Mustache-style placeholders bootstrap knows: `{{TODAY}}`, `{{PROJECT_NAME}}`, `{{OWNER_EMAIL}}`. The rest (`{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}`, `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}`, `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}`, `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}`, `{{EMPTY_FILL_AS_YOU_LEARN}}`) are left verbatim for the human to fill.
   - Files created (full list per `templates/new-project/` — keep this in sync):
     - `AGENTS.md` — project dispatcher.
     - `CLAUDE.md`, `GEMINI.md` — thin routers pointing at `AGENTS.md`.
     - `.cursor/rules/` — Cursor router(s) (`alwaysApply: true`).
     - `.mcp.json`, `mcp-servers.yaml`, `mcp-servers.project.yaml` — MCP config skeleton (base + per-project override).
     - `.claude/settings.json`, `.claude/hooks/` — CLI hook scaffold.
     - `.pre-commit-config.yaml` — pins the playbook's hook bundle.
     - `.coderabbit.yaml` — CodeRabbit reviewer config.
     - `.gitignore` — playbook-managed entries (break-glass state, notification queue, hindsight queue).
     - `docs/runbook.md` — project-specific runbook skeleton.
     - `.github/workflows/` — issue-sync + release-cut workflows.
     - `.gitattributes` — LF-only for cross-OS consistency.
3. **Pre-commit hook install**
   - `pre-commit install --install-hooks` (best-effort; warns if `pre-commit` is absent).
4. **Doctor smoke-test (`scripts/doctor.py`)**
   - Runs the full prerequisite check with CWD set to the new project. Any `⚠️` is advisory; any `❌` fails bootstrap with the canonical error format.
5. **Registry entry**
   - `python -m scripts.discover_projects --add <project-dir>` appends an entry to `~/.ai-playbook/projects.yaml` so the project resolves via `~/.claude/CLAUDE.md` without manual edits.
6. **Personal flag (if `--personal`)**
   - Injects `personal: true` into `AGENTS.md` frontmatter.
7. **Next-steps banner**
   - Prints the three human actions left: (a) edit remaining `{{PLACEHOLDER}}` tokens, (b) `git add` + commit, (c) push.

After step 7, run [`ai-playbook-check`](../../skills/ai-playbook-check/SKILL.md) against the new project to confirm no rule is in drift before your first PR:

```bash
python .ai-playbook/scripts/ai_playbook_check.py --check
```

## Placeholder contract

Every template file uses Mustache-style `{{TOKEN}}` placeholders. `bootstrap.py` substitutes the ones it knows; the rest are left for the human (e.g. project-specific hard rules, the one-liner project description). Running `grep -n '{{' <file>` after bootstrap completes should show only these human-fill tokens — zero substituted tokens remaining is a bug.

## Templates

See [`templates/new-project/`](../../templates/new-project/) — the source-of-truth
list lives there. As of v0.19.4 it includes:

- `AGENTS.md.tmpl`
- `CLAUDE.md.tmpl`, `GEMINI.md.tmpl`
- `.cursor/rules/` — Cursor router(s)
- `.mcp.json.tmpl`, `mcp-servers.yaml.tmpl`, `mcp-servers.project.yaml.tmpl`
- `.claude/settings.json.tmpl` plus `.claude/hooks/`
- `.pre-commit-config.yaml.tmpl`
- `.coderabbit.yaml.tmpl`
- `.gitignore.tmpl`
- `docs/runbook.md.tmpl`
- `.github/workflows/` (issue-sync, release-cut, …)
- `.gitattributes`

If you add a file under `templates/new-project/`, append it here AND verify
`scripts/bootstrap.py` copies it (the script walks the directory; no opt-in
list needed, but tests in `tests/test_bootstrap*.py` assert on key files).

## Break-glass

`--force-with-reason "<text>"` is accepted on the following sub-gates (see [break-glass.md](../rules/break-glass.rule.md) for the full contract):

- `--playbook-path <local>` without a released tag → breaks pinning invariant.
- Doctor failure → proceed anyway (discouraged; shows up in `overrides.log`).

`scripts/secrets_scan.py` and the schema-violation gate are `OVERRIDE: none`.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'scripts.mcp'`** when running playbook scripts from the consumer repo: use `PYTHONPATH=.ai-playbook python -m scripts.<name>` or invoke via the absolute path.
- **Pre-commit install fails** on fresh Windows: install `pre-commit` via `pipx install pre-commit` first.
- **Registry file empty**: run `python .ai-playbook/scripts/discover_projects.py` once; bootstrap.py will then find the file.

## What's next

- [03-quickstart.md](03-quickstart.md) — the manual 25–40 min walkthrough; `bootstrap.py` replaces steps 2–5.
- [Skill: ai-playbook-check](../../skills/ai-playbook-check/SKILL.md) — audit drift across every rule after bootstrap.
- [05-learning-path.md](05-learning-path.md) — self-paced reading order once your project is bootstrapped.
- [Rule: bootstrap-directive](../rules/bootstrap-directive.rule.md) — the directive the generated AGENTS.md §0 carries.
- [Concept: projects-registry](../concepts/projects-registry.md) — format of the registry file bootstrap writes to.
- [Concept: dispatcher-chain](../concepts/dispatcher-chain.md) — the three-level inheritance bootstrap wires into.
