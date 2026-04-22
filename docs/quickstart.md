# quickstart.md

> **Status**: honest 25–40 min dry-run. Populated in **T15** after cross-OS validation.

## Prereqs

- Python 3.11+
- git, git-lfs
- gh CLI (authenticated)
- pre-commit (`pipx install pre-commit`)
- Node.js 20+ and npm / npx (for `openspec` CLI)
- SOPS + age (for decrypting secrets)

See `scripts/doctor.py` (T14a) to verify.

## Steps

1. Clone your consumer repo and initialize the submodule:
   ```bash
   git submodule add git@github.com:Wizarck/ai-playbook.git .ai-playbook
   cd .ai-playbook && git checkout v0.1.0 && cd ..
   git commit -am "feat: add ai-playbook submodule at v0.1.0"
   ```
2. Bootstrap: `python .ai-playbook/scripts/bootstrap.py <project-name>`.
3. Install hooks: `pre-commit install`.
4. Validate: `python .ai-playbook/scripts/schema_validate.py AGENTS.md`.
5. Render MCP configs: `python .ai-playbook/scripts/mcp/render.py --project <project-name>`.

## Populated in T15

Cross-OS walkthroughs (Windows / macOS / Linux / WSL), common gotchas, realistic timings.
