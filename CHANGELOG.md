# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

## [Unreleased] — T02 + Batches 2-9

### Added (Batch 9 — Dashboard + Skills registry, 2 parallel subagents)

**Subagent A — T19 Dashboard (consumer-d, commit `02b640a`):**
- `dashboard/backend/` FastAPI app on port 9020 (new; coexists with legacy MVP on :8090).
  - Routes: `/health`, `/api/status` (wraps `consumer-d_ops.tools.stack_health`), `/api/events` + `/api/events/kinds`, `/api/cost/month/{yyyymm}` (subprocess wrapper, 5 min in-memory cache), `/api/lifecycle/current` (file-first, `--dry-run` fallback), `/api/stream/events` (SSE tailer, 1 s poll + 15 s keep-alive).
- `dashboard/frontend/` vanilla JS single-page dashboard — header + degradation pill + 4 cards (stack health / events / cost / lifecycle). No framework / no build step.
- `dashboard/Dockerfile` — multi-stage, port 9020, curl healthcheck.
- `dashboard/tests/test_app.py` — 19 tests (all pass): SSE init+live frame, CORS, cost caching + 400-on-bad-month, lifecycle file→dry-run fallback, stack_health degradation branches.
- Manual deploy via the T18 5-step runbook; helm values bump pending Arturo.

**Subagent B — T20 Skills Registry Integration (ai-playbook `b44833c` + consumer-d-skills `6d58f20`):**
- `scripts/skills_registry.py` (~391 lines) — `list` / `show` CLI + importable `list_skills()` / `skill_by_name()`. Stdlib `urllib` only. Canonical errors; `--force-with-reason` degrades to empty list.
- `tests/test_skills_registry.py` — 26 tests (all pass; mocks `urlrequest.urlopen`).
- `specs/skills-registry.md` — purpose, API contract, scope model, caching, fallback, security, cross-refs.
- `specs/mcp-servers-schema.md` — expanded from 28-line stub to 249-line full spec (3-layer merge, field contract, skills-registry deep dive, validator/render rules, anti-patterns).
- `specs/env-vars.md` — added `SKILLS_REGISTRY_*` table.
- `consumer-d-skills/docs/api-contract.md` + `README.md` — documents the HTTP contract the playbook integration expects; the service implementation itself remains future work.

### Test suite totals (Batch 9 close)

- **ai-playbook: 359 passed, 1 skipped** (333 previous + 26 new).
- **consumer-d: 72 passed** (53 previous + 19 new).
- **consumer-d-skills: no test suite** (currently skills data + docs only).

### Open TODOs

- `consumer-d-skills` service implementation (FastAPI/Node serving `/api/v1/skills`) — spec'd, not built. Arturo or a future track owns.
- Dashboard helm deploy manifest — Arturo adds to `helm/consumer-d-stack/` following the T18 5-step runbook.



### Added (Batch 8 — live docs + LangGraph workflows, 2 parallel subagents)

**Subagent A — T17 live docs + drift (ai-playbook):**
- `scripts/drift_check.py` (~644 lines) — full implementation (was stub). 4 checks (`inherits_from` pin lag, auto-managed section staleness, spec xref drift, taxonomy term drift with 3-file noise filter). CLI `--check`, `--fix` (auto-managed only), `--force-with-reason`. Canonical errors.
- `scripts/auto_managed.py` (~562 lines) — new. Public API `compute_expected` / `find_sections` / `regenerate` / `apply_fix`. Supports 4 source shapes (universal-principles, taxonomy:runtime/config, verdict-contract:levels) + generic `<spec>:<anchor>` fallback. Idempotent; skips fenced code blocks.
- `specs/auto-managed-sections.md` — marker format, source shapes, merge strategy, anti-patterns.
- `tests/test_auto_managed.py` (24 tests) + `tests/test_drift_check.py` (18 tests, skip marker removed).
- `.github/workflows/drift-check.yml` — active weekly cron (MON 07:00 UTC) with 48-hour T18a sentinel stagger via `heartbeat-t18a.txt` mtime check.

**Subagent B — T18 LangGraph workflows backbone (consumer-d, commit `0011bb9`):**
- `langgraph-aiops/workflows/{drift_detector,retro_generator,cost_reporter,metrics_buffer,hitl}.py` — 4 propose-only workflows + shared HITL gate. Each wraps a LangGraph StateGraph; lazy-imports langgraph so tests don't hard-depend. `drift_detector` touches `.ai-playbook/heartbeat-t18a.txt` on success → closes the loop with 8A's GitHub Action stagger.
- `docs/subsystems/langgraph-workflows.md` + `docs/operations/deploy-t18-workflows.md` (5-step Blindar aiops embedded + T18 CronJob additions + 48h stagger note) + `LEGACY_MIGRATION.md`.
- `tests/test_workflows.py` — 34 new tests (consumer-d suite 53/53).

### Test suite totals (Batch 8 close)

- **ai-playbook: 333 passed, 1 skipped** (291 previous + 42 new). Remaining skip: `test_bootstrap.py` (out of scope).
- **consumer-d: 53 passed** (19 previous + 34 new).

### Deploy gate (manual)

T18 workflows are NOT live on the VPS until Arturo runs `consumer-d/docs/operations/deploy-t18-workflows.md` (5-step Blindar aiops procedure + CronJob additions). The 48h T17h stagger starts from first successful DriftDetector run (heartbeat file touched on VPS).



### Added (Batch 7 — docs hub + consumer-d-ops meta-agent, 2 parallel subagents)

**Subagent A — T16a/b/c docs hub + MkDocs (ai-playbook):**
- `mkdocs.yml` (76 lines) — Material config, slate palette, `pymdownx.*` extensions, explicit nav (Home / Start here / Onboarding / Architecture / Specs).
- `docs/index.md` — homepage with 3-column tabbed cards, 4 universal principles snapshot, links to AGENTS.md + start-here.md.
- `scripts/gen_indexes.py` (~402 lines) — walks a root, writes `INDEX.md` per folder with File / Status / Summary table + optional `## Sub-directories` section. CLI `--root`, `--check` (staleness detection for CI). Skips directories that carry a curated lowercase `index.md` (so `docs/` keeps its homepage and `specs/` gets an auto-index).
- `specs/INDEX.md` — auto-generated (21 spec entries); second `--check` run is clean.
- `tests/test_gen_indexes.py` — 22 tests (all pass).
- `pyproject.toml` — new `[project.optional-dependencies].docs` group (mkdocs, mkdocs-material, pymdown-extensions).

**Subagent B — T16c/d/e/f consumer-d-ops meta-agent (consumer-d, commit `18ad17e`):**
- `langgraph-aiops/consumer-d_ops/{__init__,server,tools,README}.py/md` — MCP stdio server + 5 read-only tools (`watchdog_status`, `recent_incidents`, `recent_retains`, `stack_health`, `suggest_remediation`).
- `docs/subsystems/consumer-d-ops.md` + `.claude/skills/consumer-d-ops/SKILL.md` — subsystem doc + skill file.
- `tests/test_consumer-d_ops.py` — 19 tests (all pass).
- `suggest_remediation` returns propose-only candidates with `command_preview` + `risk` tier; `APPLY_FIX_MODE=apply` raises `NotImplementedError("APPLY_FIX mode deferred to T29")`.
- `watchdogs.py` untouched — consumer-d-ops reads its output files only.

### Test suite totals (Batch 7 close, ai-playbook)

- **291 passed, 2 skipped, 0 failures** (269 previous + 22 new for gen_indexes).



### Added (Batch 6 — T15 cross-OS validation)

**Windows baseline — real dry-run 2026-04-23:**
- `docs/quickstart-lessons.md` fully populated with Windows timings + 4 real friction points. Total wall-clock ~18 min (inside 25–40 min quickstart band).

**macOS / Linux / WSL2 — predicted friction from static analysis:**
- macOS: `python3` vs `python` alias, Xcode CLT git prompt, `brew install sops age gitleaks`, BSD vs GNU util gotchas, APFS case-insensitivity caveat.
- Linux: `python3-full/venv/pip` on Debian, `apt install sops age`, container `$AIPLAYBOOK_PROJECTS_FILE` override, locale UTF-8 pinning.
- WSL2: `/mnt/c` filesystem boundary slowdown (10-100× vs native), line-ending cross-writes, dual-registry split between Windows Git Bash and WSL bash (fix: point both at shared path), exec-bit ghosting.

### Fixed (Batch 6)
- Added `.gitattributes` at playbook root (source files pinned to LF; `.bat/.cmd/.ps1` stay CRLF). Prevents spurious diffs on Windows clones with `core.autocrlf=true`.

### Deferred (captured for future work)
- `TODO T22`: package the playbook (`pyproject.toml [project.scripts]`) so consumers can `pip install -e .ai-playbook/` and call `ai-playbook-doctor` directly — eliminates the `ModuleNotFoundError` friction on consumer cwds.
- Full real dry-runs on macOS / Linux / WSL2 — needs real hardware; the predicted sections above are enough to ship v0.2 but will be replaced with real timings when those machines are available.



### Added (Batch 5 — EX package, 2 parallel subagents)

**Subagent A — T14a/f/i scripts (64 new tests, all pass):**
- `scripts/doctor.py` (~413 lines) — 14 prerequisite + env-var + registry health checks (`python`, `git`, `gh`, `npx`, `pre-commit`, `pyyaml`, `jsonschema`, `sops`, `gitleaks`, `playbook-submodule`, `projects-registry`, `env-vars-required`, `env-vars-alias-warning`, `context-budget`). CLI `--json`, `--strict` (warn → fail). Advisory by default — exit 0 on warnings.
- `scripts/cost_report.py` (~412 lines) — aggregates `gen_ai.usage.*` events from `.ai-playbook/events.jsonl`. CLI `--period`, `--by project|model|task_class`, `--since`, `--json`. Reads optional `pricing.yaml` for cost estimates; gracefully skips when absent.
- `scripts/lifecycle_check.py` (~471 lines) — monthly markdown report. Surfaces break-glass usages, unresolved `❓ CLARIFICATION NEEDED` (>7 days), stale OpenSpec changes (>30 days), memory-decay candidates, pending v0→v1 migrations. Flags gates overridden ≥3× in 30 days as systemic.
- Tests: `test_doctor.py` (26), `test_cost_report.py` (14), `test_lifecycle_check.py` (24).

**Subagent B — T14b/c/d/e/g/h/i-spec docs+specs (10 files, 982 lines):**
- `docs/start-here.md` — 1-pager (3-level dispatcher ASCII, first 5 commands, needs→file routing).
- `docs/quickstart.md` — 8-step honest 25–40 min walkthrough for `acme-shop` with per-step time budget + "what can go wrong" sub-sections.
- `docs/quickstart-lessons.md` — empty per-OS skeleton ready for T15 dry-run findings.
- `FEEDBACK.md` — formalised: format, triage cadence, 3 good-gripe examples, 3 anti-patterns.
- `specs/notification-policy.md` — 4 levels, rate limits, channel contract, per-event policy table (14 events).
- `docs/contributing.md` — 4-role matrix, RFC 7/30/90-day SLAs, code style + test discipline + backwards-compat (full governance lands T22).
- `templates/retro/{post-archive,weekly,monthly}.md.tmpl` — retro templates per cadence.
- `specs/retrospective-cadence.md` — 3 cadences, template mapping, output layout, automation contract for `lifecycle_check.py`, 4 anti-patterns.

### Test suite totals (Batch 5 close)

- **269 passed, 2 skipped, 0 failures** (205 previous + 64 new for doctor/cost/lifecycle).
- Remaining skip: `test_bootstrap.py` (T14a — bootstrap.py stub, NOT populated this batch; deferred to a future track).

### Open TODOs surfaced

- `cost_report.py` `--period` is a default-window shortcut, not full calendar bucketing — flagged for T19 dashboard consumer to confirm before integrating.



### Added (Batch 4 — project workflows)

**T11 — Runbook BMAD + OpenSpec:**
- `specs/runbook-bmad-openspec.md` (canonical universal runbook — 6 HITL gates A..F, phase map, BMAD Discovery artefacts + gates, OpenSpec per-artefact sequence, max-2-rework, self-validation 5-gate checklist, lifecycle state diagram, retro cadence summary).

**T12 — Context auto-inject:**
- `scripts/inject_context.py` (full implementation, ~340 lines). POST `<HINDSIGHT_URL>/recall` with `{bank_id, query, top_k}`; normalises entries/results envelopes; auto-resolves `project` + `bank_id` from consumer `AGENTS.md` frontmatter; sanitises output through `secrets_scan.sanitise` before write; writes `<consumer>/.claude/injected-context.md` with per-entry markdown blocks + metadata; `DEGRADED_CONTEXT` banner path on URL errors / timeouts / credentials missing; break-glass honoured with audit-logged override.
- `tests/test_inject_context.py` (21 tests — all pass). Covers AGENTS.md introspection, HTTP normalisation (list + envelope shapes), degraded paths (HTTPError / URLError / malformed JSON), rendering (empty / populated / degraded / error banners), sanitiser integration, CLI paths (missing creds, force-with-reason, dry-run, happy path, bank-id override).
- `docs/session-start-hook.md` — how to wire it into Claude Code `SessionStart`, Gemini CLI, Cursor, plus dry-run + break-glass docs.

**T13 — Gotcha templates:**
- `templates/gotcha.md.tmpl` — canonical public and personal gotcha entry shapes with worked examples, 6 writer rules (one-concept-per-bullet, date-stamp, why+how-to-avoid, link-to-evidence, archive-90-day, never-retain-secrets), cross-refs to `memory-hierarchy.md` / `verdict-contract.md` / `retrospective-cadence.md`.

### Test suite totals (Batch 4 close)

- **205 passed, 3 skipped, 0 failures** (184 previous + 21 new for inject_context).



### Added (Batch 3 — scripts + infra, 4 parallel subagents)

**Subagent A (T07c-f tracing):**
- `scripts/tracing/otel_setup.py` — `init_tracing(service_name, *, enable_langfuse, enable_otlp)` with dual exporters (OTLP Collector + Langfuse), `AIPLAYBOOK_TRACING_DISABLED` short-circuit, no-op fallback when OTel/Langfuse not installed.
- `scripts/tracing/trace_emit.py` — `span()` context manager + `current_trace_id()` + semconv helpers (`gen_ai_attrs`, `routing_attrs`, `degradation_attrs`, `override_attrs`).
- `scripts/log_event.py` — full JSONL logger to `.ai-playbook/events.jsonl` with OTel span emission; CLI `--name`, `--attrs`, `--trace-id`, `--pretty`.
- Tests: 25/25 pass (`test_log_event.py`, `test_tracing_setup.py`).

**Subagent B (T08 MCP SSOT pipeline):**
- `scripts/mcp/validate.py` — 3-layer YAML loader + deep merge + schema validation + env.required union check + drift detection against committed `.mcp.json` / `.gemini/settings.json`. Canonical error emitter, break-glass integration.
- `scripts/mcp/render.py` — renders `.mcp.json` (Claude Code) + `.gemini/settings.json` (Gemini/Antigravity); `--dry-run`, `--only claude|gemini`, provenance summary.
- `mcp-servers-base.yaml` — 11 well-known server templates (hindsight, litellm, guardrails-mcp, atlassian-consumer-a, google-workspace-arturo/consumer-b, trello-arturo/consumer-b, skills-registry, crm, rag).
- Tests: 28/28 pass (`test_mcp_validate.py`, `test_mcp_render.py`).

**Subagent C (T09 scripts + pre-commit + env-vars):**
- `scripts/_break_glass.py` (NEW) — shared helper per `specs/break-glass.md`. `add_break_glass_flag`, `apply_break_glass`, min reason length 10, logs to `.ai-playbook/overrides.log`.
- `scripts/schema_validate.py` — full AGENTS.md frontmatter validator + `--autofix` (inject defaults, normalise `updated`, slugify `project`, pin `inherits_from`). Honours WILL/WON'T lists from migration-guide.md.
- `scripts/openspec_validate.py` — thin wrapper around `npx @fission-ai/openspec@latest validate`. Cross-platform npx lookup.
- `scripts/verdict_lint.py` — enforces verdict literals + S1-S4 severities on artefacts; `--shape artifact|error|script-cli`; S0 audit-only; never overridable (exit 3 on `--force-with-reason`).
- `scripts/block_manual_spec_edit.py` — pre-commit hook blocking hand-edits to `openspec/specs/*.md` unless commit message carries `openspec-archive:` marker.
- `.pre-commit-config.yaml` — full hook chain (trailing-whitespace, eof-fixer, check-yaml/json, large-files 500KB, gitleaks, schema-validate, mcp-validate, block-manual-spec-edit, verdict-lint).
- `specs/env-vars.md` — fully enumerated. Resolved the `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` alias TODO (canonical wins; bare alias accepted with doctor.py warning; removal in v2.0.0).
- Tests: 60/60 pass (`test_schema_validate.py`, `test_verdict_lint.py`, `test_break_glass.py`, `test_block_manual_spec_edit.py`).

**Subagent D (T10 secrets + injection):**
- `scripts/secrets_scan.py` — 8-kind regex catalogue (anthropic/openai/github-PAT/aws-access/aws-secret/langfuse-pk/langfuse-sk/jwt/generic-env-secret). Non-overridable (`OVERRIDE: none` always). CLI modes: `<paths>`, `--staged`, `--text`, `-` (stdin), `--sanitise-for hindsight`. Gitleaks integration when `shutil.which` resolves it.
- `scripts/prompt_injection_filter.py` — 2-layer (regex + Haiku LLM-judge). Layer 2 gracefully degrades when `anthropic` package or `ANTHROPIC_API_KEY` missing. Break-glass honoured on layer-2-only fire; refused when layer 1 fires. `--json` output matches `InjectionVerdict` envelope.
- Tests: 59/59 pass (`test_secrets_scan.py`, `test_prompt_injection_filter.py`).

### Test suite totals (Batch 3 close)

- **184 passed, 3 skipped, 0 failures.**
- Skips: `test_bootstrap.py`, `test_doctor.py`, `test_drift_check.py` (populated in T14a / T17).

### Resolved Batch 2 TODOs
- `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` alias (resolved in `env-vars.md`).
- `--autofix` behaviour (shipped in `schema_validate.py`).
- Stable finding_id for max-2-rework — deferred: `verdict_lint.py` currently uses `title` substring matching; formal `finding_id` remains future work (tracked by the heuristic note in `specs/verdict-contract.md` §3).

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
