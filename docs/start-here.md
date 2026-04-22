# start-here.md

> **Status**: 1-pager for new devs. Populated in **T14b**.

## If you just cloned this

You are looking at the **ai-playbook** repo. Most files are v0.1.0 scaffold stubs. The table in [README.md](../README.md) tells you what content lands in which downstream track.

## If you are bootstrapping a NEW consumer project

Run:

```bash
git clone git@github.com:Wizarck/ai-playbook.git .ai-playbook
python .ai-playbook/scripts/bootstrap.py <project-name>
```

(Bootstrap script is a stub in v0.1.0; full behavior lands in T14a.)

## If you are contributing

1. Read [AGENTS.md](../AGENTS.md) — self-hosted dispatcher for this repo.
2. Read [docs/contributing.md](contributing.md) — RFC process + governance (populated in T14).
3. Pre-commit: `pip install pre-commit && pre-commit install`.

## Status at a glance

- v0.1.0: scaffold committed, baseline branch for rollback.
- Next: T02 dispatcher refactor across consumer repos.
- Full plan: `~/.claude/plans/tengo-un-amigo-que-hidden-flamingo.md` (personal, not in this repo).
