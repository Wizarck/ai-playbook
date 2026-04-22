# ai-playbook

Universal AI-dev norms, specs, scripts, and templates consumed via **git submodule** by every project that Arturo / Wizarck org works on (openTrattOS, eligia-core, future projects).

## Purpose

One repo, one source of truth for:

- How agents (Claude Code / Gemini CLI / Antigravity / Cursor) should behave across projects.
- How MCP servers are declared (SSOT `mcp-servers.yaml`).
- How secrets are scanned, prompts are filtered, specs are validated.
- How AGENTS.md is structured (`schema: agents-md/v1`).
- How dispatchers chain (project `AGENTS.md` → `.ai-playbook/specs/*`).
- How break-glass works (`--force-with-reason`).
- How we trace agent calls (OTel `gen_ai.*` semconv + Langfuse).

## Scope & philosophy

- **LLM-agnostic.** Norms live in `AGENTS.md` + `specs/`; CLI-specific routers (CLAUDE.md, GEMINI.md, .cursor/rules) are thin pointers.
- **Dispatch-file architecture.** Lean root docs; anything >10 lines gets a pointer to a `specs/` detail.
- **Dogfooding.** This repo uses its own schema, pre-commit hooks, and scripts.
- **Do not assume.** Missing data escalates to `❓ CLARIFICATION NEEDED`, never fills with guesses.

## Consumers

| Repo | How it consumes |
|---|---|
| `openTrattOS` | `.ai-playbook/` as git submodule pinned to a semver tag. |
| `eligia-core` | `.ai-playbook/` as git submodule. |
| Future projects | Bootstrap via `templates/new-project/` + submodule add. |

## Directory map

See [docs/start-here.md](docs/start-here.md) (T14) and [AGENTS.md](AGENTS.md) for the self-hosted dispatcher.

## Versioning

Semver on the `main` branch. `baseline` branch preserves the pre-refactor state (rollback safety).

Current: see [`VERSION`](VERSION).

## Status

**v0.1.0 — Scaffold.** Structure in place; content is populated by subsequent tracks (T02–T23, see project plan).

## Maintainer

See [`MAINTAINERS.md`](MAINTAINERS.md).

## License

Internal to Wizarck org. Content may be relicensed (MIT or compatible) once a public release is cut; consumers that ship under AGPL-3.0 (`openTrattOS`) receive only the submodule snapshot, which is compatible with AGPL so long as the playbook is permissively licensed at public-release time.
