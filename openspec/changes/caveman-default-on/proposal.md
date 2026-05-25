# caveman-default-on

> **Status**: SCRATCH (gitignored — `openspec/` dropped from playbook in PR #79).
> Canonical contract lives in the PR description (#95). This file exists to satisfy the `branch-name-validator` workflow.

## Why

PR #88 shipped the caveman feature as opt-in: every consumer had to run `python -m scripts.caveman on` manually after bootstrap. User feedback: "why do I have to run `caveman on` if it should be activated by default in the AI-playbook?" — fair point. The whole value proposition of bundling caveman INTO the playbook is that the playbook ships token-efficient defaults. If activation is per-project manual, almost nobody flips it.

## What

Make caveman default-on for new projects (via bootstrap) and dogfood it on the playbook itself.

### Scope (this PR)

- `scripts/bootstrap.py`: new step 4.6 invokes `python -m scripts.caveman on --mode full --components <all six> --project <target>`. Runs after templates are copied and before MCP configs are rendered, so the post-render shrink hook auto-wraps `.mcp.json` / `.gemini/settings.json` in a single pass.
- `--no-caveman` flag for opt-out at bootstrap time.
- 4 new bootstrap tests pinning the default-on contract.
- Playbook dogfoods caveman: `.ai-playbook/caveman.json` committed (narrow `.gitignore` exception so only the toggle state is tracked, not notifications.jsonl / overrides.log / backups/).
- AGENTS.md carries the materialised `caveman/ruleset:full` block (auto-managed).
- `scripts/auto_managed.py` resolves `caveman/ruleset:<mode>` markers via `materialise.render_block_content` — same function `caveman on` uses, so drift_check and materialise stay byte-identical by construction.
- Runbook updated with the default-on policy + opt-out path.

### Out of scope

- Migration script for existing consumers — they still run `caveman on` once. Bootstrap-time default-on is one-shot.
- Changing read_state default to "enabled" in `toggle.py` — would have changed behaviour for every existing consumer on submodule update, which is too surprising.

## Test plan

- Full pytest suite green (1376 passed, 2 skipped).
- `python -m scripts.drift_check --check auto-managed` clean.
- `python scripts/ai_playbook_check.py --check` — only pre-existing drift findings (6 invariant violations were present before this PR).
- `python -m ruff check .` — all checks passed.
- Manual on a new consumer: bootstrap → confirm `.ai-playbook/caveman.json` + AGENTS.md marker + `.mcp.json` wrapped.
