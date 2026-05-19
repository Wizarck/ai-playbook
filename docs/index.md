# ai-playbook

> Universal AI-dev norms, specs, scripts, and templates consumed via **git submodule** by every Wizarck project — LLM-agnostic, dogfooded, and dispatch-file shaped.

=== "Start here"

    New to the playbook? Read these in order:

    - [development-flow.md](development-flow.md) — **LLM-agnostic canonical entry point**: how to make a change in any playbook-consuming project. Read first.
    - [start-here.md](start-here.md) — 60-second orientation: dispatcher chain, first 5 commands, where-to-go-next table.

=== "Onboarding"

    Stand up a new consumer repo or a fresh machine.

    - [quickstart.md](quickstart.md) — 25–40 min bootstrap of `acme-shop` end-to-end.
    - [quickstart-lessons.md](quickstart-lessons.md) — real friction recorded from dry-runs.
    - [session-start-hook.md](session-start-hook.md) — wire `SessionStart` context injection.
    - [contributing.md](contributing.md) — how PRs land; governance for the 0–3 month horizon.

=== "Specs"

    The universal contracts every consumer inherits via `.ai-playbook/specs/*`.

    - [Full specs index](../specs/INDEX.md) — auto-generated, every file + status + summary.
    - [dispatcher-chain](../docs/concepts/dispatcher-chain.md) — 3-level inheritance model.
    - [verdict-contract](../docs/rules/verdict-contract.rule.md) — QA output shape.
    - [error-message-standard](../docs/rules/error-message-standard.rule.md) — canonical error format.

## What the playbook stands for

Four of the eight universal principles the playbook is built on (the full list lives in your global `CLAUDE.md`):

- **Do not assume** — agents verify or escalate `❓ CLARIFICATION NEEDED` rather than invent data.
- **Dispatch-file architecture** — lean root docs; anything over ~10 lines becomes a pointer to a `specs/` detail.
- **Framework files stay lean** — no changelogs inline, no evolutionary comments; history lives in git.
- **Approval-gated progression** — one artifact or change at a time, waiting for approval before the next.

## Where to go next

- [AGENTS.md](https://github.com/Wizarck/ai-playbook/blob/master/AGENTS.md) — the self-hosted dispatcher for agents editing THIS repo.
- [start-here.md](start-here.md) — the 60-second pitch, with the first 5 commands and the situation → reading matrix.
- [architecture-diagrams.md](architecture-diagrams.md) — Mermaid views of the dispatcher chain and pre-commit gates.
- [why-these-choices.md](why-these-choices.md) — the rationale behind every load-bearing decision.

## Status

- **Version**: `v0.1.0` — scaffold committed; `baseline` branch preserves the pre-refactor state.
- **Active track**: T14–T16 (EX package, cross-OS dry-runs, docs hub).
- **Changelog / migration notes**: see [migration-guide](../docs/concepts/migration-guide.md) for v0 → v1 procedure and the repo's `rfcs/` directory for per-version decisions.
