# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

## [0.4.0] — 2026-04-26 — skills distribution: copy-paste → semver-pinned submodule

Implements [RFC-0001](rfcs/RFC-0001-skills-distribution.md). Skills now ship
with the same audit/versioning posture the playbook itself enjoys: source repos
(`ai-playbook`, `consumer-d-skills`) cut independent semver tags; consumers pin per
source via `AGENTS.md.skills_sources` + `consumers.yaml.skills_pins`; bootstrap
materialises content via git submodule sparse-checkout into a vendor-neutral
`<consumer>/skills/` path; per-LLM mirrors at `.claude/skills/` and
`.gemini/skills/` are gitignored copies regenerated deterministically.

The HTTP registry at `consumer-d-skills.consumer-bfood.com` keeps its discovery role
(catalog of `{name, description, scope, version, source, updated}`) — content
distribution moves to git, where it belongs. The `source` field in the catalog
now points to the canonical pin (`<owner>/<repo>@<tag>:skills/<name>/`).

### Added

- `skills/` (1067 files) — canonical methodology skills tree under the playbook
  itself, populated from `consumer-c-legacy/.claude/skills/` (the de-facto canonical
  copy). 65 BMAD agents/workflows/QA + 4 OpenSpec commands = 69 skills.
- `rfcs/RFC-0001-skills-distribution.md` — full design rationale, alternatives
  considered, KPIs, FRs/NFRs, migration recipe per consumer.
- `specs/skills-distribution.md` — formal contract for the new distribution
  surface (canonical layout, pinning model, materialisation algorithm, drift
  detection, propagation, fallback, security, KPIs).
- `runbooks/skills-version-bump.md` — maintainer procedure for cutting a tag
  on a source repo and walking it through the propagation workflow PR-by-PR.
- `scripts/_skills_materialiser.py` (533 LOC) — idempotent submodule
  sparse-checkout + merge + per-LLM mirror copy. Public entry point
  `materialise_skills(consumer_dir, dry_run=False) → SkillsMaterialisationResult`.
- `scripts/propagate_skills_bump.py` (380 LOC) — sibling of
  `propagate_bump.py`; opens consumer PRs on a skills source-repo tag push.
  Line-level regex edit of `AGENTS.md` + `consumers.yaml` (no whole-file
  rewrites; preserves YAML comments and ordering).
- `scripts/validate_skills_mirror.py` (180 LOC) — pre-commit hook detecting
  drift between `<consumer>/skills/` and `<consumer>/.claude/skills/` /
  `.gemini/skills/`. `--fix` regenerates; report-only otherwise. No-op for
  pre-migration consumers (silent until the consumer migrates).
- `.github/workflows/propagate-skills-bump.yml` — fires on tag push or
  `repository_dispatch` event `skills-tag-pushed`; per-consumer PR fan-out.
- `.pre-commit-hooks.yaml` — exposes `validate-skills-mirror` as a public
  pre-commit hook (consumers add `repo: <playbook-url>` to their
  `.pre-commit-config.yaml`).
- `tests/test_skills_materialiser.py` (17 tests), `tests/test_propagate_skills_bump.py`
  (16 tests), `tests/test_validate_skills_mirror.py` (12 tests) — 45 new tests
  total covering happy path + edge cases (missing AGENTS.md, malformed source
  refs, idempotency, name collisions, partial mirror state, drift detection,
  --fix regeneration).

### Changed

- `specs/skills-registry.md` bumped to v2.0.0: scope clarified to
  **discovery-only** (catalog metadata, never content). The `source` field
  format changes to canonical pin (`<owner>/<repo>@<tag>:skills/<name>/`).
- `scripts/bootstrap.py`: new `--refresh-skills` flag re-runs only the
  materialisation step without redoing the full bootstrap. Skills
  materialisation is wired as step 4.5 of the normal bootstrap flow (warns
  but does not abort if materialisation fails — skills remain opt-in for
  pre-migration consumers).
- `consumers.yaml`: schema gains optional `skills_pins` field (dict of
  `<source-repo-slug>: <git-ref>`). No existing consumer rows modified.
- `consumer-d-skills` (companion repo): catalog moves from root to
  `consumer-d-skills/skills/` (68 git-mv'd renames at 100% similarity, history
  preserved). `Dockerfile` env updated (`SKILLS_CATALOG_DIR=/app/skills`,
  scoped `COPY skills`). README + `docs/api-contract.md` reflect the new
  canonical layout. Backend (`backend/`), tests (`tests/`), docs (`docs/`),
  `claude-plugins-official/` and `hindsight/` stay at root. consumer-d-skills cut
  as v0.2.0 in parallel with this playbook release.

### Deprecated

- `Wizarck/skills-manager-personal` — frozen since 2026-04-07, content
  identical to `consumer-d-skills` for shared skills, no installer remaining
  (CLI lived on a now-decommissioned PC). Will be archived on GitHub as part
  of Phase 5.

### Verified

- 568 unit tests pass globally (45 new + 523 pre-existing); 2 skipped E2E
  guard `AIPLAYBOOK_E2E=1`. The 2 pre-existing failures in
  `tests/test_issue_sync.py` (`consumer-b → consumer-a` mapping) are unrelated
  to this release — verified to fail also at parent commit `01fccf9`.
- Smoke test (Win11 Pro, Git Bash + native PowerShell): bootstrap dry-run +
  live materialisation + drift inject + `--fix` regen + drift re-check all
  pass per `runbooks/skills-version-bump.md` smoke recipe.
- `consumer-d-skills` test suite (21 tests) green post-restructure. Catalog
  smoke test detects 64 valid skills with `SKILLS_CATALOG_DIR=./skills` (4
  pre-existing broken-frontmatter skills are tracked as backlog cleanup).

### Migration

Consumers migrate one at a time via the per-consumer recipe in
[`rfcs/RFC-0001-skills-distribution.md` §"Per-consumer migration recipe"](rfcs/RFC-0001-skills-distribution.md).
The recipe is mechanical: `git rm -r .claude/skills/`, add `skills_sources`
to `AGENTS.md`, run `bootstrap.py --refresh-skills`, smoke-test a key skill,
commit. Consumers that have not migrated continue working with their
pre-RFC-0001 copy-pasted skills.

## [0.3.1] — 2026-04-26 — onboarding flow for new consumer projects

User question: "I have a brand-new repo, how do I anex it to ai-playbook?"
The pieces existed (bootstrap.py, templates/new-project/) but were
incomplete: no SessionStart hook template, no v1 mcp-servers.project.yaml
template, no Cursor router, no consumers.yaml registration, no rendered
.mcp.json. A canonical end-to-end onboarding runbook was missing.

This release ships the complete one-command onboarding flow.

### Added

- `templates/new-project/CLAUDE.md.tmpl` — thin Claude Code router pointing at AGENTS.md.
- `templates/new-project/.claude/settings.json.tmpl` — SessionStart hook with `--bank-id {{PROJECT_BANK}}` and 60 s timeout for cold Hindsight recall.
- `templates/new-project/mcp-servers.project.yaml.tmpl` — v1 layer file declaring the Hindsight server with the project's bank id.
- `templates/new-project/.cursor/rules/00-dispatcher.mdc.tmpl` — Cursor thin router (alwaysApply: true).
- `templates/new-project/.gitignore.tmpl` — playbook integration entries (overrides.log, hindsight-queue.jsonl, etc).
- `runbooks/onboard-new-project.md` — canonical one-page procedure: `gh repo create` → `bootstrap.py --register-in <playbook>` → 3 placeholders in AGENTS.md → 2 commits → done. Covers SOPS path overrides, rollback, and the verification suite.

### Changed

- `templates/new-project/AGENTS.md.tmpl` — bumped pin from `v0.1.0` → `v0.3.0`, rewrote §0 bootstrap directive to match the post-v0.3.0 file-based delivery (§2 says "Consult `.claude/injected-context.md`" via SessionStart hook), expanded §5 capability map with retain CLI + drift check + memory hierarchy pointers.
- `scripts/bootstrap.py`:
  - New `{{PROJECT_BANK}}` placeholder substituted with `project_name.lower()` for SessionStart hook + mcp-servers.project.yaml.
  - New `render_mcp_configs()` step runs `mcp/render.py` after templates land — produces `.mcp.json` + `.gemini/settings.json` automatically.
  - New `--register-in <playbook-path>` flag appends a row to `<playbook>/consumers.yaml` (idempotent; skips if already present). The dev still commits + pushes the playbook change.
  - New `--visibility public|private` and `--default-branch <name>` flags feed the consumers.yaml row.
  - `print_next_steps` updated with the registered/non-registered branches.
  - Default playbook pin bumped from `v0.1.0` → `v0.3.0`.

### Verified

- 550 unit tests pass.
- Dry-run on a fake project copies 18 template files (was 14 in v0.3.0) including the 5 new templates above.
- `--register-in` dry-run leaves `consumers.yaml` unchanged.

## [0.3.0] — 2026-04-25 — architectural review fixes + template-readiness

Substantive structural changes from a software + agentic-architect review.
Theme: preserve everything that worked, eliminate personal-namespace leak,
make the framework template-ready for forks, mark spec-vs-wired status
honestly, close the manual-vs-automation script duplication.

### Added

- `specs/enforcement-status.md` — full matrix of every spec with one of
  ✅ wired / 🟡 partial / 📋 spec-only / 📌 deferred status. Three most
  aspirational specs (`agent-contract.md`, `parallel-review.md`,
  `agentic-failures.md`) carry banner pointers to it. Lets future
  contributors know which rows are framework definitions vs harness-
  enforced contracts.
- `scripts/check_mcp_drift.py` (197 LOC) + `tests/test_check_mcp_drift.py`
  (10 tests) — detects drift between a consumer's legacy `mcp-servers.yaml`
  SSOT and the playbook v1 layer file `mcp-servers.project.yaml`. Skips
  fields where only one side declares a value (asymmetric tracking ≠ drift).
  CLI `--json` for CI; `--force-with-reason` for intentional staging
  divergence.
- `scripts/_bumper.py` — shared submodule-bump primitives consumed by both
  `bump_consumers.py` (manual) and `propagate_bump.py` (CI). Centralises
  the commit message template, branch name pattern, tag→SHA resolution.
- `scripts/init_org.py` (190 LOC) + `tests/test_init_org.py` (8 tests) —
  parametrises a fresh fork for a new org. Walks the worktree, applies a
  set of substitutions (`Wizarck/* → <org>/*`, Hindsight URL, SOPS path,
  owner email), resets `consumers.yaml` to a stub. Dry-run mode for review
  before write. Lets a third party clone the playbook + run one command to
  re-skin it for their stack.
- `scripts/retain_memory.py` — canonical name for the retain CLI (handles
  every `kind`: lesson/gotcha/decision/failure/fact). Tests migrated under
  `tests/test_retain_memory.py` (7 tests).
- `templates/mcp-servers-personal.yaml.example` — starter template for the
  personal layer at `~/.config/mcp-servers.yaml`. Documents the
  `<server>-<tenant>` naming convention with commented examples for
  Atlassian, Google Workspace, Trello, Camoufox.
- `tests/test_propagate_bump.py` (8 tests) — covers the CI-side propagation
  script. Mocks subprocess; verifies idempotency (skip if PR open),
  no-submodule skip, up-to-date skip, error path on clone failure.
- `tests/integration/test_e2e_loop.py` — env-gated end-to-end Hindsight
  loop test. Requires `AIPLAYBOOK_E2E=1` + creds. Posts a sentinel,
  polls recall until it surfaces (Hindsight indexing is async).
- `.github/workflows/docs-deploy.yml` — publishes the MkDocs site to
  GitHub Pages on every tag push + main push.

### Changed (BREAKING — see Migration below)

- `mcp-servers-base.yaml` — restructured. Removed tenant-named entries
  (`google-workspace-arturo`, `trello-arturo`, `atlassian-consumer-a`, etc).
  Base now ships only generic templates (`atlassian`, `google-workspace`,
  `trello`) plus truly universal servers (`hindsight`, `litellm`,
  `guardrails-mcp`, `skills-registry`, `crm`, `rag`). Tenant-named
  instances live in the personal layer.
- `scripts/retain_lesson.py` → `scripts/retain_memory.py`. The old name
  remains as a deprecation shim that re-exports + emits a `DeprecationWarning`;
  will be removed in v1.0.0. Update invocations:
  `python -m scripts.retain_memory ...`.
- `specs/bootstrap-directive.md` — rewritten to reflect SessionStart-hook
  reality. Step 2 now says "Consult `.claude/injected-context.md`"
  (populated by the auto-fired hook BEFORE the session starts) instead of
  the deprecated "Call MCP `hindsight.recall`" wording (the MCP tool isn't
  loaded in vanilla Claude Code sessions; the file-based delivery is canon).
  Consumer AGENTS.md files updated.
- `consumer-d/mcp-servers.yaml` — `hindsight` entry's `url` no longer
  includes the deprecated `/mcp/consumer-d/` path; aligned with the v1 layer
  file. `notes` field documents that REST API uses
  `/v1/default/banks/{bank}/...`.
- `scripts/mcp/validate.py` already accepts `mcp-servers.project.yaml` as
  the v1-explicit alternative; no change here, just confirming the flow.

### Removed

- `routers/CLAUDE.md.example`, `routers/GEMINI.md.example`,
  `routers/cursor-rules.example` — dead weight. Canonical templates live
  at `templates/new-project/CLAUDE.md.tmpl` etc; the `routers/` examples
  were never updated and never referenced.

### Migration (consumer + dev impact)

For consumers (consumer-c-legacy, consumer-d, consumer-b): nothing breaks.
The propagation Action handles the submodule bump as usual.

For devs invoking scripts directly:

    OLD: python -m scripts.retain_lesson --bank ... --content ...
    NEW: python -m scripts.retain_memory  --bank ... --content ...

The shim still works through v0.x; will emit a stderr warning. Update
your runbook bookmarks + shell aliases.

For YOUR personal layer (`~/.config/mcp-servers.yaml`): no change — your
existing entries (`google-workspace-arturo`, `trello-consumer-b`, etc) keep
working. They're now solely in the personal layer instead of being
duplicated as `scope: universal` in the base.

For forks of the playbook (third parties): you can now run
`python -m scripts.init_org --org-name <yours> --owner-email <email>`
to re-skin the fork in one command instead of finding-and-replacing
across 6+ files.

### Verified

- 550 unit tests pass (was 522 in v0.2.3); +28 new tests across
  check_mcp_drift, propagate_bump, init_org, retain_memory shim.
- `scripts/check_mcp_drift.py --consumer-root /c/Projects/consumer-d`
  reports `✅ no drift across 1 server(s)` after the legacy yaml
  endpoint cleanup.
- `scripts/init_org.py --org-name acme --dry-run` produces a clean
  25-replacement plan touching exactly 4 files; no specs/* drift.
- Re-rendered `.mcp.json` for consumer-c-legacy shows 9 generic servers (was
  11 incl. `*-arturo` leak in v0.2.3).

## [0.2.3] — 2026-04-25 — consumer-b onboarded + consumer-d mcp render + hook validated

### Added

- `consumer-b/` (third active consumer) — `.ai-playbook/` submodule pinned to v0.2.2; `AGENTS.md` (v1 dispatcher); `mcp-servers.project.yaml` (project layer with `consumer-b` bank); `.claude/settings.json` (SessionStart hook); `.mcp.json` + `.gemini/settings.json` rendered. `consumers.yaml` updated.
- `consumer-d/mcp-servers.project.yaml` — playbook-side project layer for the render pipeline. The legacy `mcp-servers.yaml` (v2-metadata SSOT for helm + desktop-stack + scripts) stays untouched; the playbook validator now resolves `mcp-servers.project.yaml` first, falls back to `mcp-servers.yaml` only when the legacy file declares `schema: mcp-servers/v1`. consumer-d's `.mcp.json` rendered (23 servers across base+project+personal).
- `runbooks/rotate-secrets.md` §"Fine-grained PAT scope" — explicit GitHub UI fields (token name, description, resource owner, expiration, repos-to-select, exact permission grants).

### Changed

- `scripts/mcp/validate.py::load_layers` — supports `mcp-servers.project.yaml` as a v1-explicit alternative filename. New helper `_resolve_project_layer_file` picks the right file per consumer; preserves backward compat for consumers using `mcp-servers.yaml` directly.

### Verified end-to-end on 2026-04-25

- SessionStart hook fires correctly: `sops exec-env ../consumer-d/secrets/secrets.env -- python .ai-playbook/scripts/inject_context.py --bank-id consumer-c-legacy` writes `injected-context.md` with 7 entries (semantic indexing breaks one retained lesson into multiple recall results, as designed).
- Retain CLI works against production: `retain_lesson.py --bank consumer-c-legacy --content "..."` lazy-creates the bank, sanitises, POSTs, returns `✅ retained 1 item(s) to bank=consumer-c-legacy; usage=4844 tokens`.
- Loop closed: retain → semantic indexing → recall → injected context all working against production Hindsight v0.5.4 behind CF Access.

### Fixes (in consumer-d, related)

- `secrets/secrets.env` — added `HINDSIGHT_URL=https://consumer-d-hindsight.consumer-bfood.com` (was missing; SessionStart hooks were failing silently via `|| true`).

## [0.2.2] — 2026-04-24 — Hindsight loop closed (read + write + sessionstart wiring)

### Added

- `scripts/_hindsight.py` — shared HTTP client (CF Access auth + bearer fallback + 45 s default timeout). 9 tests.
- `scripts/retain_lesson.py` — write side. CLI: `--content`, `--bulk JSONL`, `--replay-queue`. Sanitises through `secrets_scan` before POST. Hard-blocks API-key shapes, soft-redacts softer matches. Queues to `.ai-playbook/hindsight-queue.jsonl` when Hindsight is unreachable. 9 tests.
- `runbooks/hindsight-retain.md` — when to retain, how to invoke, sanitisation contract, degraded-mode replay, verify-it-landed.
- `consumer-c-legacy/.claude/settings.json` + `consumer-d/.claude/settings.json` — SessionStart hooks invoking `inject_context.py` with the project bank id (timeout 60 s).
- `consumer-c-legacy/mcp-servers.yaml` (project layer, schema mcp-servers/v1) + rendered `consumer-c-legacy/.mcp.json` + `consumer-c-legacy/.gemini/settings.json` (11 servers from base+project layers; personal layer excluded since consumer-c-legacy is public AGPL).

### Changed

- `scripts/inject_context.py` — recall now goes through `_hindsight.post_recall` against the real API path `/v1/default/banks/{bank_id}/memories/recall` with CF Access headers. Bank id rides in URL, not body. Maps `top_k` → `max_tokens` (~800 tokens per top_k unit). 21 tests pass.
- `specs/env-vars.md` §HINDSIGHT_* — replaced bearer-only contract with the real auth resolution order: CF Access pair preferred, bearer fallback. Documents the 45 s timeout and queue file.
- `specs/memory-hierarchy.md` §5 — added the canonical retain CLI invocation as the lead bullet.
- `docs/session-start-hook.md` — bumped hook timeout from 15 s to 60 s; updated command to use full path + `--bank-id <slug>`.

### Replayed to Hindsight

Four lessons from the 2026-04-24 session retained to bank `consumer-d` (cross-project personal knowledge): zero-touch propagation loop architecture, runbooks-as-AI-executable doctrine, 3 GitHub Actions gotchas (setuptools / x-access-token / submodule auth via insteadOf), Hindsight production deployment shape (CF Access + REST endpoints + 30 s cold recall).

### Known gap (deferred)

`consumer-d/.mcp.json` not rendered — the existing `consumer-d/mcp-servers.yaml` follows a legacy v2-metadata schema that pre-dates the playbook's mcp-servers/v1 layer schema. Migrating it is a separate piece of work (touches helm chart consumers, sync-configs.py, etc.). The SessionStart hook wired in consumer-d works regardless because it shells out to `inject_context.py` directly — `.mcp.json` is only needed for in-session MCP tool registration which isn't load-bearing today.

## [0.2.1] — 2026-04-24 — docs + propagation automation

### Added
- `consumers.yaml` — committed org-level registry of downstream repos consuming the playbook (distinct from per-dev `~/.ai-playbook/projects.yaml`). Schema `ai-playbook/consumers/v1`; active entries: consumer-c-legacy, consumer-d.
- `scripts/bump_consumers.py` — manual CLI to bump every consumer's `.ai-playbook/` submodule pin against `~/.ai-playbook/projects.yaml`. Flags: `--tag`, `--dry-run`, `--only`, `--push`, `--open-pr`, `--allow-dirty`, `--force`, `--force-with-reason`.
- `scripts/propagate_bump.py` — CI-side twin that reads `consumers.yaml` + `$GH_TOKEN`, clones each active consumer, bumps submodule, opens PR via `gh`. Idempotent (skips if PR already open). Emits `warn` notifications per PR.
- `.github/workflows/propagate-playbook-bump.yml` — event-driven primary propagation path: fires `on: push: tags: v*.*.*`, runs `propagate_bump.py`, uploads notifications.jsonl. Needs repo secret `PLAYBOOK_PROPAGATION_TOKEN`.
- `consumer-d/langgraph-aiops/workflows/playbook_bump_propagator.py` + CronJob wiring — daily circuit-breaker for the GH Action: queries consumer submodule SHAs, re-invokes propagator for laggards, emits `warn` on every firing (meaning the Action missed a fire).
- `specs/dispatcher-chain.md`, `specs/bootstrap-directive.md`, `docs/bootstrap-new-project.md` — 3 real v0.1.0 stubs closed to full v1.0.0 content.
- `specs/agent-contract.schema.json` — JSON Schema file extracted from the spec prose (was "stub pending T06 follow-up"); now the authoritative validation target.
- README.md — full directory map (35 specs, 24 scripts, templates, docs, routers, rfcs, tests) + 4 persona getting-started paths + honest status.

### Changed
- 36 spec/doc Status headers normalized — dropped confusing `Populated in **T14b**` provenance phrases that read like TODOs.
- 13 in-prose "stub" references inside v1.0.0 specs resolved (scripts they pointed at are fully populated).
- `scripts/_break_glass.py` — wires `ai_playbook.override.*` OTel span via `trace_emit.override_attrs` (no-op safe when OTel absent). Removes the stale T07c TODO.
- `scripts/mcp/validate.py` — stale "wire through _break_glass" TODO removed (the wiring already existed).
- `docs/quickstart.md`, `docs/quickstart-lessons.md`, `docs/start-here.md`, `AGENTS.md` — outdated "bootstrap.py is a stub" warnings replaced with real usage.

### Notes
- Deferred-by-design items (not addressed here, not stubs):
  - `specs/incident-response.md` activates at first paying client.
  - `docs/model-migration.md` activates at first pinned-model retirement.
  - `specs/notification-queue.md` full spec is T25+ (Phase 5).
- Consumer pins today: consumer-c-legacy + consumer-d still at v0.1.0. The propagation loop above will open bump-to-v0.2.1 PRs on tag push; humans merge per propose-only HITL convention.

## [0.2.0] — 2026-04-23 — MVP complete (T01–T23)

### Added (Batch 10 — governance + upstream sync, 3 parallel subagents)

**Subagent A — T22a/c/d/e/h/i governance docs + bootstrap (ai-playbook):**
- `specs/incident-response.md` — deferred IR placeholder; activation triggers named.
- `specs/role-matrix.md` — 4-role matrix + deferred k8s RBAC mapping.
- `specs/data-retention.md` — retention table (10+ rows), deletion paths, GDPR-adjacent anonymisation.
- `specs/post-mortem.md` + `templates/post-mortem.md.tmpl` — S1/SYSTEMIC trigger, 7-day due, required outcomes, 7 anti-patterns.
- `scripts/bootstrap.py` (~534 lines, **full impl replacing stub**) — submodule add + pin, template copy with placeholder substitution, `--personal`, `--dry-run`, `--playbook-path` offline fallback via break-glass.
- `scripts/deprecation_watcher.py` (~446 lines) — scans registry consumers + playbook for v0 schema, env-alias leaks, deprecated MCP IDs, stale lifecycle reports. `--strict`/`--json` modes; reads optional `specs/deprecations.yaml`.
- `tests/test_bootstrap.py` (28 tests; **skip removed**) + `tests/test_deprecation_watcher.py` (18 tests).

**Subagent B — T22f/g/j/k governance ops (ai-playbook):**
- `specs/slos.md` — 8 SLOs with monthly review cadence + RFC escalation.
- `specs/rollout-strategy.md` — 5-phase announcement path, 1-minor-cycle OR 90-day deprecation window, emergency security bypass.
- `docs/curriculum.md` — 4-week dev learning path (Operator / Reviewer / Contributor / Maintainer candidate) with exit criteria.
- `specs/channels.md` — solo-state + 8-row channels-by-purpose table + team-growth path + anti-patterns.

**Subagent C — T23 upstream sync (ai-playbook + consumer-d):**
- `specs/upstream-sync.md` + `templates/PATCHES.md.tmpl` + `docs/fork-inventory.md` (with `TODO: clarify` on 4 upstream URLs).
- `scripts/upstream_sync.py` (~528 lines) — local inspection tool, `list`/`status`/`refresh`/`mark-merged` subcommands. Refresh is propose-only — no auto-merge.
- `tests/test_upstream_sync.py` — 20 tests.
- `consumer-d/langgraph-aiops/workflows/upstream_refresher.py` (~538 lines) — weekly LangGraph workflow; propose-only, gated by `hitl.request_approval`; decision log written to `reports/upstream-refresh/`.
- `consumer-d/tests/test_upstream_refresher.py` — 20 tests.

### Test suite totals (MVP close)

- **ai-playbook: 425 passed, 0 skipped, 0 failures** (359 previous + 66 new from Batch 10A+C; `test_bootstrap.py` finally unskipped).
- **consumer-d: 92 passed** (72 previous + 20 new from upstream_refresher); 2 pre-existing failures in `lib/test_advisor.py` that require live `ANTHROPIC_API_KEY` (unrelated to Batch work).
- **consumer-d-skills: no test suite yet.**

### Open TODOs remaining at v0.2.0

- Upstream URLs for 4 forks (hindsight/hermes/paperclip/lightrag) — Arturo to confirm in `docs/fork-inventory.md`.
- `Last rebase` timestamp convention in `PATCHES.md` — default ISO-8601; flagged in `specs/upstream-sync.md`.
- T18 LangGraph workflows (Batch 8B) — NOT deployed; Arturo runs `consumer-d/docs/operations/deploy-t18-workflows.md` (5-step Blindar aiops procedure) to activate on VPS.
- T19 Dashboard (Batch 9A) — deploy helm/consumer-d-stack/ manifest; 5-step runbook.
- `consumer-d-skills` HTTP service — only the API contract is spec'd (Batch 9B `docs/api-contract.md`); the service itself is future work.
- IR runbook (Batch 10A `specs/incident-response.md`) — deferred until first paying client.
- APPLY_FIX mode (T29 Phase 5) — every propose-mode helper carries the stub; real write capability after stability proof.

### MVP summary

23 tracks (T01–T23) landed across 10 batches. 3 repos touched (ai-playbook, consumer-d, consumer-d-skills + consumer-c-legacy for T02). Full test suite 425/0/0 green. 0 skips. All scripts dogfood pre-commit + schema + verdict + break-glass contracts.

---

## [Unreleased (pre-v0.2.0)] — T02 + Batches 2-9

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
