# ai-playbook

> **LLM-agnostic, neuro-symbolic enforcement framework** for LLM-driven development. Every rule is one slug bound to four paired artefacts (markdown contract + Python hook + GitHub workflow + tests) so they cannot drift silently. Claude Code, Gemini CLI, and Cursor all read the same files. Ships per-project as a git submodule; configures from a double-click HTML UI.

## The drift problem this solves

LLM coding assistants follow rules you give them as prose. CI enforces rules you give it as code. Both rot, and they rot independently. The doc says "test coverage ≥ 80 %" while the workflow says ≥ 75 %. The LLM honours the doc; the merge gate uses the workflow; nobody notices until a regression ships. The playbook binds the prose, the hook, and the CI step under one slug — `scripts/validate_pairing.py` refuses to merge if any pair disagrees.

## The neuro-symbolic answer

Every rule lives at three layers, all derived from a single rubric:

- **L1 — symbolic, terminal-side** — a deterministic Python hook fires before `Edit` / `Write` / `Bash` lands. Claude Code native; other hosts degrade gracefully to L2 + L3.
- **L2 — neural, in-context** — the same rule rendered as markdown loaded into the LLM's context. Every host (Claude, Gemini, Cursor) reads the same file.
- **L3 — symbolic, server-side** — a GitHub Action runs the same validator on every PR. Required check.

This is the classic neuro-symbolic composition pattern ([IBM Research, 2023](https://research.ibm.com/blog/neuro-symbolic-ai)): the symbolic verifier owns the truth, the neural interpreter explains it. When L1 and L2 disagree, **L1 wins by contract** (decision D8). Full model: [concepts/enforcement-layers.md](concepts/enforcement-layers.md).

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

- [AGENTS.md](https://github.com/Wizarck/ai-playbook/blob/main/AGENTS.md) — the self-hosted dispatcher for agents editing THIS repo.
- [tutorials/02-start-here.md](tutorials/02-start-here.md) — the 60-second pitch, with the first 5 commands and the situation → reading matrix.
- [concepts/architecture-diagrams.md](concepts/architecture-diagrams.md) — Mermaid views of the dispatcher chain and pre-commit gates.
- [tutorials/06-why-these-choices.md](tutorials/06-why-these-choices.md) — the rationale behind every load-bearing decision.

## Status

- **Version**: see [VERSION](../VERSION) — semver pinned. Consumers absorb new tags at their own pace (pull model, no push pipeline; see the [README](../README.md#how-consumers-absorb-updates-pull-model-no-push) for the contract introduced in v0.19.0).
- **Changelog / migration notes**: see [concepts/migration-guide.md](concepts/migration-guide.md) for v0 → v1 procedure and [../CHANGELOG.md](../CHANGELOG.md) for per-version decisions.
