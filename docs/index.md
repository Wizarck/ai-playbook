# ai-playbook

> Universal AI-dev norms, specs, scripts, and templates consumed via **git submodule** by every consumer project — LLM-agnostic, dogfooded, and dispatch-file shaped.

=== "Start here"

    New to the playbook? Read these in order:

    - [concepts/development-flow.md](concepts/development-flow.md) — **LLM-agnostic canonical entry point**: how to make a change in any playbook-consuming project. Read first.
    - [tutorials/02-start-here.md](tutorials/02-start-here.md) — 60-second orientation: dispatcher chain, first 5 commands, where-to-go-next table.

=== "Onboarding"

    Stand up a new consumer repo or a fresh machine.

    - [tutorials/03-quickstart.md](tutorials/03-quickstart.md) — 25–40 min bootstrap of `acme-shop` end-to-end.
    - [concepts/session-start-hook.md](concepts/session-start-hook.md) — wire `SessionStart` context injection.
    - [CONTRIBUTING.md](../CONTRIBUTING.md) — how PRs land.

=== "Specs"

    The universal contracts every consumer inherits via `.ai-playbook/`.

    - [Rules index](rules/INDEX.md) — every paired-enforcement rule, status, and slug.
    - [Concepts index](concepts/INDEX.md) — reference + explanation docs (Diátaxis).
    - [concepts/dispatcher-chain.md](concepts/dispatcher-chain.md) — 3-level inheritance model.
    - [rules/verdict-contract.rule.md](rules/verdict-contract.rule.md) — QA output shape.
    - [rules/error-message-standard.rule.md](rules/error-message-standard.rule.md) — canonical error format.

## What the playbook stands for

Four of the eight universal principles the playbook is built on (the full list lives in your global `CLAUDE.md`):

- **Do not assume** — agents verify or escalate `❓ CLARIFICATION NEEDED` rather than invent data.
- **Dispatch-file architecture** — lean root docs; anything over ~10 lines becomes a pointer to a detail doc.
- **Framework files stay lean** — no changelogs inline, no evolutionary comments; history lives in git.
- **Approval-gated progression** — one artifact or change at a time, waiting for approval before the next.

## Where to go next

- [AGENTS.md](https://github.com/Wizarck/ai-playbook/blob/master/AGENTS.md) — the self-hosted dispatcher for agents editing THIS repo.
- [tutorials/02-start-here.md](tutorials/02-start-here.md) — the 60-second pitch, with the first 5 commands and the situation → reading matrix.
- [concepts/architecture-diagrams.md](concepts/architecture-diagrams.md) — Mermaid views of the dispatcher chain and pre-commit gates.
- [tutorials/06-why-these-choices.md](tutorials/06-why-these-choices.md) — the rationale behind every load-bearing decision.

## Status

- **Version**: see [VERSION](../VERSION) — semver pinned, propagated to consumers via the submodule bump bot.
- **Changelog / migration notes**: see [concepts/migration-guide.md](concepts/migration-guide.md) for v0 → v1 procedure and [../CHANGELOG.md](../CHANGELOG.md) for per-version decisions.
