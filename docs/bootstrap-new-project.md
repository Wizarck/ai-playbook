# bootstrap-new-project.md

> **Status**: stub, v0.1.0. Populated in **T14a**.

## Template substitution (future behavior of `scripts/bootstrap.py`)

Given `<project-name>` and `<owner-email>`, the bootstrap script:

1. Adds submodule: `git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook`.
2. Pins to current playbook tag.
3. Copies `templates/new-project/` → project root, substituting `{{PROJECT_NAME}}`, `{{TODAY}}`, `{{OWNER_EMAIL}}`, `{{ACTIVE_OPENSPEC_CHANGE_OR_NONE}}`, `{{ONE_TO_THREE_LINES_ABOUT_THE_PROJECT}}`, `{{PROJECT_SPECIFIC_RULES_NOT_DUPLICATING_PLAYBOOK}}`, `{{NONE_OR_EXPLICIT_OVERRIDES_WITH_RATIONALE}}`, `{{EMPTY_FILL_AS_YOU_LEARN}}`.
4. Installs pre-commit hooks.
5. Runs `scripts/doctor.py` — must verdict `✅` before bootstrap exits.
6. Prints next steps (add project-specific sections, commit, push).

## Templates

See `templates/new-project/`:
- `AGENTS.md.tmpl`
- `.mcp.json.tmpl`
- `mcp-servers.yaml.tmpl`
- `.claude/settings.json.tmpl`
- `.pre-commit-config.yaml.tmpl`
- `docs/runbook.md.tmpl`
- `GEMINI.md.tmpl`
- `.gitattributes`
