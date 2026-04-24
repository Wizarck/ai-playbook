# ai-playbook

Universal AI-dev norms, specs, scripts, and templates consumed via **git submodule** by every project under Arturo / Wizarck org (openTrattOS, eligia-core, palafito-b2b, future projects).

## Purpose

One repo, one source of truth for:

- How agents (Claude Code / Gemini CLI / Antigravity / Cursor) should behave across projects.
- How MCP servers are declared (SSOT `mcp-servers.yaml` + 3-layer merge).
- How secrets are scanned, prompts are filtered, specs are validated.
- How `AGENTS.md` is structured (`schema: agents-md/v1`).
- How dispatchers chain (project `AGENTS.md` → `.ai-playbook/specs/*` → optional personal add-on).
- How break-glass works (`--force-with-reason`, logged to `overrides.log` + OTel).
- How we trace agent calls (OTel `gen_ai.*` semconv + Langfuse backend).
- How retros, upstream syncs, issue tracking, and zero-touch automations flow.

## Scope & philosophy

- **LLM-agnostic.** Norms live in `AGENTS.md` + `specs/`; CLI-specific routers (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/*.mdc`) are thin pointers.
- **Dispatch-file architecture.** Lean root docs; anything >10 lines gets a pointer to a `specs/` detail.
- **Dogfooding.** This repo uses its own schema, pre-commit hooks, and scripts.
- **Do not assume.** Missing data escalates to `❓ CLARIFICATION NEEDED`, never fills with guesses.
- **Cross-platform.** Scripts are Python 3.11+, no bash-isms. Windows native + macOS + Linux + WSL2 all supported.

## Directory map

```
ai-playbook/
├── AGENTS.md                    # self-hosted dispatcher (agents working ON this repo)
├── CHANGELOG.md                 # semver history
├── FEEDBACK.md                  # low-friction gripe channel (append-only)
├── MAINTAINERS.md               # who owns what
├── README.md                    # this file
├── VERSION                      # current semver tag (authoritative)
├── mcp-servers-base.yaml        # generic MCP server templates (no endpoints)
├── mkdocs.yml                   # optional MkDocs site (github.io)
├── pyproject.toml               # Python deps + [project.scripts] entry points
│
├── specs/                       # 35 normative specs (the contract surface)
│   ├── INDEX.md                 # auto-generated table of contents
│   ├── dispatcher-chain.md      # 3-level inheritance model
│   ├── agents-md-v1.schema.json # JSON Schema for AGENTS.md frontmatter
│   ├── agent-contract.md        # Task subagent I/O envelope
│   ├── agent-contract.schema.json
│   ├── bootstrap-directive.md   # canonical AGENTS.md §0 block
│   ├── break-glass.md           # --force-with-reason contract
│   ├── verdict-contract.md      # ✅ / ⚠️ / ❓ + S1–S4 rubric
│   ├── error-message-standard.md # canonical ❌ WHY/WHERE/FIX/OVERRIDE
│   ├── model-routing.md         # Haiku/Sonnet/Opus matrix + fallback chain
│   ├── degradation-modes.md     # HEALTHY / DEGRADED_* / OFFLINE
│   ├── prompt-caching.md        # stable→volatile ordering
│   ├── parallel-review.md       # Task subagent fan-out discipline
│   ├── memory-hierarchy.md      # 4 tiers + bank_id convention
│   ├── agentic-failures.md      # 12-mode failure catalog
│   ├── notification-policy.md   # 4 levels + channel contract
│   ├── notification-queue.md    # JSONL + rate limit + SMTP
│   ├── mcp-servers-schema.md    # 3-layer MCP config contract
│   ├── projects-registry.md     # ~/.ai-playbook/projects.yaml format
│   ├── env-vars.md              # AIPLAYBOOK_* / ELIGIA_* / etc namespaces
│   ├── migration-guide.md       # v0 → v1 AGENTS.md upgrade path
│   ├── runbook-bmad-openspec.md # BMAD Discovery + OpenSpec Implementation flow
│   ├── retrospective-cadence.md # post-archive / weekly / monthly
│   ├── role-matrix.md           # maintainer / reviewer / contributor / consumer
│   ├── rollout-strategy.md      # breaking-change protocol
│   ├── channels.md              # Telegram / Slack / PagerDuty wiring
│   ├── post-mortem.md           # S1 incident template contract
│   ├── slos.md                  # 6 MVP SLOs + alerting
│   ├── data-retention.md        # PII cleanup + right-to-forget
│   ├── auto-managed-sections.md # BEGIN/END marker pattern
│   ├── upstream-sync.md         # fork governance + rebase cadence
│   ├── skills-registry.md       # skills discovery contract
│   ├── issue-tracking.md        # Jira (enterprise) + GH Projects (community)
│   ├── incident-response.md     # deferred — activates at first paying client
│   └── taxonomy.md              # canonical glossary
│
├── scripts/                     # ~24 Python scripts, cross-platform stdlib-first
│   ├── _break_glass.py          # shared --force-with-reason helper
│   ├── bootstrap.py             # init new consumer project (534 lines)
│   ├── discover_projects.py     # scan disk + write ~/.ai-playbook/projects.yaml
│   ├── schema_validate.py       # AGENTS.md ↔ agents-md-v1 schema
│   ├── openspec_validate.py     # OpenSpec change validator
│   ├── verdict_lint.py          # QA artefact + error shape linter
│   ├── block_manual_spec_edit.py # pre-commit: refuse openspec/specs hand-edits
│   ├── secrets_scan.py          # regex + gitleaks
│   ├── prompt_injection_filter.py # regex layer-1 + LLM judge layer-2
│   ├── drift_check.py           # playbook ↔ consumer AGENTS.md duplication
│   ├── auto_managed.py          # regen BEGIN/END marker sections
│   ├── doctor.py                # prereq checker + --context-budget
│   ├── cost_report.py           # events.jsonl → cost summary
│   ├── lifecycle_check.py       # monthly retro skeleton generator
│   ├── inject_context.py        # Hindsight recall for session-start hook
│   ├── log_event.py             # JSONL emitter + OTel span
│   ├── gen_indexes.py           # auto-generate specs/INDEX.md etc.
│   ├── deprecation_watcher.py   # model EOL tracker
│   ├── upstream_sync.py         # fork rebase + PATCHES.md diff triage
│   ├── skills_registry.py       # dynamic skills discovery client
│   ├── notify.py                # JSONL queue + SMTP fan-out
│   ├── issue_sync.py            # Jira / GH Issues auto-creation
│   ├── release_cut.py           # semver tag → GH Release / Jira fixVersion
│   ├── mcp/
│   │   ├── validate.py          # 3-layer yaml ↔ .mcp.json drift check
│   │   └── render.py            # yaml → native configs (claude/gemini/cursor)
│   └── tracing/
│       ├── otel_setup.py        # gen_ai.* semconv bootstrap
│       └── trace_emit.py        # span context manager + attribute helpers
│
├── templates/                   # scaffolds for new consumers
│   ├── new-project/             # full consumer repo skeleton
│   │   ├── AGENTS.md.tmpl
│   │   ├── CLAUDE.md.tmpl       GEMINI.md.tmpl
│   │   ├── .cursor/rules/00-dispatcher.mdc.tmpl
│   │   ├── .mcp.json.tmpl       mcp-servers.yaml.tmpl
│   │   ├── .claude/settings.json.tmpl
│   │   ├── .pre-commit-config.yaml.tmpl
│   │   ├── .github/workflows/{issue-sync,release-cut}.yml.tmpl
│   │   ├── docs/runbook.md.tmpl
│   │   └── .gitattributes
│   ├── retro/                   # post-archive / weekly / monthly retro templates
│   └── PATCHES.md.tmpl          # per-fork patch inventory
│
├── docs/                        # long-form docs, MkDocs-friendly
│   ├── start-here.md            # 60-second orientation (read this first)
│   ├── quickstart.md            # 25–40 min consumer walkthrough
│   ├── quickstart-lessons.md    # real friction from dry-runs, per OS
│   ├── bootstrap-new-project.md # scripts/bootstrap.py contract
│   ├── contributing.md          # governance + RFC process (friendly)
│   ├── curriculum.md            # 4-week onboarding plan
│   ├── fork-inventory.md        # all Wizarck forks tracked
│   ├── session-start-hook.md    # CLI-specific wiring (Claude / Gemini / etc)
│   ├── architecture-diagrams.md # Mermaid flow diagrams
│   ├── why-these-choices.md     # rationale
│   ├── zero-touch-automation.md # issue-sync + release-cut + notify loop
│   └── model-migration.md       # deferred — activates at first retirement
│
├── routers/                     # CLI router examples
│   ├── CLAUDE.md.example
│   ├── GEMINI.md.example
│   └── cursor-rules.example
│
├── rfcs/                        # proposals for breaking changes
│   └── README.md                # RFC template + process
│
├── runbooks/                    # AI-executable ops procedures
│   ├── INDEX.md                 # table of runbooks + when to run
│   ├── release.md               # cut a semver tag → auto-propagates PRs
│   ├── rotate-secrets.md        # PAT / SMTP / ATLASSIAN rotation
│   └── propagate-bump-troubleshooting.md  # debug failing propagation Action
│
└── tests/                       # 27 test files, 504 tests passing
    ├── test_bootstrap.py        test_doctor.py  test_drift_check.py
    ├── test_mcp_validate.py     test_mcp_render.py
    ├── test_schema_validate.py  test_verdict_lint.py
    ├── test_prompt_injection_filter.py  test_secrets_scan.py
    └── ...
```

## How consumers use it

| Repo | How it consumes |
|---|---|
| `openTrattOS` | `.ai-playbook/` as git submodule, semver-pinned. |
| `eligia-core` | `.ai-playbook/` as git submodule + `ELIGIA.md` personal add-on. |
| New projects | Run `python <playbook>/scripts/bootstrap.py --project-name X --owner Y` from a fresh repo. |

Each consumer pins its own semver tag — see [`~/.ai-playbook/projects.yaml`](specs/projects-registry.md) for the current inventory per dev machine. Upgrading is opt-in; run `python <playbook>/scripts/bump_consumers.py --tag vX.Y.Z` to batch-bump every registered consumer.

## Getting started

1. **New consumer project**: see [docs/bootstrap-new-project.md](docs/bootstrap-new-project.md).
2. **Working inside this repo**: see [AGENTS.md](AGENTS.md).
3. **Onboarding a dev**: [docs/start-here.md](docs/start-here.md) → [docs/quickstart.md](docs/quickstart.md) → [docs/curriculum.md](docs/curriculum.md).
4. **Contributing a spec / script**: [docs/contributing.md](docs/contributing.md) + [rfcs/README.md](rfcs/README.md) for breaking changes.
5. **Running an operation** (cutting a release, rotating a secret, debugging a failed Action): [runbooks/INDEX.md](runbooks/INDEX.md).

## Versioning

Semver on the `master` branch. Consumers pin to a released tag, never `master`. Breaking changes require an RFC and a major bump (see [specs/rollout-strategy.md](specs/rollout-strategy.md)).

Current: see [`VERSION`](VERSION).

## Status

**v0.2.0 — MVP deployed.** All core specs at v1.0.0, 504 tests passing, zero-touch automations (issue-sync + release-cut + notifications) live via GitHub Actions + k3s CronJobs, SMTP verified end-to-end. Deferred-by-design items (full incident-response runbook, model-migration playbook, Phase 5 dynamic model routing) activate at their documented triggers.

## Maintainer

See [`MAINTAINERS.md`](MAINTAINERS.md).

## License

Internal to Wizarck org. Content may be relicensed (MIT or compatible) once a public release is cut; consumers that ship under AGPL-3.0 (`openTrattOS`) receive only the submodule snapshot, which is compatible with AGPL so long as the playbook is permissively licensed at public-release time.
