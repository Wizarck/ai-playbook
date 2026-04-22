# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

## [Unreleased] — T02 + Batch 2

### Added (Batch 2 — universal norm specs populated from stubs)
- **`specs/agents-md-v1.schema.json`** (T03a): tightened patterns (`version` semver, `inherits_from` github pins, `project` slug, `owner` email), added `$comment` rationale, `examples[]` with 2 cases.
- **`specs/migration-guide.md`** (T03b): v0→v1 procedure, warn-only stance at v0.1.x, hard-fail at v2.0, autofix contract, acme-shop worked example (before/after diff), 5 common pitfalls.
- **`specs/taxonomy.md`** (T03c): 25 entries across runtime/config/process groupings + 5 "hammered distinctions" (tool-vs-skill, hook-vs-script, subagent-vs-agent, personal-add-on-vs-project-dispatcher, dispatcher-vs-router).
- **`specs/model-routing.md`** (T04a): 9-class task taxonomy, fallback semantics (1-step silent, ≥2-step visible), provider quirks (Anthropic/Gemini/OpenRouter/Ollama), OTel attribute table.
- **`specs/degradation-modes.md`** (T04b): 5-state enum (HEALTHY/DEGRADED_CAPACITY/_QUALITY/_CONTEXT/OFFLINE), rolling-window triggers, circuit breaker (30s floor, 5min cap), composition rules, T19 dashboard contract.
- **`specs/prompt-caching.md`** (T04c): 9-tier stable→volatile rule, provider-specific mechanics (`cache_control`+5min TTL, Context Caching API+32k min, OpenAI-compat implicit, Ollama KV warmth), 6 anti-patterns, worked 3-turn example, `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` knob.
- **`specs/parallel-review.md`** (T05a): 3-layer pattern, 3 canonical prompts (Blind Hunter + Edge Case + Acceptance ≥30 lines each), triage, cost budgets (Sonnet×3 default), discipline rules.
- **`specs/agentic-failures.md`** (T05b): 12-entry catalog (hallucination, infinite_loop, prompt_injection, goal_drift, over_confidence, context_collapse, tool_selection_error, premature_completion, untracked_state_mutation, plan_mode_escape, credential_exposure, cascade_failure) with signal + detector + OTel attr + example each.
- **`specs/verdict-contract.md`** (T05c): `✅/⚠️/❓` canonical strings, S0-S4 rubric, max-2-rework SYSTEMIC escalation, `blocked-by-spec` lifecycle, 3 worked examples, interaction with break-glass.
- **`specs/memory-hierarchy.md`** (T06a): 4-tier table (session/project/durable-personal/durable-universal), `bank_id` conventions (including `*-personal` suffix), retrieval thresholds, decay policy, handoff to agent-contract.
- **`specs/agent-contract.md`** (T06b): formal input/return envelopes, field reference tables, `budget_exhausted` synthesized return, JSON Schema (draft 2020-12) inline, RBAC linkage (deferred to T18).
- **`specs/error-message-standard.md`** (T07a): canonical WHY/WHERE/FIX/OVERRIDE, field contracts, 4 worked examples, exit code table, OTel mapping, linter contract, anti-patterns.
- **`specs/break-glass.md`** (T07b): `--force-with-reason` contract, min reason length (10), OTel attrs, audit trail (local + durable + retro), shared Python helper interface, override-vs-verdict boundary (never waives S1).

### Open TODOs surfaced by subagents
- `--autofix` flag behaviour in migration-guide.md (lands with T09 scripts).
- `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` alias vs bare `ANTHROPIC_CACHE_TOKENS_MIN` (reconcile in env-vars.md during T09).
- Stable `finding_id` for same-finding detection in max-2-rework (heuristic currently; tighten when `verdict_lint.py` lands in T09).

### Added (T02-pre, pre-Batch-2)
- **Projects registry** (`specs/projects-registry.md`) — per-dev `~/.ai-playbook/projects.yaml` mapping project name → absolute path. Eliminates hardcoded paths from dispatchers.
- `scripts/discover_projects.py` — full (non-stub) implementation. Scans conventional roots + `$AIPLAYBOOK_PROJECTS_ROOTS`, finds `AGENTS.md` with `schema: agents-md/v1`, writes registry.
- `tests/test_discover_projects.py` — functional tests (10+) covering frontmatter parsing, scan filtering, registry round-trip, and CLI subcommands.
- `templates/projects.yaml.example` — reference layout.
- Schema extensions: `personal` (boolean) + `personal_addon` (path) optional frontmatter fields on `AGENTS.md`.
- Env vars: `AIPLAYBOOK_PROJECTS_FILE`, `AIPLAYBOOK_PROJECTS_ROOTS`.
- `.gitignore`: exclude `projects.yaml`, local `.ai-playbook/`, `overrides.log`.

## [0.1.0] — 2026-04-22

### Added
- Initial scaffold: directory tree, metadata, placeholder specs/scripts/tests/templates/docs.
- `baseline` branch capturing the pre-refactor state for rollback safety.
- `AGENTS.md` self-hosted dispatcher (for agents working ON the playbook itself).
- Empty pre-commit config and GitHub workflow stubs (populated in T09 / T17 / T22).

### Notes
- Content for specs (`specs/*.md`), scripts (`scripts/*.py`), and tests (`tests/*.py`) is populated by downstream tracks T02–T23. Stubs carry `TODO: populated in TXX` banners so consumers can grep for gaps.
- No LICENSE file yet. Added in T22 (governance).
