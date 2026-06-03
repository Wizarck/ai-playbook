---
schema: agents-md/v1
version: 0.1.0
inherits_from: []
updated: 2026-04-22
project: ai-playbook
owner: 23051550+Wizarck@users.noreply.github.com
capabilities_map: true
---

# ai-playbook — self-hosted dispatcher

Read by agents working **ON** this repo (not consumers). Consumers read own project's `AGENTS.md`, inheriting from playbook via `.ai-playbook/specs/*`.

## 0 Bootstrap directive

Agents editing this repo MUST:
1. Read `docs/concepts/dispatcher-chain.md` — inheritance + override semantics.
2. Read `specs/agents-md-v1.schema.json` — frontmatter contract before editing `AGENTS.md`.
3. Read `docs/rules/verdict-contract.rule.md` — verdict + severity rubric before QA.
4. Then act.

## 1 Project identity

`ai-playbook` = universal norms + tooling repo. Submoduled by every consumer project. LLM-agnostic. Dogfoods own pre-commit + schema.

## 2 Dispatcher index

| Topic | Pointer |
|---|---|
| **Canonical entry point — how to make any change** | [docs/concepts/development-flow.md](docs/concepts/development-flow.md) |
| Inheritance model | [docs/concepts/dispatcher-chain.md](docs/concepts/dispatcher-chain.md) |
| Projects registry (path resolution) | [docs/concepts/projects-registry.md](docs/concepts/projects-registry.md) |
| AGENTS.md schema | [specs/agents-md-v1.schema.json](specs/agents-md-v1.schema.json) |
| Taxonomy (agent/tool/skill/hook/…) | [docs/concepts/taxonomy.md](docs/concepts/taxonomy.md) |
| Verdict + severity contract | [docs/rules/verdict-contract.rule.md](docs/rules/verdict-contract.rule.md) |
| Merge style rules | [docs/concepts/merge-policy.md](docs/concepts/merge-policy.md) |
| Conflict resolution across parallel PRs | [docs/rules/conflict-resolution-policy.rule.md](docs/rules/conflict-resolution-policy.rule.md) |
| Degradation modes | [docs/concepts/degradation-modes.md](docs/concepts/degradation-modes.md) |
| Agentic failure catalog | [docs/concepts/agentic-failures.md](docs/concepts/agentic-failures.md) |
| Model routing matrix | [docs/concepts/model-routing.md](docs/concepts/model-routing.md) |
| Prompt caching rules | [docs/concepts/prompt-caching.md](docs/concepts/prompt-caching.md) |
| Parallel review discipline | [docs/concepts/parallel-review.md](docs/concepts/parallel-review.md) |
| Memory hierarchy | [docs/concepts/memory-hierarchy.md](docs/concepts/memory-hierarchy.md) |
| Agent contract (I/O) | [docs/concepts/agent-contract.md](docs/concepts/agent-contract.md) |
| Error message standard | [docs/rules/error-message-standard.rule.md](docs/rules/error-message-standard.rule.md) |
| Break-glass (`--force-with-reason`) | [docs/rules/break-glass.rule.md](docs/rules/break-glass.rule.md) |
| Env var namespace | [docs/concepts/env-vars.md](docs/concepts/env-vars.md) |
| MCP servers schema | [docs/concepts/mcp-servers-schema.md](docs/concepts/mcp-servers-schema.md) |
| Notification policy | [docs/concepts/notification-policy.md](docs/concepts/notification-policy.md) |
| Migration guide (v0→v1) | [docs/concepts/migration-guide.md](docs/concepts/migration-guide.md) |
| Retrospective cadence | [docs/concepts/retrospective-cadence.md](docs/concepts/retrospective-cadence.md) |
| Caveman feature (concept) | [docs/concepts/caveman-mode.md](docs/concepts/caveman-mode.md) |
| Caveman toggle (runbook) | [docs/runbooks/caveman-toggle.md](docs/runbooks/caveman-toggle.md) |
| Caveman architecture + UI contract | [docs/operations/caveman-architecture.md](docs/operations/caveman-architecture.md) |

## 3 Active work

Tracked in project plan outside repo. Current tag: see [`VERSION`](VERSION). Core specs + scripts v1.0.0. Deferred-by-design entries (e.g. `incident-response.md`, `model-migration.md`) declare activation trigger in header.

## 4 Hard rules (this repo only)

- **Never edit `specs/*.md` without first verifying `agents-md-v1.schema.json` does not enforce structure** — broken schema = broken consumers.
- **Scripts cross-platform Python 3.11+.** No bash-isms. Use `pathlib`, never `os.path.join` with hardcoded separators.
- **Every script has matching `tests/test_*.py`.** PR merges block on coverage drop.
- **Conventional commits** here (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **Semver.** Breaking changes (schema bump, dispatcher semantics) = major. RFC under `rfcs/` first.

## 5 Capability map

| Need | How |
|---|---|
| Validate an `AGENTS.md` frontmatter | `python scripts/schema_validate.py <path>` |
| Render MCP configs for a consumer | `python scripts/mcp/render.py --project <name>` |
| Scan for leaked secrets | `python scripts/secrets_scan.py` |
| Run pre-commit locally | `pre-commit run --all-files` |
| Emit a trace event | `python scripts/log_event.py` (see `scripts/tracing/`) |
| Rollback to pre-refactor state | `git checkout baseline` |
| Discover local projects / populate registry | `python -m scripts.discover_projects` |
| List current registry | `python -m scripts.discover_projects --list` |
| Cut new playbook release | [docs/runbooks/release.md](docs/runbooks/release.md) |
| Rotate secret (PAT / SMTP / ATLASSIAN) | [docs/runbooks/rotate-secrets.md](docs/runbooks/rotate-secrets.md) |
| Debug failed propagation Action | [docs/runbooks/propagate-bump-troubleshooting.md](docs/runbooks/propagate-bump-troubleshooting.md) |

## 6 MCP sources

No MCP servers specific to this repo (spec/tooling repo, not runtime). Consumers declare MCP servers in own `mcp-servers.yaml`, validated against `docs/concepts/mcp-servers-schema.md`.

## 7 Overrides inherited from playbook

N/A — this IS the playbook.

## 8 Gotchas

Empty at v0.1.0. Populated as operational knowledge accrues.

## 9 Rule Map (D3 signal #4)

Every `docs/rules/<slug>.rule.md` slug, grouped by `status:`. Hand-curated in Slice 5.F; refreshed Slice 6 (14 new hardrules) + Slice 7 (5 new + 5 advisory downgrades). Deferred-hardrules allowlist empty at v0.18.3.

### Enforced (paired hardrule on disk)

- [agentic-failure-catalog-schema](docs/rules/agentic-failure-catalog-schema.rule.md)
- [ai-reviewer-signoff](docs/rules/ai-reviewer-signoff.rule.md)
- [alembic-migration-naming](docs/rules/alembic-migration-naming.rule.md)
- [alembic-single-head](docs/rules/alembic-single-head.rule.md)
- [apply-skill-enforcement](docs/rules/apply-skill-enforcement.rule.md)
- [auto-merge-discipline](docs/rules/auto-merge-discipline.rule.md)
- [auto-pr-stream-closure](docs/rules/auto-pr-stream-closure.rule.md)
- [bare-layout](docs/rules/bare-layout.rule.md)
- [bootstrap-directive](docs/rules/bootstrap-directive.rule.md)
- [break-glass](docs/rules/break-glass.rule.md)
- [claude-settings](docs/rules/claude-settings.rule.md)
- [cleanup-on-bump](docs/rules/cleanup-on-bump.rule.md)
- [cleanup-zombies](docs/rules/cleanup-zombies.rule.md)
- [cross-slice-additive-extension](docs/rules/cross-slice-additive-extension.rule.md)
- [delegated-shipping-prompt](docs/rules/delegated-shipping-prompt.rule.md)
- [dispatcher-cursor](docs/rules/dispatcher-cursor.rule.md)
- [dispatcher-gemini](docs/rules/dispatcher-gemini.rule.md)
- [doc-drift-enforcement](docs/rules/doc-drift-enforcement.rule.md)
- [english-only-docs](docs/rules/english-only-docs.rule.md)
- [error-message-standard](docs/rules/error-message-standard.rule.md)
- [gemini-session-start](docs/rules/gemini-session-start.rule.md)
- [github-project-board-schema](docs/rules/github-project-board-schema.rule.md)
- [gitignore-entries](docs/rules/gitignore-entries.rule.md)
- [install-playbook](docs/rules/install-playbook.rule.md)
- [link-integrity](docs/rules/link-integrity.rule.md)
- [mcp-render](docs/rules/mcp-render.rule.md)
- [migration-slot-reservation](docs/rules/migration-slot-reservation.rule.md)
- [openspec-apply-enforcement](docs/rules/openspec-apply-enforcement.rule.md)
- [openspec-scaffold](docs/rules/openspec-scaffold.rule.md)
- [output-completeness](docs/rules/output-completeness.rule.md)
- [pr-tracker-reference](docs/rules/pr-tracker-reference.rule.md)
- [pre-commit-hooks](docs/rules/pre-commit-hooks.rule.md)
- [registry-entry](docs/rules/registry-entry.rule.md)
- [secrets-handling](docs/rules/secrets-handling.rule.md)
- [skills-sync](docs/rules/skills-sync.rule.md)
- [subagent-envelope-schema](docs/rules/subagent-envelope-schema.rule.md)
- [update-documentation](docs/rules/update-documentation.rule.md)
- [update-playbook](docs/rules/update-playbook.rule.md)
- [verdict-contract](docs/rules/verdict-contract.rule.md)
- [verification-before-completion](docs/rules/verification-before-completion.rule.md)

### Advisory (paired_hardrule: null per `docs/concepts/enforcement-pairing-exceptions.md`)

- [apply-fix-contract](docs/rules/apply-fix-contract.rule.md) — consumer-side surface (Slice 7).
- [caveman-reinforce](docs/rules/caveman-reinforce.rule.md) — per-turn UserPromptSubmit nudge when caveman is ON; silent-fail; never blocks.
- [conflict-resolution-policy](docs/rules/conflict-resolution-policy.rule.md)
- [data-handling](docs/rules/data-handling.rule.md)
- [hitl-approval-pattern](docs/rules/hitl-approval-pattern.rule.md) — consumer-side surface (Slice 7).
- [notification-channel-adapter](docs/rules/notification-channel-adapter.rule.md) — consumer-side surface (Slice 7).
- [notification-level-declared](docs/rules/notification-level-declared.rule.md) — consumer-side surface (Slice 7).
- [notification-no-secrets](docs/rules/notification-no-secrets.rule.md) — consumer-side surface (Slice 7).
- [parallel-wave-anti-collision](docs/rules/parallel-wave-anti-collision.rule.md)
- [slice-preflight](docs/rules/slice-preflight.rule.md)
- [verify-existing-patterns](docs/rules/verify-existing-patterns.rule.md)

### Hardrule deferred (paired_hardrule named, .py ships in a later slice)

Empty at v0.18.3. Deferred-hardrules allowlist file removed in Slice 7; strict-mode validator now exits 0 with no allowlist.

<!-- BEGIN auto-managed: caveman/ruleset:full -->
**Caveman mode: ON · intensity full**

Core rules:
- Drop articles (a/an/the), filler (just/really/basically), pleasantries, hedging.
- Fragments OK. Short synonyms. Technical terms exact. Code unchanged.
- Pattern: `[thing] [action] [reason]. [next step].`
- Not: "Sure! I'd be happy to help you with that."
- Yes: "Bug in auth middleware. Fix:"

Mode (full):
Drop articles. Fragments OK. Short synonyms. Technical terms exact. Code unchanged. Pattern: `[thing] [action] [reason]. [next step].` Default mode — about 65% output reduction.

Auto-clarity exceptions:
Drop caveman mode and use normal prose when:
- **Security warnings** — full sentences so the user does not misread risk.
- **Irreversible action confirmations** — `rm -rf`, `git push --force`, drop database, force-merge, etc.
- **Multi-step sequences** where fragment ambiguity could cause skipped or misordered steps.
- **User confused or repeating a question** — they need clearer, not shorter.

Resume caveman mode on the next turn.

Boundaries:
- Code, fenced code blocks, and tool inputs written normally — caveman applies to prose around them, not to code.
- Commit messages and PR descriptions written normally unless the user opts into `caveman-commit` or `caveman-review` skills.
- Comments inside generated code written normally.
- File paths, URLs, and identifiers preserved byte-for-byte.

Toggle off: `python -m scripts.caveman off`. Full rule: [skills/caveman/SKILL.md](skills/caveman/SKILL.md).
<!-- END auto-managed -->
