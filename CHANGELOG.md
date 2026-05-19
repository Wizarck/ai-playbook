# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

## [Unreleased]

### Known gaps still pending (target: v0.16.0+)

## [0.15.0] — 2026-05-19 — consumer-side zombie cleanup hook (declarative manifest + auto-fire)

Additive MINOR. Solves a long-standing hygiene gap: bumping `.ai-playbook` advances the submodule pin but never cleans what prior pins deposited in consumer trees. Patterns observed in `consumer-a` (PR #125, 2026-05-18): orphan `.skills-sources/` submodule + `.git/modules/.skills-sources/` metadata after a single-source simplification, stale `consumer-c-legacy` literals in MCP YAMLs after the v0.14.1 rename, drained-but-fat `hindsight-queue.jsonl` files, orphan `<!-- BEGIN auto-managed: <source> -->` markdown blocks.

This release ships a **declarative zombie manifest** + a **single cleanup script** that consumers invoke automatically from their `post-merge` / `post-checkout` hooks (same pattern as `sync_skills_local.py`).

### Added

- **`specs/cleanup-zombies.md`** (NEW, v1.0.0). Full contract: manifest schema (§2), three-tier policy (§3), six safety checks catalogue (§4), three-channel report contract (§5), exit-code policy (§6 — default invocation NEVER exits non-zero), break-glass clause (§7, `AIPLAYBOOK_CLEANUP_SKIP=1`), consumer adoption checklist (§8).
- **`specs/zombies-manifest.yaml`** (NEW). Rolling declarative inventory. v1 ships with 10 entries — 4 × Tier 1 (safe-delete), 1 × Tier 2 (literal rename), 5 × Tier 3 (advisory-only). Schema validation enforced via `cleanup_zombies.py validate` (exit 2 on schema break — the ONLY non-zero exit in the tool).
- **`scripts/cleanup_zombies.py`** (NEW): default invocation is dry-run; `--apply` executes Tier 1+2; `--quiet` for hook context; `validate` for the manifest schema pre-commit gate; `version` prints the manifest_version. 31 tests in [`tests/test_cleanup_zombies.py`](tests/test_cleanup_zombies.py) covering: manifest schema (9), each safety check (8), decision flow + channels (8), exit-code policy + break-glass (5), idempotency (1).
- **`templates/new-project/scripts/git-hooks/post-merge.tmpl`** (NEW). Two-step bash: skills sync → playbook zombie cleanup. Always exits 0 (`|| true` after cleanup). Activates via existing `scripts/install-skills-hooks.sh` pattern (sets `git config core.hooksPath scripts/git-hooks`).
- **`templates/new-project/scripts/git-hooks/post-checkout.tmpl`** (NEW). Analogous, gated on `$3 == "1"` (branch-checkout flag) so file checkouts don't re-fire.

### Changed

- **`specs/enforcement-status.md`**: new row for `cleanup-zombies.md` at ✅ wired (script + 31 tests + 2 hook templates + manifest schema validator).
- **`docs/development-flow.md`** §5 enforcement table: new row for "Consumer-side playbook zombie cleanup" at 🟡 partial (auto-fires per hook; promotion to ✅ when ≥ 1 real consumer adopts and reports a quiet quarter).
- **`runbooks/release.md`** §2: pre-cut checklist gains "If this release REMOVED or RENAMED any consumer-surface artefact (template file, frontmatter field, literal identifier consumers wire against), append an entry to `specs/zombies-manifest.yaml` and bump `manifest_version`."

### Consumer adoption (per consumer, in a follow-up PR)

1. Bump `.ai-playbook` submodule to v0.15.0.
2. Append one line to existing `scripts/git-hooks/post-merge` AND `scripts/git-hooks/post-checkout`:
   ```bash
   python "$REPO_ROOT/.ai-playbook/scripts/cleanup_zombies.py" --apply --quiet || true
   ```
3. Append `.ai-playbook/zombie-report.md` to `.gitignore`.

First adoption: `consumer-a` (already has `scripts/git-hooks/` from PR #125; single-line addition).

### Notes

- Manifest is **rolling**: future releases that remove/rename consumer-surface artefacts MUST append an entry here. The release.md checklist now gates this.
- No breaking changes. Consumers that don't bump remain unaffected. Consumers that bump but don't wire the hook keep running but accumulate (the script never auto-installs).

## [0.14.1] — 2026-05-18 — finish consumer-c-legacy → consumer-c rename (templates + schema)

Additive PATCH. Bundles PR #59 (already merged but untagged) plus stragglers it missed in two templates and the AGENTS.md JSON schema example. No spec/script/runbook contract changes — docs/examples only.

### Changed

- **`templates/gotcha.md.tmpl`**: example gotcha now references `consumer-c-api` instead of `consumer-c-legacy-api` so consumers copy a current project name.
- **`templates/projects.yaml.example`**: example registry entry now shows the canonical `consumer-c` slug + nested bare-worktree path `C:/Projects/consumer-c/master` (per the rename layout adopted 2026-05-18).
- **`specs/agents-md-v1.schema.json`**: `examples[0].project` is now `consumer-c` (was `consumer-c-legacy`); the camelCase justification `$comment` no longer cites the renamed repo — reworded to generic historical framing.

### Notes

CHANGELOG entries from prior releases that reference `consumer-c-legacy` are intentionally left as historical record. GitHub redirects the renamed repo URL so no link rot.

## [0.14.0] — 2026-05-15 — apply-phase orchestration enforcement (L1+L2+L3)

Additive MINOR. Closes a real failure mode observed in consumer-a's Revalid v1.0 epic (2026-05-14, PRs #1-#4): four slices implemented with manual `Edit`/`Write` on declared `write_paths` instead of through the `openspec-apply-change` skill. Symptoms — tests appended at end (not TDD-red-first), citation-drift preflight (skill §4b, v0.11.0) skipped, self-validation gates (runbook §3.4) silent. The work landed but retros could not distinguish skill-orchestrated work from manual work.

This release ships three coordinated enforcement layers:

- **L1 — doc rule**: explicit text in [`specs/runbook-bmad-openspec.md`](specs/runbook-bmad-openspec.md) §3.1.1 stating apply phase MUST go through the skill. New row `2.13 apply_phase_bypass` in [`specs/agentic-failures.md`](specs/agentic-failures.md).
- **L2 — skill marker**: skill `openspec-apply-change` bumped to v1.1 — new step 0 writes a JSONL `start` record to `openspec/changes/<id>/.apply_log.jsonl` (committed to git for audit). Marker helper `scripts/openspec_apply_marker.py` exposes `start`/`stop`/`override`/`is_active`/`session_started`/`list` subcommands.
- **L3 — PreToolUse hook**: project-local hook at `.claude/hooks/openspec-apply-enforce.py` blocks `Edit`/`Write`/`MultiEdit` on a slice's `write_paths` when no `start` record exists for the current session. Break-glass via `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE=<≥10-char reason>` env (audited via `override` JSONL record).

### Added

- **`specs/apply-skill-enforcement.md`** (NEW, v1.0.0). Marker contract (§1), hook contract (§2), break-glass clause (§3, per [`break-glass.md`](specs/break-glass.md)), invariants INV-1..INV-4 (§4), consumer adoption checklist (§5), retro/audit cadence (§6).
- **`scripts/openspec_apply_marker.py`** (NEW). 6 subcommands. JSONL append-only audit log. Session-id resolution: `--session-id` → `$CLAUDE_SESSION_ID` env → derived `local-<git-user>-<host>-<pid>`. Path resolution walks `cwd` ancestors for `openspec/` dir. Error shape per [`error-message-standard.md`](specs/error-message-standard.md). 9 tests in [`tests/test_openspec_apply_marker.py`](tests/test_openspec_apply_marker.py): happy paths, idempotent start, corrupt-JSONL recovery, override audit record, missing change folder, list subcommand.
- **`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`** (NEW). Project-local PreToolUse hook. Reads JSON from stdin per Claude Code hook protocol. Walks `openspec/changes/*/tasks.md`, parses `Owns (write_paths)` section (bullet `* `path`` lines), glob-matches via `fnmatch`. Calls `session_started` subprocess per matching active change. Honours override env. Emits canonical block message per error-message-standard.md. Fail-open on missing helper. Perf budget <250ms p95. 10 tests in [`tests/test_apply_enforce_hook_template.py`](tests/test_apply_enforce_hook_template.py).
- **Skill `openspec-apply-change` v1.1**: new step 0 ("Write apply-session start marker") inserted before existing step 1. Frontmatter `version: "1.0"` → `"1.1"`. Backwards-compatible: pre-v0.14.0 consumers without the helper script see the skill's note about overdue playbook bump but proceed (no block).

### Changed

- **`specs/runbook-bmad-openspec.md`** §3.1.1 (NEW subsection). Documents the apply-phase orchestration rule + the two enforcement vectors + cross-references to QA pairing (§3.2) and self-validation gates (§3.4).
- **`specs/agentic-failures.md`** §1 catalog: new row `apply_phase_bypass` (S2, Detectable: Yes). §2 catalog detail: new section §2.13 with Signal/First-response/Detector/Example. Example cites the consumer-a Revalid incident.
- **`specs/enforcement-status.md`**: new row for `apply-skill-enforcement.md` at ✅ wired. `agentic-failures.md` row flipped from 📋 spec-only to 🟡 partial (mode 2.13 now wired via the hook).
- **`templates/new-project/.claude/settings.json.tmpl`**: registers the new `PreToolUse` hook for `Edit|Write|MultiEdit` matcher.

### Migration (per consumer)

5-step adoption checklist in [`specs/apply-skill-enforcement.md`](specs/apply-skill-enforcement.md) §5:

1. Bump `.ai-playbook` submodule to `v0.14.0`.
2. Copy `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` → `.claude/hooks/openspec-apply-enforce.py`.
3. Register the hook in `.claude/settings.json` (PreToolUse matcher `Edit|Write|MultiEdit`).
4. Update `AGENTS.md` to reference the new spec.
5. (Custom-schema projects) declare `apply.handler: openspec-apply-change` in `openspec/schemas/<name>/schema.yaml`.

First-class adoption: `consumer-a` (concurrent follow-up PR; dogfooded by resuming the paused `revalid-bulk-action-sse` slice under the new regime).

### Tests

- 9 new tests in `tests/test_openspec_apply_marker.py` — all GREEN.
- 10 new tests in `tests/test_apply_enforce_hook_template.py` — all GREEN.
- Total new test count: 19.

### Notes

- The `enforce-apply-skill` change folder ships with a real `.apply_log.jsonl` from this slice's own apply session (dogfooded). See `openspec/changes/enforce-apply-skill/.apply_log.jsonl`.
- Hook fails OPEN on helper absence (intentional, see [`specs/apply-skill-enforcement.md`](specs/apply-skill-enforcement.md) §2.4): a missing `.ai-playbook/scripts/openspec_apply_marker.py` warns to stderr but does not block. Consumer pre-v0.14.0 sees no enforcement.

## [0.13.4] — 2026-05-14 — worker-agent delegation prompt contract (`release-management.md` §4.5.5 + §4.5.6)

Patch release. Additive — codifies two prompt-engineering patterns that emerged across 4 consecutive worker-agent-delegated PRs in the `Wizarck/consumer-e` dashboard wave (#149, #150, #151, #152) plus one CI-recovery cycle (PR #152 L2 re-run).

Both failure modes affect the **whole-slice worker-agent delegation** flow (main agent invokes `Agent(isolation="worktree", ...)` to ship apply → lint → push → open PR end-to-end). Neither was previously covered: §4.5.4 only covers *automation* PRs (bump / chore-archive scripts), not *worker-AI* delegation. The new subsections close that gap.

New: [`specs/release-management.md`](specs/release-management.md) §4.5.5 — **Worker-agent delegation: STOP-after-`gh pr create` directive.** Prompts MUST embed the literal "STOP after `gh pr create` returns the PR URL. Do NOT poll CI." instruction. Verified on consumer-e PRs #149-#152: worker wall-time dropped from ~16 min to 4-8 min (263 seconds on PR #151, new record) after the directive landed.

New: [`specs/release-management.md`](specs/release-management.md) §4.5.6 — **Worker-agent delegation: AI-reviewer signoff canonical block in prompt.** Prompts MUST embed the literal §4.5.3 block (three markers `Profile:`, `Reviewer:`, `Self-review findings:`) verbatim, not a free-form "write a self-review section" instruction. Failure surfaced on consumer-e PR #152 (substantive prose, no markers → L2 re-run cycle, +6 min recovery).

Tracked at [`openspec/changes/agent-spawn-template-improvements/proposal.md`](openspec/changes/agent-spawn-template-improvements/proposal.md).

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.4`. No code changes required — docs-only patch. Main agents that already include the patterns ad-hoc see no change; main agents that don't get a documented contract to follow.

## [0.13.3] — 2026-05-13 — fusion-integration-pattern spec + new-project template polish

Patch release. Additive — codifies the integration pattern for consumer projects that already have a mature OpenSpec custom workflow (their own `openspec/schemas/<name>/schema.yaml` with N artefacts and project-specific Karpathy/discipline rules). The pattern preserves the consumer's accumulated workflow investment and imports the formal contracts the playbook ships (verdict-contract S1-S4, parallel-review context isolation, agentic-failures taxonomy, output-completeness rules, verification-before-completion iron law, agent-contract write_paths, Hindsight recall) without replacing the custom workflow.

First reference implementation: `consumer-a` (FastAPI + Next.js modular monolith, `consumer-a-team` schema with 9 artefacts, 18 changes pre-fusion).

New: [`specs/fusion-integration-pattern.md`](specs/fusion-integration-pattern.md) — fusion decision matrix, AGENTS.md §7 template structure, migration policy (existing changes exempt), N-layer parallel review (3 isolated playbook layers + 1 holistic project-reviewer layer with M custom checks; no size opt-out), dual canonical memory sources (Markdown SSOT + Hindsight recall), verdict mapping reference (legacy → canonical), pre-commit hook profile with documented opt-out conditions, worked example.

Template polish (no breaking changes for existing consumers):

- `templates/new-project/AGENTS.md.tmpl`: bump `inherits_from` pin from `v0.3.0` to `v0.13.2` (current shipped at time of v0.13.3 PR). Add §7 comment block linking to fusion-integration-pattern.md for projects with pre-existing custom workflows.
- `templates/new-project/.pre-commit-config.yaml.tmpl`: add `verdict-lint` hook as default (matches `openspec/changes/*/(review|verify).md`). Comment out `block_manual_spec_edit` and `verify_llm_routing` hooks with explicit opt-in activation conditions documented inline. Expand `mcp-validate` `files` regex to match both `mcp-servers.yaml` and `mcp-servers.project.yaml`.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.3`. No code changes required. Existing consumer projects with their own workflow stay on the path they were on; the new spec is opt-in for projects that need it.

## [0.13.2] — 2026-05-13 — upstream-sync §9: containerised forks pin-bump rule

Patch release. Docs-only — `specs/upstream-sync.md` v1.0.0 → v1.1.0 gains §9 "Containerised forks — base-image pin discipline" capturing a fork-overlay-Docker gotcha learned in [`Wizarck/hermes-agent#6`](https://github.com/Wizarck/hermes-agent/pull/6) on 2026-05-13.

Rule: when a fork ships as `FROM <upstream>@sha256:<digest> + COPY our_source.py`, the pinned digest and the fork source tree MUST advance together during every upstream sync. Skipping the pin bump produces a container where new source files (with new imports) sit on top of an OLD base image without the modules they need → `ModuleNotFoundError` at startup.

Spec adds the rule, a 4-step recipe (merge → resolve digest → bump pin → rebuild), an applicability boundary (only for overlay forks), and a memory-retention hook tagged `upstream-sync, containerised-fork, fork-image-pin`.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.2`. No code changes required. Consumers running fork overlays (Hermes, Hindsight, Paperclip, LightRAG, ...) benefit from the vendored doc.


- **`propagate_bump.py` + `propagate_skills_bump.py` script implementation of §4.5.4 rule**: v0.11.0 codifies the rule (auto-generated bump PRs MUST pre-populate §4.5 markers); the script edits to actually emit the block in `_render_pr_body()` are deferred to a follow-up. Until then, the rule is enforced socially: a bump PR opened without §4.5 will fail the `ai-self-review-required` check and require a manual body edit.
- **Capa 2 of bump-PR safety**: `propagate_bump.py` should scan the consumer's open PRs + branches with recent activity and post a comment listing them as "potentially affected, rebase needed post-merge". Carried forward from v0.10.x.
- **`missing-application-kwarg` warn → strict ratchet**: target 2026-06-05 after 30 days of green CI. Flip pre-commit + CI to `--strict` and add runtime `LLMConfigError` in `_llm.call()` when neither `application=` arg nor `AIPLAYBOOK_APPLICATION` env is set.

## [0.13.1] — 2026-05-13 — enforcement-status row 47 refresh (Phase 1 closure docs)

Patch release. Docs-only — refreshes the `model-routing.md` row in `specs/enforcement-status.md` (line 47) to reflect post-Phase-1 reality of OpenSpec change `add-litellm-enforcement` in consumer-d. No code or behaviour change.

The row now documents: drift detector covers BOTH direct-SDK and `_llm.call(...)` missing `application=` (v0.13.0 AST check); call-site migrations CLOSED for `prompt_injection_filter.py` (v0.12.1) and `consumer-d/lib/advisor.py:_call_via_litellm` (consumer-d PR #166); application tag lands end-to-end (v0.12.0 + roster in §5 of model-routing.md); CI step `Drift detector (warn-only)` wired in test.yml on 2026-05-13; strict-mode promotion target 2026-06-05 still pending.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.1`. No code changes required. The vendored copy of `specs/enforcement-status.md` will reflect the post-Phase-1 reality.

## [0.13.0] — 2026-05-13 — drift detector: `_llm.call(...)` missing `application=` kwarg

Additive MINOR release. `scripts/verify_llm_routing.py` gains a second detection rule beyond direct-SDK callers: every `_llm.call(...)` invocation MUST carry an explicit `application=` keyword (or rely on `AIPLAYBOOK_APPLICATION` env at runtime). Without static enforcement, new callers shipping post-v0.12.0 could silently land with `metadata.application = null` and render in downstream observability as "untagged" — defeating the purpose of the application dimension.

Closes T7.5 + T7.8 of parent consumer-d change `add-litellm-enforcement`. Tracked here at [`openspec/changes/llm-drift-detector-app-kwarg/proposal.md`](openspec/changes/llm-drift-detector-app-kwarg/proposal.md).

### Added

- **`scripts/verify_llm_routing.py`** — new AST-based check `missing-application-kwarg`. Flags `_llm.call(...)` invocations that lack an explicit `application=` keyword. Handles aliased imports (`from ._llm import call as _llm_call`), attribute chains (`scripts._llm.call(...)`), and multiline call sites. Respects existing `# llm-routing-allow: <reason>` inline whitelist (use `env-fallback` for callers relying on `AIPLAYBOOK_APPLICATION` env). Warn-only in v1 — same warn → strict ratchet (D3.5) as the existing direct-SDK rules. CLI hint differentiates direct-SDK findings from missing-application findings.
- **`.github/workflows/test.yml`** — new "Drift detector (warn-only)" CI step running `python -m scripts.verify_llm_routing` on every PR.
- **`tests/test_llm_helper.py`** — 9 new `test_scan_*` tests covering the AST check (clean-tree updated; new cases for missing/explicit/multiline/aliased/inline-allow/kwargs-splat/excludes-`_llm.py`/chained-attr). 26/26 tests passing.
- **`openspec/changes/llm-drift-detector-app-kwarg/`** — new openspec change tracking the playbook-side of T7.

### Changed

- N/A — fully additive. The new rule is warn-only, so existing builds remain green.

### Removed

- N/A.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.0`. The new CI step will start flagging any `_llm.call(...)` in consumer code missing `application=`. Findings are warnings only — exit code 0 — but they appear in the CI log and are visible in pre-commit local runs.
- Existing callers that already pass `application=` (e.g. consumer-d's `lib/advisor.py` adopted in v0.12.1's wave) are unaffected.
- To migrate a flagged call, add the canonical `application="<name>"` per `specs/model-routing.md` §5 roster, OR annotate with `# llm-routing-allow: env-fallback` if the caller relies on `AIPLAYBOOK_APPLICATION` env in its deployment manifest.

## [0.12.1] — 2026-05-13 — prompt-injection-filter adopts application tag

Patch release. `scripts/prompt_injection_filter.py:_run_layer2()` now passes `application="prompt-injection-filter"` to its existing `_llm.call(task_class="safety_judge", ...)` invocation (the parameter shipped in v0.12.0). Without the explicit kwarg, the trace's `metadata.application` was null and downstream observability tooling (consumer-d's cost-by-application widget, Phase 3) would have rendered the entries in the "untagged" bucket.

First caller in the playbook to adopt the application dimension. No behavior change beyond OTel metadata.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.12.1`. No code changes required in consumers unless they want to backport the same pattern (`application=` kwarg) to their own callers — recommended.

## [0.12.0] — 2026-05-12 — LLM application tag (second observability dimension orthogonal to consumer)

Additive MINOR release. Adds a second tagging dimension (`application`) parallel to the existing `consumer`, enabling cost attribution by functional subsystem in downstream observability tooling (cost-by-tag dashboard in consumer-d, similar surfaces in other consumers).

Motivation: consumers like `WORKFLOWS` fan out to many functional subsystems (`aiops-workflow-vps-maintainer`, `aiops-workflow-retro-generator`, `langgraph-doc-writer`, ...). Attribution by `consumer` alone collapses these into one bucket, breaking *"which subsystem is driving Opus cost?"*. Collapsing the two dimensions instead (one tag per app) explodes the LiteLLM virtual-key roster and breaks the budget abstraction. Decouple from day 1.

Origin: cost-by-tag-dashboard project in consumer-d (Phase 1), see [`openspec/changes/llm-application-tag/proposal.md`](openspec/changes/llm-application-tag/proposal.md).

### Added

- **`scripts/_llm.py`** — `call()` accepts new `application: str | None = None` kwarg. `_resolve_application()` mirrors `_resolve_consumer()` with `AIPLAYBOOK_APPLICATION` env fallback (kebab-lowercase normalisation). All 4 OTel emission points propagate `ai_playbook.application`. CLI surface gains `--application`. `LLMResponse` dataclass gains `application` field. 16/16 existing tests pass — backwards-compatible.
- **`specs/model-routing.md`** v2.1.0 — new §5 "Application tags" with canonical roster (`hermes-bot`, `dashboard-backend`, `aiops-workflow-<name>`, `prompt-injection-filter`, `lib-advisor`, `hindsight-internal`, `claude-code` reserved) + "how to add a new application" recipe + worked examples showing `consumer × application` M:M. §4 OTel attributes table gains `ai_playbook.application` and `ai_playbook.consumer` rows (the latter was implicitly required but never documented). Existing §5 "Hooks and existing code" renumbered to §6; §6 "Break-glass" to §7. Additive.
- **`specs/env-vars.md`** §Per-consumer virtual keys — new "How to add a new consumer" 7-step subsection (provider key generation → SOPS encryption → k8s sync → LiteLLM wiring → table registration → budget cap script → smoke test).
- **`configs/litellm-router.yaml`** — top-of-file warning section documenting the production-deploy mirror contract: LiteLLM accepts only ONE `--config` file, so this yaml MUST be mirrored into the consumer's project-local ConfigMap. The companion sync test lives in the consumer's repo (e.g. `consumer-d/dashboard/tests/test_litellm_config_sync.py`), NOT here — it reads the consumer's local deploy template, which doesn't exist inside the playbook standalone.
- **`openspec/changes/llm-application-tag/`** — new openspec change folder tracking the playbook-side of this work, cross-referenced to the parent project in consumer-d.

### Changed

- N/A — fully additive. No existing surface modified in a breaking way.

### Removed

- N/A.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.12.0` via `propagate_bump.py` (or manually `cd .ai-playbook && git checkout v0.12.0`).
- Existing callers that don't pass `application=` continue to work; the resulting trace's `metadata.application` will be `null` until adopted.
- Each consumer SHOULD ship a sync test that asserts strict-subset against their local LiteLLM ConfigMap / docker-compose volume mount. See consumer-d for the reference implementation.

## [0.11.0] — 2026-05-06 — cross-project pattern consolidation: migration slots, Protocol+InTreeFake, additive extension, HITL approval, multi-layer defense

## [0.11.0] — 2026-05-06 — cross-project pattern consolidation: migration slots, Protocol+InTreeFake, additive extension, HITL approval, multi-layer defense

Major cross-project lessons-consolidation release. Mined 14 consumer-e retros + 22 consumer-c-legacy retros + 28 consumer-d ADRs + consumer-b docs/archive for recurring patterns; produced 7 new normative specs, 1 new skill, 2 new runbook surfaces, 3 new templates, and 5 spec extensions.

### Added

#### Tier-1 specs (HIGH-severity cross-project patterns)

- **`specs/migration-slot-reservation.md`** (v1.0.0) — universal contract for **reserving monotonic / append-only namespace slots** across parallel slices (DB migrations, gotcha IDs, ADR numbers, seed entity IDs). Subsumes + generalises `release-management.md` §6.4.1/§6.4.2. Closes the **6-consecutive migration-slot-collision pattern** in consumer-e Wave 2-3 (R1/R2/R5/R3/T2/O2 all picked slot `0007`/`0008` independently). Validated by consumer-c-legacy m2-data-model + cost-rollup parallel m2 races.
- **`specs/protocol-fake-deferred-install.md`** (v1.0.0) — canonical **Protocol + InTreeFake + DeferredProductionInstall** pattern for isolating heavy / security-sensitive vendor SDKs. Cross-validated by 6+ consumer-e Wave 3 slices (R5/T2/R3/O2 + 2 more) + consumer-c-legacy m2-recipes-core service IoC + consumer-d ADR-018/-028 sidecar isolation. Defines the four artefacts (Protocol / fake / deferred-install row / production adapter) + cross-language guidance (Python / TypeScript-NestJS / Elixir-behaviour).
- **`specs/cross-slice-additive-extension.md`** (v1.0.0) — three additive shapes (nullable / `NOT NULL DEFAULT <sentinel>` / JSONB) for parallel slices extending shared entities. Drawn from 4+ consumer-e R-series slices (`dedupe_key`, `audit_trail_id`, `client_order_id`) + consumer-c-legacy m2-data-model array/jsonb columns. Codifies migration-chain discipline + read-side discipline.
- **`specs/hitl-approval-pattern.md`** (v1.0.0) — runtime **HITL gating for state-mutating actions** in single-operator AI systems. Cross-validated by **3 projects** (consumer-e P1 Telegram approval-channels + consumer-d ADR-028 WABA-MCP rollout gating + consumer-b operator-gated deploys). Defines the five Protocol artefacts (mutation request DTO / channel Protocol / HMAC correlation / decision persistence / TTL+escalation ladder) + a canonical 3-tier channel ladder + cross-project mutation taxonomy.

#### Tier-2 specs (MED-severity recurring patterns)

- **`specs/dependency-injection-patterns.md`** (v1.0.0) — provider deduplication (NestJS `@Global()` rule + Python `app.dependency_overrides` + Phoenix `Application.put_env` equivalents) + **seam-then-consume DI tokens** for cross-slice extension. Cross-validated by consumer-c-legacy m2-mcp-write-capabilities (`payload_before:null` bug from `@Global()` re-declaration) + m2-cost-rollup-and-audit (`INVENTORY_COST_RESOLVER` token rebinding) + consumer-d ADR-028 (action-class dispatcher dict). Includes the **class-level cache reset autouse fixture** pattern for test isolation.
- **`specs/database-numeric-boundaries.md`** (v1.0.0) — **money/decimal column boundary rule** (explicit coercion at ORM, never per-call). Surfaced by consumer-c-legacy m2-cost-rollup numeric-string-multiplication bug (`"1000NaN"` shipped to BI ingest). Per-stack recipes for TypeORM / Prisma / SQLAlchemy / Ecto. Generalises the AGENTS.md "no float for money" universal rule.
- **`specs/multi-layer-defense-single-operator.md`** (v1.0.0) — canonical **5-layer defense pattern** (L1 Identity / L2 Ingress / L3 Network / L4 State-RBAC / L5 Ergonomic) for single-operator AI systems. Cross-validated by consumer-d ADRs 017/018/019/020/024 + consumer-b `MERGE-ORDERS-SECURITY-AUDIT.md` zero-permission plugin fork. Decision matrix for when each layer is warranted.

#### Spec extensions (added sections to existing canonical specs)

- **`specs/release-management.md` §4.5.4**: codifies that **auto-generated bump / chore-archive PRs MUST pre-populate the §4.5 AI-reviewer signoff block**. Closes the v0.10.3 CHANGELOG gap surfaced 2026-05-06 by 5 failed bump PRs + 3 failed chore-archive PRs in consumer-e (PRs #90/#92/#94 all required manual body-edit roundtrips).
- **`specs/release-management.md` §6.6.1**: canonical **subagent prompt template** + mandatory verification commands contract for intra-slice parallelism. Cross-validated by consumer-c-legacy Wave 1.7-1.9 (3 subagent slices, 0 boundary violations, ~22 min/slice saved). Template at `templates/subagent-prompt.md.tmpl`.
- **`specs/release-management.md` §6.7**: **post-merge OpenSpec archive automation**. Closes the second v0.10.3 CHANGELOG gap (28h archive drift in consumer-e Wave 2 PRs #68+#69). Workflow template fires on `slice/*` PR squash-merge to main; opens `chore/archive-<id>` PR with §4.5-marker-populated body and auto-merge enabled.
- **`specs/event-and-data-patterns.md` §9**: async event-emission ordering — `tap()` vs `mergeMap+emitAsync` for read-after-write coherence + cascade self-emission guard (one-line ID equality check). Cross-stack equivalents for NestJS RxJS / Phoenix LiveView / FastAPI / Express. Cross-validated by consumer-c-legacy m2-mcp-write-capabilities + m2-cost-rollup race conditions.
- **`specs/runbook-bmad-openspec.md` §3.7.2**: **proposal-only-first** for tech-seam slices (new tech stack, architectural seams, cross-cutting infrastructure). Cross-validated by consumer-c-legacy m2-ui-foundation + consumer-e api-foundation-rfc7807. Defers design.md/tasks.md/apply until Gate D approval lands; saves rework when design is rescinded mid-apply.
- **`skills/openspec-apply-change/SKILL.md` §4b**: **preflight re-grep** of cited identifiers (class names, file paths, migration slot numbers, ADR numbers) on `main` before apply. Catches state divergence between propose and apply (proposals written days earlier may cite renamed/removed identifiers). Refuses to proceed if ≥3 identifiers drifted; warns + asks if 1-2.
- **`runbooks/release.md` §10**: mandatory **first-run smoke test** for every new script / workflow / skill against ONE real consumer before rc → stable promotion. Closes the v0.10.x cascade pattern (3 hotfixes within 5 days because tests stubbed boundaries that hid environmental constraints — API limits, locale encoding, missing markers).

#### New templates

- **`templates/new-project/.github/workflows/propagate-archive.yml.tmpl`** — GH Actions workflow implementing release-management.md §6.7. Self-contained; consumers copy in + ensure `allow_auto_merge=true` is set.
- **`templates/subagent-prompt.md.tmpl`** — five-section subagent prompt template (Scope / Owns / Reads / Verification commands / Report format) per release-management.md §6.6.1.
- **`templates/k8s/serviceaccount-namespace-scoped.yaml.tmpl`** — L4 RBAC starter; default-deny + verify-by-attempted-denial pattern per multi-layer-defense-single-operator.md.
- **`templates/k8s/networkpolicy-egress-allowlist.yaml.tmpl`** — L3 egress control; DNS-aware variant for Cilium/Calico CNIs.

#### New runbooks

- **`runbooks/cascade-failure-template.md`** (v1.0.0) — template runbook for **service-dependency cascade failures**. 5-section structure (symptom list / precondition check / impact map / recovery sequence / postmortem trigger). Cross-validated by consumer-d `runbook-litellm-down-cascade.md` (LiteLLM → Hindsight → Hermes → Paperclip cascade) + consumer-b gotchas.

#### New skill

- **`skills/bmad-extract-lessons-from-adrs/`** (v1.0) — mining skill for projects without populated `retros/` directories. Walks ADRs / gotchas / runbooks / docs/archive / CHANGELOGs / postmortems for cross-project patterns. Used to mine consumer-d (28 ADRs) + consumer-b (docs/archive) for v0.11.0 patterns. Reusable for future ai-playbook releases.

### Migration

Existing consumers on v0.10.x adopt v0.11.0 by:

1. **Submodule bump**: the `propagate-playbook-bump.yml` Action opens the bump PR automatically once `v0.11.0` is tagged.
2. **Slot reservations** (per `migration-slot-reservation.md`): for projects with active OpenSpec waves, audit current slot usage + add the **"Slot reservations"** section to `docs/openspec-slice.md`. Re-open Gate C to approve. Existing slot assignments are preserved; only future scaffolds get the new validation.
3. **Deferred installs table** (per `protocol-fake-deferred-install.md`): for projects using Protocol + fake patterns, add the **"Deferred installs"** section to `docs/openspec-slice.md` listing every Protocol-isolated capability.
4. **HITL mutation taxonomy** (per `hitl-approval-pattern.md`): for projects with state-mutating AI actions, list the mutation classes that require HITL gating in `AGENTS.md`.
5. **Multi-layer-defense matrix** (per `multi-layer-defense-single-operator.md`): for projects with operator-gated infrastructure, document the 5-layer matrix as 5 ADRs (or a single combined ADR).
6. **Subagent prompt template** (per `release-management.md` §6.6.1): for projects using `/openspec-apply-parallel`, copy the subagent prompt template and extend with project-specific verification commands.

Migration is **non-destructive**: existing artefacts are preserved; only new scaffolds opt into the new validations. Each consumer's bump PR includes a checklist to drive the migration.

### Notes

- All 7 new specs + 1 new skill cross-validated by ≥2 projects (most by 3+ projects). One-source patterns deliberately excluded as project-specific.
- The mining session (used to identify these patterns) is reproducible via the new `bmad-extract-lessons-from-adrs` skill — ai-playbook v0.12+ should run it against every consumer with empty `retros/` to seed the next consolidation pass.
- v0.11 deliberately ships as a feature release (not v0.10.3 patch) because the 7 new normative specs are too substantial for a patch slot.

## [0.10.2] — 2026-05-06 — verify_board_state Windows UTF-8 hotfix

### Fixed

## [0.10.2] — 2026-05-06 — verify_board_state Windows UTF-8 hotfix

### Fixed

- **`scripts/verify_board_state.py`** — added `sys.stdout/sys.stderr.reconfigure(encoding="utf-8")` at module top. v0.10.1's success path printed `✅ Project item ... matches expected` which crashed with `UnicodeEncodeError` on Windows cp1252 consoles. Pattern mirrors `scripts/notify.py` and `scripts/verify_llm_routing.py`. Surfaced 2026-05-06 during first invocation from `/c/Projects/consumer-e/.ai-playbook/scripts/verify_board_state.py` on Windows. Linux CI was unaffected (default UTF-8). The crash masked exit code 0 (success) and surfaced as exit code 1, which would cause spurious `--enforce-board` failures on Windows for slices that ARE actually in the expected state.

### Notes

- This is the third real-world-surfaced gap in the v0.10.x line (after `first: 200` API limit and §4.5 auto-population). Pattern: tests stub at the boundary, real-world invocation reveals environmental constraints (API limits, locale encoding, missing markers in auto-generated content). v0.10.3 should formalize a "first real invocation" smoke test in the release ritual.

## [0.10.1] — 2026-05-06 — verify_board_state pagination hotfix

### Fixed

- **`scripts/verify_board_state.py`** — replaced `items(first: 200)` with paginated `items(first: 100, after: $cursor)` walking via `pageInfo.hasNextPage` / `endCursor`. Surfaced 2026-05-06 during first real invocation against `consumer-e` project board: GitHub GraphQL connection limit on `first` is 100, not 200, producing `HTTP 422: Requesting 200 records on the connection exceeds the 'first' limit of 100 records`. v0.10.0's tests mocked the GraphQL transport with `subprocess.run` patches that returned a single response; they never hit the real API limit. The pagination loop now terminates cleanly via `pageInfo.hasNextPage=false`.
- **`tests/test_verify_board_state.py`** — added 2 pagination tests (`test_pagination_walks_to_second_page`, `test_pagination_stops_after_last_page_when_not_found`) covering the cursor-following loop. Also extended `_make_graphql_response` helper to accept `has_next_page` + `end_cursor` so existing tests stay compatible.

### Notes

- This is a real-world-vs-mocks gap: the bug shipped because tests stubbed the transport at the boundary that hides the API constraint. v0.10.2 should add a contract test that uses `gh api graphql --schema` validation (or a recorded fixture from a real call) so structural API mismatches surface in CI.

## [0.10.0] — 2026-05-06 — project-board-sync + agent-telemetry + 7-layer defense-in-depth

### Added

- **`specs/project-board-sync.md`** — new normative spec (v1.0.0) codifying a 7-layer defense-in-depth contract for GitHub Project board sync during AI-driven OpenSpec work. L1 built-in workflows, L2 custom Actions workflow, L3 required status check (`project-board-synced`), L4 state-machine validator (gh-aw ProjectOps pattern), L5 OTLP agent telemetry, L6 companion script `--enforce-board` flag, L7 archive skill Step 0 verification. Five truly-independent layers (server-side + telemetry) plus two tool-level reinforcers. Authored after consumer-e Wave 2 retro surfaced silent board drift (slices merged with `Status=Backlog`, no audit trail). Research-grounded justifications cite OWASP AI Security Guide 2026, GitHub gh-aw ProjectOps pattern, EU AI Act forward-looking compliance, and the LLM-structured-outputs syntax-vs-semantics distinction.
- **`specs/agent-telemetry.md`** — new normative spec (v1.0.0) codifying the Claude Code OTLP exporter → Langfuse ingestion pattern. Four-environment-variable configuration, resource attributes for slice/wave tagging, OpenTelemetry GenAI semantic conventions mapping, "reuse over reinvent" default for projects with existing Langfuse instances (or Langfuse Cloud free tier as minimum-viable for greenfield consumers). Anti-patterns: standing up a custom OTel collector, inventing custom JSONL audit logs, logging traces to the project's `data/` directory, disabling telemetry "for performance".
- **`specs/event-and-data-patterns.md`** — new normative spec (v1.0.0) codifying 7 stack-agnostic patterns surfaced by consumer-c-legacy Wave 1.7-1.9 + consumer-e Wave 1-2: (1) hybrid translation pattern for cross-cutting concern extraction without forcing N upstream emitters to migrate, (2) two-name pattern (bus channel name preserves module ownership; persisted name is module-agnostic), (3) same-transaction migration with backfill, (4) `hasTable`/`hasColumn` guards on backfill SELECTs, (5) open-enum text columns + CHECK over native enums, (6) stateless proxy + stateful caller, (7) failure-collapse-to-null. Each pattern has a "when it applies", "when NOT", failure-mode-prevented, and reference implementation citation.
- **`specs/cross-language-tooling.md`** — new normative spec (v1.0.0) codifying the `tools/<name>/` peer-subdirectory convention for non-primary-language tools (Python services in TS monorepos, MCP servers in Python monorepos). Each tool has its own complete toolchain (`pyproject.toml`, ruff/mypy/pytest, Dockerfile multi-stage, `.env.example`, separate CI workflow with path filter). Anti-patterns: faking Python as a TS workspace, mixing primary-language code into `tools/`, reaching across language boundaries via filesystem. Reference implementations: consumer-c-legacy `tools/rag-proxy/` (Wave 1.8) and planned consumer-e `tools/openbb-sidecar/` (R4 slice).
- **`runbooks/windows-dev-environment.md`** — new operational runbook (v1.0.0) capturing Windows-specific dev-loop gotchas: (1) `python -m venv` doesn't include pip on Windows Store Python without `--upgrade-deps`, (2) `pip install --user` is silent + glacially slow on Windows Store Python, (3) Jest workers crash with `spawn UNKNOWN errno -4094` on Windows + Node 24+ (fix: `--runInBand`), (4) `git worktree remove --force` fails "Device or resource busy" on Windows when IDE / file watcher / AV holds handles. Linux CI is unaffected; this runbook is for Windows developer pain only.
- **`templates/new-project/.github/workflows/project-status-slice-progress.yml.tmpl`** — L2 server-side workflow per project-board-sync.md. On `push` to `slice/**` populates Branch field + Base SHA + Status=In Progress on the matching project item via GraphQL; on PR opened sets Status=Review. Idempotent. Reuses existing `PROJECT_AUTOMATION_TOKEN` secret + `PROJECT_OWNER`/`PROJECT_NUMBER` vars from the existing `project-status.yml` template (which it complements, not replaces — that one handles Wave-N Blocked → Todo transitions).
- **`templates/new-project/.github/workflows/project-board-synced-check.yml.tmpl`** — L3 required status check per project-board-sync.md. Asserts (a) Status ∈ {In Progress, Review}, (b) Branch field matches PR head ref, (c) Base SHA field populated. Designed to be added to required-status-checks list in branch protection so the merge button physically blocks until board is synced. Actionable error messages name `opsx_apply_companion.py` as the fix path.
- **`templates/new-project/.github/workflows/project-state-machine.yml.tmpl`** — L4 state-machine validator per project-board-sync.md. v1 ships as periodic auditor (every 15min cron) flagging items with `Status=Done` but no merged PR. v2 will switch to native `project_v2_item.edited` webhook events once GitHub exposes them at the workflow level. Honors `break-glass` label exception per `specs/break-glass.md`.
- **`scripts/verify_board_state.py`** — L7 helper script per project-board-sync.md. CLI tool that queries the GH Project board via GraphQL and exits non-zero when the matching item's Status doesn't match `--expected-status`. Stable exit-code contract: `0` match, `1` mismatch, `2` item-not-found, `3` GraphQL/network error. Designed for invocation by skills (e.g. archive Step 0) where the AI's verdict is bound to a tool exit code rather than the AI's text claim (per verification-before-completion.md §4.1.2).
- **`tests/test_verify_board_state.py`** — pytest coverage for `verify_board_state.py`. 11 tests covering all 4 exit codes + CLI argument parsing. The GraphQL transport (`subprocess.run` boundary) is mocked.

### Changed

- **`scripts/opsx_apply_companion.py`** — added `--enforce-board` flag (L6 per project-board-sync.md). When set, after the existing Branch/Base SHA write, the script delegates to `verify_board_state.py` with `--expected-status='In Progress'` and propagates the exit code. Default off for backwards compatibility; new opt-in for consumers on ai-playbook v0.10.0+. Telemetry event `opsx_apply_companion.board_enforce_failed` emitted on mismatch.
- **`skills/openspec-archive-change/SKILL.md`** — added Step 0 invoking `scripts/verify_board_state.py --expected-status=Done` BEFORE any archive work. Refuses archive on non-zero exit. Cites the exit code (per `verification-before-completion.md` §4.1.2 tool-exit-code-over-text rule). Backwards-compatible: emits warning + continues if script not present (consumers on ai-playbook < v0.10.0).

### Changed

- **`specs/verification-before-completion.md` §4.1** — added §4.1.1 "Broadest-scope rule" (run lint/typecheck at the broadest scope CI uses, not the slice subdirectory; retro-proven by consumer-e Wave 2 P1 where 6 mypy errors in test files were invisible at the contexts/<slice>/ scope but immediately surfaced at apps/api/ scope) and §4.1.2 "Tool-exit-code-over-text rule" (verdict messages cite the tool's exit code, not paraphrase the tool's output; LLM structured outputs guarantee syntax not semantics, so AI text claims about tool results are not proof — only non-AI-controlled process exit codes are).
- **`specs/release-management.md` §4.4** — added §4.4.1 "Gitleaks scans full PR commit history" (squash + force-push to clear history when leak is fixed in a later commit but earlier commit's leak still triggers the scanner) and §4.4.2 "Markdown style guide: avoid `KEY=<placeholder>` syntax" (shell-syntax placeholder fires gitleaks generic-api-key matcher; use bullet lists or inline narrative instead). Both retro-proven on consumer-c-legacy PR #89 (`m2-wrap-up`).
- **`specs/release-management.md` §6.4** — added §6.4.1 "Append-only doc files: numbering ranges per slice" (gotchas.md, CHANGELOG.md, append-only ADR indexes require explicit numeric range per slice; recommended convention: foundation 1-29, Wave 2 bounded contexts 30-79 in 10-blocks, Wave 3 adapters 80-199 in 20-blocks). Added §6.4.2 "Migration revision strings: verbose-form from scaffold" (alembic/sqlx/prisma migrations MUST use `<NNNN>_<topic>` from scaffold; latent chain breakage retro from consumer-e Wave 2 R1/T1 mismatch).
- **`specs/release-management.md` §6.6** — refined "When it does NOT apply" guidance for intra-slice parallelism: explicitly NOT applied to slices with cross-BC verification gates (cost ↔ allergens ↔ labels ↔ audit; trading → risk → kill-switch). The serial verification path beats subagent recombination + cross-BC test orchestration overhead. Validated on consumer-c-legacy Wave 1.9 + consumer-e K1.
- **`specs/release-management.md`** — added §9.5 "Project board sync contract" cross-referencing the new `project-board-sync.md` spec; updated §10 cross-references.
- **`specs/runbook-bmad-openspec.md` §3** — added §3.7.1 "Design-mock HTML for dense designs" (optional review aid for slices spanning ≥3 bounded contexts; visual mock with arch-flow + schema cards + sample API + Gate D recap, using project's design-system palette per `ux-track.md`). Validated on consumer-c-legacy Wave 1.9 where the mock surfaced a column-name mismatch pre-implementation.
- **`specs/runbook-bmad-openspec.md` §4** — added §4.1 "Forward-authored retros" (recommended pattern: author retro DURING slice's implementation, not after merge; squash SHA + merge date filled in post-merge during the archive step; reduces after-merge cognitive drop-off; validated across consumer-c-legacy Wave 1.7-1.9 + consumer-e Wave 2).
- **`scripts/notify.py`** — warn/error path now prefers the consumer-side durable queue (Phase 5 Change B `add-durable-notification-queue`) when `consumer-d_NOTIFICATIONS_QUEUE_ENABLED=1` AND a `notifications.queue` package is importable; falls through to the legacy synchronous SMTP path otherwise. The two transports are mutually exclusive per emission. Other consumers (consumer-b, consumer-c-legacy, consumer-e, livekit) continue with SMTP unchanged.
- **`scripts/prompt_injection_filter.py`** layer-2 migrated from direct `anthropic` SDK to `scripts._llm.call("safety_judge", consumer="INJECTION", ...)` per Change C P5.4 follow-up. The opt-in env var `ANTHROPIC_API_KEY_INJECTION` is preserved as a budget gate; actual provider key resolution now happens at the LiteLLM proxy via the `safety_judge` task class. Drift detector confirms 0 in-tree direct-SDK callers remain.
- **`scripts/verify_llm_routing.py`** — added Windows-safe UTF-8 stdio reconfigure so the success sigil (`✓`) prints under cp1252.
- **`specs/notification-queue.md`** — extended with §8 Durable queue layer (Phase 5 Change B): activation gate, SQLite schema, async worker model, backoff schedule, channel routing, MCP outbox tool, observability events, restart-survival contract. The legacy JSONL+SMTP layers (§3-§7) are unchanged.
- **`specs/enforcement-status.md`** — `notification-queue.md` row flipped 🟡 partial → ✅ wired with the Change B activation details.

### Added

- **`.pre-commit-config.yaml`** + **`templates/new-project/.pre-commit-config.yaml.tmpl`** — wire `verify_llm_routing` as a `local` hook (warn-only initially per D3.5; strict-mode promotion target 2026-06-05 after 30 green-build days). New consumers inherit the hook on bootstrap; existing consumers can opt in by adding the block to their own `.pre-commit-config.yaml`.
- **6 new tests in `tests/test_notify.py`** (durable queue path): warn-routes-via-queue + skips-SMTP; error-routes-via-queue; queue-disabled-falls-through; queue-package-missing-falls-through; enqueue-failure-falls-back; info-bypasses-queue. Total: 30 tests in test_notify.py (was 24).

### Notes

- Closes 2/3 deferred items from v0.9.3 follow-up note (Change C). Remaining: `consumer-d/lib/advisor.py` migration (separate consumer PR, manual 2-call paths to `_llm.call`; native Anthropic advisor-tool beta retains an inline-allow comment since LiteLLM cannot tunnel the `advisor_20260301` tool block). The "Hermes adapter" deferred item is a no-op — no Python adapter exists in-tree (Hermes is a separate container that already consumes the LiteLLM proxy directly via OpenAI-compatible API).
- The Change B wiring lands as a chore-level upstream PR because the contract change is consumer-driven (the OpenSpec proposal lives in consumer-d under `openspec/changes/add-durable-notification-queue/`); the upstream playbook absorbs the integration as documented mechanical follow-up.

## [0.9.3] — 2026-05-05 — dev-flow industrialization + Phase 5 P5.4/P5.6/P5.7

Major milestone release codifying the canonical task↔PR↔release pattern as the standard for any agent (Claude Code / Cursor / Antigravity / Gemini CLI / OpenCode) and human collaborating across modules. Closes the "where do I start?" gap with a single LLM-agnostic canonical entry point + CI gates that enforce the pattern + a skill orchestrator that runs it end-to-end. Also lands the Phase 5 bring-forward work (LiteLLM enforcement, IR + model-migration specs) deferred since v0.2.0.

### Added

#### Dev-flow industrialization (PRs #33, #34)

- **`docs/development-flow.md`** (new) — single LLM-agnostic canonical entry point for "how do I make a change in any playbook-consuming project?". 4-level hierarchy + 3 axes of parallelism (Wave-N / Intra-slice / Worktrees) + lifecycle + LLM-agnostic pointer table + industrialisation surface + 8 anti-patterns. Decisions D1.1–D1.5.
- **`specs/merge-policy.md`** (new) — squash vs merge-commit decision rules (D2.1–D2.4). Default merge-commit; squash bounded to trivial single-intent PRs.
- **`specs/conflict-resolution-policy.md`** (new) — 4-tier conflict taxonomy + 5-line escalation threshold + Wave-N coordinator role + intra-slice partitioning gate (D3.1–D3.6).
- **`skills/dev-flow/SKILL.md`** (new) — orchestrator skill: `/dev-flow start <description>` scaffolds OpenSpec change + branch + worktree (when ≥3 concurrent) + auto-tick git hook; `/dev-flow ship` validates + pushes + opens PR + monitors CI. Decisions D1.1–D1.6 + 3 anti-patterns.
- **LLM-agnostic pointers wired** from `templates/new-project/AGENTS.md.tmpl` §2 (every NEW consumer inherits) + `runbooks/INDEX.md` + `docs/index.md` + `docs/start-here.md` + playbook root `AGENTS.md`. NOT in `~/.claude/CLAUDE.md` per LLM-agnostic principle (per repo `README.md`: "CLI-specific routers are thin pointers").
- **`specs/release-management.md`** v1.2.0 → v1.3.0 — new §0 entry-point pointer to `development-flow.md`; scopes what release-management.md adds beyond it.

#### CI gates + git hook (Followup #4 closed)

- **`.github/workflows/branch-name-validator.yml`** (new) — enforces `<type>/<change-id>` branch names (types: feat/fix/chore/docs/refactor/test/release) + verifies `openspec/changes/<change-id>/` exists. Sticky PR comments on violation. Hard gate. Exempts dependabot, GitHub-auto-revert, release-prep, and `chore/*` branches.
- **`.github/workflows/check-tasks-checkboxes.yml`** (new, Followup #4 OPT 2) — soft enforcement: scans `tasks.md` of the affected change-id, posts sticky PR comment with checked/total/pct + first 10 unchecked items.
- **`scripts/auto_tick_tasks.py`** + **`templates/git-hooks/prepare-commit-msg`** (new, Followup #4 OPT 1) — git hook auto-ticks `- [ ]` boxes from conventional-commit subjects (`groups N-M`, `§N.M`, `tasks N,M,O`). Idempotent. Depth-aware scope tracking. Soft contract: never blocks commits.
- **`.github/workflows/pr-merge-style.yml`** (new) — advisor recommending squash vs merge-commit per `merge-policy.md` decision rules. Soft (informational comment).

#### Schema cross-ref enforcement (warn-only window)

- **`specs/bootstrap-directive.md`** v1.1.0 → v1.2.0 — adds Development-flow cross-ref requirement: every consumer's AGENTS.md §2 Dispatcher index MUST contain a row pointing to `.ai-playbook/docs/development-flow.md`. Phased rollout (Change C pattern): warn-only initially → strict after 30d green builds.
- **`scripts/schema_validate.py`** extended — body-level check for `development-flow.md` link. `--strict-dev-flow-cross-ref` flag promotes warn → error.
- **`scripts/propagate_bump.py`** extended — `ensure_dev_flow_cross_ref()` inserts the row in each consumer's AGENTS.md §2 in the same bump PR as the version bump. Idempotent. Already-present → no-op. (= **Opción 1 migration** from `development-flow.md` §3.3.)

#### Phase 5 bring-forward (PRs #31, #32)

- **PR #32** — `scripts/wt_add.py` post-create install (npm/pnpm/poetry/uv detection, lockfile-based, failure non-fatal); `.gitignore` ignore `notifications.jsonl` + `hindsight-queue.jsonl` (runtime logs).
- **PR #31** — Phase 5 P5.4: `configs/litellm-router.yaml` (11 task classes); `scripts/_llm.py` (canonical helper, `LITELLM_BASE_URL` proxy); `scripts/verify_llm_routing.py` (drift detector, warn-only initially per D3.5); `specs/model-routing.md` v2.0.0 + per-consumer virtual keys section in `env-vars.md`. Phase 5 P5.6+P5.7: `specs/incident-response.md` stub → v1.0.0 (8 S1–S4 scenarios + on-call ladder + 7-day post-mortem detector + comm templates + 4 stub recovery runbooks); `docs/model-migration.md` stub → v1.0.0 (trigger taxonomy + 6-step playbook + canary thresholds); 2 lifecycle_check detectors (`first_paying_client_detected`, `model_retirement_detected`); 2 dry-run simulators; `configs/anthropic-retirement-list.yaml`; new 🟠 wired-pending-trigger symbol in `enforcement-status.md`.

### Tests

- **`tests/test_dev_flow_industrialization.py`** (new): 31 tests across 5 classes — auto_tick_tasks parser + tick logic + CLI + schema_validate cross-ref warn-only/strict + propagate_bump cross-ref insertion.
- **`tests/test_llm_helper.py`** (new, PR #31): 16 tests for `_llm.call` + `verify_llm_routing.scan`.
- **`tests/test_activation_triggers.py`** (new, PR #31): 23 tests for the 2 lifecycle detectors + 2 simulators.
- **Full suite**: 763 passed, 2 skipped (integration tests requiring `AIPLAYBOOK_E2E=1`) — zero regression.

### Migration

- **New consumers** bootstrapped via `scripts/bootstrap.py` after v0.9.3 inherit the cross-ref row from the updated `AGENTS.md.tmpl`.
- **Existing consumers** (consumer-d, consumer-c-legacy, consumer-b, consumer-e, livekit) receive the cross-ref row automatically as part of the v0.9.3 bump PR opened by `propagate-playbook-bump.yml` — idempotent insertion via `propagate_bump.py::ensure_dev_flow_cross_ref()`.
- **Auto-tick git hook** is per-developer per-checkout (git does not version `.git/hooks/`). Manual install:
  ```
  cp .ai-playbook/templates/git-hooks/prepare-commit-msg .git/hooks/
  chmod +x .git/hooks/prepare-commit-msg
  ```
  OR invoke `/dev-flow start <description>` which installs it automatically.

### Notes

- Pending follow-ups (separate PRs after v0.9.3): migrate historical call sites (`lib/advisor.py`, `prompt_injection_filter.py:182`, Hermes adapter) to `_llm.call`; wire `verify_llm_routing.py` into pre-commit; archive 2 OpenSpec changes from PR #31 in consumer-d (`add-litellm-enforcement`, `complete-ir-and-model-migration-specs`).
- Dev-flow `--strict-dev-flow-cross-ref` flag stays default-off for the v0.9.3 → v0.10.x window; flip to default-on after 30 days green + ≥4/5 consumers migrated.

## [0.9.2] — 2026-05-01 — `openspec-apply-parallel` skill + filed followup #4

Patch release that ships a guided skill for the §6.6 intra-slice parallelism contract and files a fourth followup for tracking.

### Added

- **`skills/openspec-apply-parallel/SKILL.md`** — guided skill that wraps `specs/release-management.md` §6.6 (intra-slice parallelism). Encodes the gating questions (multi-group? disjoint write-paths? >30 min? pre-allocated migration numbers?), the ownership cross-check, the spawn matrix, the parallel-spawn pattern (single-message multi-Agent calls with `isolation: "worktree"`), the cherry-pick recombination order, and the anti-patterns. Falls back to `/opsx:apply` (sequential) when the gates don't pass. Architectural note: the skill is **declarative** — there is no Python orchestration script. The agent reads the skill + invokes the existing `Agent` tool primitives (worktree mode, gh CLI, git CLI). This matches the state-of-the-art "agent-as-orchestrator" pattern (Anthropic Agent SDK, OpenAI Swarm, LangGraph supervisor); a Python orchestration script would have been an anti-pattern that encloses the LLM's judgment in fixed control flow.
- **`specs/release-management.md` §6.6 cross-reference** — the section now opens with a pointer at the new skill, so an agent reading the spec discovers the operational entry point immediately.

### Filed (open)

- **Followup 4** in `specs/v0.9.0-roadmap.md` — `/opsx:apply` skill doesn't enforce `tasks.md` checkbox-update discipline. Surfaced by consumer-e slice 3 archive (merged with 0/55 tasks ticked despite being feature-complete). Three fix options outlined: (1) conventional-commit scope → checkbox auto-tick via `prepare-commit-msg` hook, (2) PR-open warning workflow, (3) `openspec archive --strict` mode. Recommended: ship 1 + 2 in a future v0.9.x patch; defer 3.

### Notes

- This is a doc + skill release. No script changes; no test additions. Cascade behaviour identical to v0.9.1 (auto-bump AGENTS.md `inherits_from` for all 5 consumers via `bump_agents_md_pin`).

## [0.9.1] — 2026-05-01 — close v0.9.0 followups (#1 #2 #3)

Patch release that addresses the 3 followups carried into v0.9.x from the v0.9.0 stable release. Each was a real production gap surfaced during the consumer-e cascade dogfood. Now all three are fixed + covered by tests.

### Fixed

- **Followup #1 — `propagate_bump.py` now bumps `AGENTS.md inherits_from` for every consumer.** Previously only `propagate_skills_bump.py` rewrote frontmatter pins, and only for consumers with `skills_pins:` declared in `consumers.yaml`. livekit (no skills tracking) ended every cascade with stale `inherits_from:` and required a manual fix-PR each time. The `_edit_frontmatter_skills_source` helper has been moved to `scripts/_bumper.py::bump_agents_md_pin` and is now called by BOTH propagation scripts. The same regex matches `inherits_from:` items (with the `github.com/` prefix) and `skills_sources:` items (without) in one pass.
- **Followup #2 — `_bumper.supersede_open_bump_prs()` is now semver-aware.** Previously it used "newer-PR-by-creation-time wins" — when multiple tags pushed close together (rc1 + rc2 cycle 2026-05-01), workflow scheduling determined order, not semver, and v0.8.7's PRs closed the newer v0.9.0-rc2 PRs (recovery required deleting + re-pushing the rc2 tag). The function now parses the head-branch's version (`chore/bump-(playbook|skills-*)-vX.Y.Z[-rc.N]`), compares via tuple key (stable releases sort above their rcs of the same series; older series sort below newer), and only closes an open PR whose parsed version is `<=` the new bump's. Backward-compatible: callers that omit the new `new_branch` argument fall back to chronological mode + log a warning.
- **Followup #3 — `block_manual_spec_edit.py::read_commit_message()` now handles CI mode.** Previously it only read `$PRE_COMMIT_COMMIT_MSG_FILE` (commit-msg stage) and `.git/COMMIT_EDITMSG` (fallback) — but in CI's `pre-commit run --from-ref/--to-ref` mode neither is set, so every archive PR saw "commit message unavailable" and required `--admin` merge to bypass (consumer-e PR #57 was the surfacing case). The function now ALSO runs `git log --format=%B%x00 $FROM..$TO` and concatenates every commit message in the range, so the `openspec-archive:` marker is detected if it appears in ANY commit on the branch.

### Added (operational guard)

- **`runbooks/release.md` Step 3** — pre-tag chronology check codified. Before tagging, verify the previous tag's `propagate-playbook-bump` workflow is `completed success` AND that `git log <prev-tag>..HEAD` is non-empty. The semver-aware supersede in `_bumper.py` is the code-side defence; this runbook step is the operational guard so devs don't rely on script correctness when tagging close together.

### Tests

- **`tests/test_bumper.py`** (new): 16 tests covering `bump_agents_md_pin` (rewrites both blocks; idempotent at-target; comments + indentation preserved; missing file / no-frontmatter detection) AND semver-aware supersede (out-of-order tag push doesn't close newer; v0.9.0 stable closes all prior rcs/series; backward-compat fallback when `new_branch` missing; unparseable open branches skipped) AND `_parse_branch_version` (rc < stable; rc number ordering; series ordering across major/minor/patch).
- **`tests/test_block_manual_spec_edit.py`** (extended): 4 new tests covering CI mode (`PRE_COMMIT_FROM_REF/TO_REF` env vars are read; marker detected in any commit of the range; local stage takes precedence; legacy `.git/COMMIT_EDITMSG` fallback still works).

### Migration

- No consumer migration required. The `bump_agents_md_pin` helper is invoked from `propagate_bump.py` automatically on every future tag push; previously-stale `inherits_from:` lines will self-heal on the next bump.

## [0.9.0] — 2026-05-01 — CodeRabbit fallback STABLE — slice 3 dogfood validated end-to-end

Promotes v0.9.0-rc1 (CodeRabbit fallback 3-layer defense) → stable after the validation milestone (`specs/v0.9.0-roadmap.md`) completed successfully on consumer-e slice 3 (`persistence-tenant-enforcement`).

### Validation evidence (consumer-e cascade 2026-05-01)

- **PR #52** (`coderabbit-fallback-l2-setup`): bootstrap dogfood. Submodule + L2 workflow installed via `runbooks/onboard-new-project.md` Step 11. CodeRabbit was rate-limited at the moment of PR open (the EXACT scenario the L2 design exists for). L2 fired at 5m11s, classified `rate-limited`, posted the structured checklist as a PR comment when §4.5 was empty/stubbed, and turned `ai-self-review-required` ✅ after the PR body was updated with the 3 schema markers (`Profile:`, `Reviewer:`, `Self-review findings:`). Squash-merged into `main`.
- **PR #55** (`slice/persistence-tenant-enforcement`): L1 in-session §4.5 populated by claude-code-action; CodeRabbit reviewed without rate-limit; L2 skipped silently (status check ✅). 56 tasks / 30 new tests / 95% coverage on `persistence/*` / 154 passed combined / mypy strict clean / pre-commit clean.
- **PR #56** (`chore/ux-scaffolding-draft`): L1 in-session §4.5 populated; CodeRabbit reviewed; L2 skipped silently. Squash-merged.

The 3-layer architecture worked exactly as designed: L0 (CodeRabbit primary) handled the bulk; L1 (worker self-review) covered every PR; L2 (CI safety net) caught the rate-limit case on PR #52 without false positives on the others.

### Changed (since v0.9.0-rc3)

- **`templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`**: add `token: ${{ secrets.consumer-d_GOD_MODE }}` to `actions/checkout@v4` step. Required when the consumer pins `.ai-playbook` (and optionally `.skills-sources/ai-playbook`) as submodules of the PRIVATE `Wizarck/ai-playbook` repo. The default `GITHUB_TOKEN` scope is consumer-repo only; cross-repo submodule clone needs `Contents:R` on the playbook + skills repos. Mirrors `ci.yml`. Caught during PR #52 dogfood; consumer-e's runtime workflow was patched in-PR. Per gotchas #7. Followup tracked from v0.9.0-rc1 closed.

### Added (since v0.9.0-rc3)

- **`specs/release-management.md` §6.6 Intra-slice parallelism** (originally landed under "Unreleased" between rc3 and stable): orthogonal to wave-level (§6.4). Codifies how a main agent spawns subagents inside one slice when the slice covers multiple disjoint bounded contexts. Pre-conditions (write-path ownership in `tasks.md`, migration-number pre-allocation, shared-file reservation), spawn pattern (`Agent isolation: "worktree"` with ephemeral side-branches `slice/<id>--<group>`), recombination via cherry-pick, anti-patterns (cross-ownership edits, public-branch pushes), and the cost-benefit threshold (~30 min of parallelisable work).
- **`specs/runbook-bmad-openspec.md` §3.8**: brief pointer to §6.6, distinguishing intra-slice from wave-level parallelism.

### Open followups (carried into v0.9.x)

- **`scripts/propagate_bump.py`**: doesn't bump `AGENTS.md` `inherits_from` field on consumers. Manual fix in livekit PR #36 surfaced this. Filed in `specs/v0.9.0-roadmap.md`.
- **`scripts/_bumper.py` supersede logic**: uses tag-push chronology, not semver order. Out-of-order tag push superseded newer PRs with older ones during the v0.9.0-rc1/rc2 cycle. Filed in `specs/v0.9.0-roadmap.md`.
- **`/opsx:apply` skill**: doesn't enforce tasks.md checkbox-update discipline. Slice 3 implementation merged with 0/55 boxes checked despite being feature-complete (verified by tests + coverage). To file as a v0.9.x followup.

## [0.9.0-rc3] — 2026-05-01 — bare-repo + per-branch worktree layout (default for new consumers)

Codifies the directory layout senior-developer practice (Cugerone, Medeski, ChristopherA) recommends for projects that ship in waves of 5–10 concurrent OpenSpec slices. The implicit pre-v0.9.0 default (single working tree at `<repo>/`) saturated in consumer-c-legacy Module 2 (11 concurrent changes); the new layout makes every change-id a peer subdirectory under one parent, sharing one `.bare/` git database.

Existing consumers on the legacy single-tree layout keep working — migration is opt-in via the new runbook §3.

### Added

- **[`specs/git-worktree-bare-layout.md`](specs/git-worktree-bare-layout.md)** (v1.0.0): the layout contract — directory shape, naming rules (worktree dir == OpenSpec change-id), invariants I1–I5, rationale (bare+per-branch vs sibling-suffix vs centralised pool), tooling pointers, registry compatibility. Cross-references `dispatcher-chain.md` and `release-management.md`.
- **[`runbooks/git-worktree-bare-setup.md`](runbooks/git-worktree-bare-setup.md)** (v1.0.0): operational runbook covering 4 scenarios — §1 greenfield bootstrap, §2 onboard existing repo, §3 migrate from legacy single-tree, §4 daily flow (add/remove worktrees). §3.5 documents the Windows cwd-lock workaround (rename a project root locked by an open editor session).
- **[`scripts/wt_add.py`](scripts/wt_add.py)** (~280 LOC): one-command worktree creation. Auto-detects default branch via `origin/HEAD`; refuses change-ids without a matching `openspec/changes/<id>/` folder unless `--no-slice-check`; initialises submodules in the new worktree by default. Dry-run mode.

### Changed

- **`specs/runbook-bmad-openspec.md`**: new §3.7 "On-disk layout for concurrent slices" cross-references the new spec + runbook + script. §3.6 (branch + PR + merge contract) unchanged — the layout sits **under** the existing 1 branch = 1 change = 1 PR rule.
- **`runbooks/INDEX.md`**: new row pointing at `git-worktree-bare-setup.md`.
- **`specs/INDEX.md`**: regenerated to include `git-worktree-bare-layout.md`.

### Notes

- Migration from legacy is **not breaking**: the `path` entry in `~/.ai-playbook/projects.yaml` is unchanged (the dispatcher resolution treats it as parent-of-cwd, so cwd in `<repo>/master/` still resolves through the same registry entry as cwd in `<repo>/` did).
- First real-world migration: consumer-c-legacy, 2026-05-01. Lessons folded back into the runbook §3.5 (Windows cwd-lock workaround) and §3.6 (`git worktree repair` as the recovery step after the rename).
- The naming rule "worktree dir == openspec change-id" is enforced by `wt_add.py` but **not** retroactively imposed: consumer-c-legacy still has `m1-ingredients/` while its change-id is `module-1-ingredients-implementation`. This mismatch is cosmetic and will be cleaned up after the slice merges. Future slices use exact names.

## [0.9.0-rc2] — 2026-05-01 — rolls v0.8.7 forward into the v0.9.0 line

Cut to recover from a tag-ordering miss: the v0.8.7 fix (`opsx_apply_companion` default-branch auto-detect, commit `8ea91e4`) landed on `main` 3m34s **AFTER** v0.9.0-rc1 was tagged + propagated. Consumers that merged the v0.9.0-rc1 bump PR (all 5) ended up with the **broken** companion that hardcodes `origin/main` — which fails on `master`-default repos (consumer-c-legacy, by design).

rc2 is the v0.9.0-rc1 bundle PLUS the v0.8.7 fix folded in. Also adds the retroactive `v0.8.7` and `v0.8.8` tags (info-only — `v0.8.8` content was already in rc1's bundle; `v0.8.7` content is new in rc2).

### Fixed (carried forward from v0.8.7)

- **`scripts/opsx_apply_companion.py::_detect_default_branch()`** — reads `origin/HEAD` (e.g. `refs/remotes/origin/main`), falling back to a literal probe of `origin/main` then `origin/master` then any other ref present. Slice branches now rebase against the actual default branch instead of a hardcoded `main`. Critical for consumer-c-legacy (default branch = `master`).

### Notes

- All v0.9.0-rc1 features are preserved verbatim (L1 detection script, L2 workflow + checklist script, runbook, spec §4.5.1-3, bootstrap integration). See [v0.9.0-rc1] entry below.
- Process gotcha: when a fix-PR merges to main between the tag-cut and the propagation-finish window, it falls between two semver releases. Mitigation idea for v0.9.x: a pre-tag check in `runbooks/release.md` Step 3 that diffs `git log origin/main..HEAD` and aborts if there are uncommitted-into-tag fixes. Filed as a follow-up; not blocking rc2.

## [0.9.0-rc1] — 2026-05-01 — CodeRabbit fallback (3-layer defense)

Codifies the manual Profile-B fallback the worker AI applies when CodeRabbit is rate-limited or silent. Turns it into a 3-layer defense (L0 mechanical / L1 in-session AI / L2 GH Action safety net) with L1 ↔ L2 coordination via PR-body §4.5 regex check. See [`specs/v0.9.0-roadmap.md`](specs/v0.9.0-roadmap.md) for the design rationale (incl. 4 alternatives considered + tradeoff analysis).

### Added

- **L1 — `scripts/check_coderabbit_status.py`** (~80 LOC): polls `gh pr view --comments` for CodeRabbit; classifies into `available` / `rate-limited` / `silent` / `error`. Returns JSON on stdout + exit codes (0/1/2/3). Pure stdlib + `gh` CLI; no API token.
- **L1 — [`runbooks/coderabbit-fallback.md`](runbooks/coderabbit-fallback.md)**: structured guide for the worker AI when L1 fires. 7-category diff inspection (type / async / errors / security / edge cases / public API / spec compliance) + canonical §4.5 schema + 5 anti-patterns + reference run (consumer-e PR #41).
- **L2 — `scripts/post_self_review_checklist.py`** (~280 LOC): reads PR diff + body; if §4.5 is populated (3 markers + non-stub), exits silently and marks status check ✅; if empty/stubbed, posts a structured fallback checklist as a PR comment + marks status check ❌. Markdown bold (`**Profile**:`) is normalised to plain (`Profile:`) before matching.
- **L2 — `templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`**: GH Action (`pull_request: [opened, synchronize]`). Sleeps 5 min, runs detection + checklist scripts. Skips dependabot/renovate/github-actions PRs. `secrets.GITHUB_TOKEN` only — no PAT.
- **`scripts/bootstrap_gh_project.py`**: `apply_profile()` now copies the new workflow under both Profile A and Profile B (the L2 status check is informational unless added to required-checks manually). Helper: `write_coderabbit_fallback_workflow()`. Idempotent; "delete to refresh" semantics.
- **Tests**: 46 new tests (20 for `check_coderabbit_status` + 26 for `post_self_review_checklist`) covering happy paths, error paths, edge cases. All green.

### Changed

- **`specs/release-management.md`**: 3 new subsections under §4.5 — §4.5.1 (L1 worker-AI in-session check, MUST after every PR push), §4.5.2 (L2 CI safety net + ai-self-review-required status check semantics), §4.5.3 (PR-body schema regex contract: 3 mandatory markers + STUB_INDICATORS exclusion list). All additive — existing §4.5 unchanged.
- **`runbooks/release.md`** Step 7: replaces generic "wait for CodeRabbit" with explicit `check_coderabbit_status.py --pr ... --wait 300` invocation + Profile B fallback path; clarifies how L1 ↔ L2 interact on bump PRs. Step 8 mentions that bootstrap re-run now propagates the L2 workflow.
- **`runbooks/onboard-new-project.md`** Step 11: adds `coderabbit-fallback.yml` to the manual `cp` list with note that `bootstrap_gh_project.py` copies it automatically (v0.9.0+).

### Notes

- **Status check `ai-self-review-required` is opt-in** by default — informational, not in required-checks. Profile A consumers add it manually if they want strict enforcement (avoids breaking in-flight PRs at v0.9.0 rollout).
- **Validation plan**: validate L1 + L2 on `consumer-e` slice 3 (`persistence-tenant-enforcement`) before tagging stable. If both layers behave clean → tag `v0.9.0` stable → cascade to all 5 consumers.
- **Trade-offs documented in roadmap**: L1 blocks the AI session for ~5 min per PR (acceptable; evolve to background-poll if annoying); L2 generates a redundant comment if L1 was slow (mitigated by body-check just-before-post; small race window); 4 alternatives rejected (Ollama, only-L1, only-L2, GH Merge Queue).

## [0.8.8] — 2026-05-01 — propagate-skills-bump ships submodule advance + skills mirror in one PR

Surfaced 2026-05-01 in consumer-c-legacy: `AGENTS.md` frontmatter said `Wizarck/ai-playbook@v0.8.6` but `.skills-sources/ai-playbook` submodule pointer was still at v0.7.1 (`8d5f68c`), and `skills/` tracked mirror was stale relative to the new tag's contents. Every consumer would have needed a manual `bootstrap.py --refresh-skills` after merging the bump PR — silent half-propagation.

### Fixed

- **`scripts/propagate_skills_bump.py::_propagate_one()`** — after editing `AGENTS.md` frontmatter (the existing v0.8.x behaviour), the script now also runs `materialise_skills()` from `_skills_materialiser.py` to:
  1. Advance the `.skills-sources/<source>/` submodule pointer to the new tag's SHA.
  2. Regenerate the tracked `skills/` mirror with the new tag's contents.
  3. Regenerate the `.claude/skills/` and `.gemini/skills/` mirrors locally (gitignored — not committed; consumer machines regenerate them on the SessionStart hook).

  The bump commit now stages `AGENTS.md` + `.gitmodules` (when first-ever submodule add) + `.skills-sources/<source>/` + `skills/`. Single PR ships fully-propagated state. Consumers no longer need `bootstrap.py --refresh-skills` after merge.

  PR description updated to reflect the new contract: lists the three concrete artefacts the commit ships (frontmatter, submodule pointer, tracked skills mirror) and the gitignored mirrors that regenerate on SessionStart.

### Migration

Bump submodule (previous → v0.8.8). Verified end-to-end against consumer-c-legacy:
- Pre-fix state: AGENTS.md@v0.8.6 + submodule@v0.7.1 (drift).
- `materialise_skills(consumer-c-legacy-m1)` → 123 skills materialised from 2 sources, 2 mirrors regenerated, submodule advanced 8d5f68c → cd31441 (v0.8.6), no errors.
- Post-fix state: AGENTS.md@v0.8.6 + submodule@v0.8.6 + skills/* tracked mirror regenerated.

## [0.8.7] — 2026-05-01 — opsx_apply_companion supports `master` default branch

Surfaced when consumer-c-legacy (`master` default branch) ran the companion before its first M1 slice commit and got `git rev-parse origin/main` exit 128.

### Fixed

- **`scripts/opsx_apply_companion.py`** — auto-detects the remote's default branch instead of hardcoding `origin/main`. Order of resolution:
  1. Read `git symbolic-ref refs/remotes/origin/HEAD` (the modern git canonical pointer; e.g. `refs/remotes/origin/main` or `refs/remotes/origin/master`).
  2. Fallback probe: try `origin/main` first, then `origin/master` via `git rev-parse --verify --quiet`. First hit wins.
  3. If neither resolves, exit 2 with a remediation hint (`git remote set-head origin --auto` or `--default-branch <name>`).

  Also: new `--default-branch <name>` CLI flag for explicit override (fresh clones with no `origin/HEAD`, repos targeting a non-canonical default like `develop`).

  Backwards-compatible: `main`-default repos see no behaviour change. `master`-default repos work without flags. The `Base SHA` field on the project board now records the SHA of whichever default the repo actually uses.

### Migration

Bump submodule v0.8.6 → v0.8.7. Verified against:
- consumer-c-legacy (`master` default) — runs cleanly, captures Base SHA from `origin/master`.
- ai-playbook (`main` default) — backwards-compatible.

## [0.8.6] — 2026-05-01 — DESIGN.md format spec + Google design.md tier 1 adoption

Extends `specs/ux-track.md` con tier 1 adoptions de [google-labs-code/design.md](https://github.com/google-labs-code/design.md) (Apache-2.0, alpha, 10.5k stars). DESIGN.md becomes hybrid format: machine-readable YAML frontmatter tokens + human-readable markdown rationale.

### Added

- **`specs/ux-track.md` §11 — DESIGN.md format spec** (NEW section, 175 lines). Subsections:
  - §11.1 Hybrid format (YAML frontmatter + Markdown body)
  - §11.2 Token schema (colors, typography, rounded, spacing, components)
  - §11.3 Token reference syntax `{path.to.token}`
  - §11.4 8 canonical sections + ai-playbook extensions (Iconography preserved as unknown section per defensive parsing)
  - §11.5 Component variants pattern (`name-state` keys: `button-primary` + `button-primary-hover`)
  - §11.6 Consumer behavior table for unknown content (defensive parsing)
  - §11.7 Dual color representation (OKLCH canonical en CSS runtime + hex computed equivalents en YAML for tooling)
  - §11.8 Tooling integration (Google CLI `lint`/`diff`/`export` opcional + future ai-playbook custom validator path)
  - §11.9 Reference to source format

- **`templates/ux/DESIGN.md.template`** updated con YAML frontmatter machine-readable tokens schema (colors with hex computed equivalents + OKLCH derivation comments, typography roles, spacing, rounded, components con variants pattern).

### Changed

- **`specs/ux-track.md` §10 OKLCH-canonical rule** — added "Dual representation" paragraph cross-referencing §11.7. The CSS surfaces declare OKLCH canonical; YAML frontmatter declares hex computed equivalents. OKLCH remains source-of-truth; hex is one-way derivation snapshot. Tooling consumers MUST NOT round-trip hex → OKLCH.

- **`specs/ux-track.md` §11..§19 renumbered to §12..§20** (per-journey docs format → §12, Components catalogue → §13, ...). Internal §-references updated atomically.

### Pilot validated

`consumer-d/docs/ux/DESIGN.md` (Z.2 Phase 2 consumer-d dashboard, palette D Things 3 Night, variant D Structured timeline). Format verified production-ready: YAML schema consumido por agentes, OKLCH canonical en CSS runtime, hex equivalents en YAML, Iconography section preservada como ai-playbook extension sin breaking Google CLI tooling.

### Compatibility

ai-playbook keeps unique value:
- OKLCH-canonical color discipline (perceptual luminance > Google's hex-only sRGB)
- Visual-first 3-step (inspiration → palette → variants per §3)
- 5 creative engines starter set (§5.1)
- Per-journey `jN.md` + companion mocks (§12)
- Phase A scrub + Phase B consolidation (§9)
- Anti-pattern hand-coded mocks (§16)
- Audit head-comment WCAG verification block (§6.2)
- Storybook-style components catalogue (§13)

Adopted from Google (5 deltas):
- YAML frontmatter machine-readable tokens
- Token reference syntax `{path.to.token}`
- Component variants pattern (`name-state` keys)
- 8-section canonical order alignment
- Consumer behavior defensive parsing table

### Migration

Bump submodule v0.8.5 → v0.8.6. No code change required for consumer
projects; pilot consumer (`consumer-d`) already shipped a DESIGN.md in
the new format (commit ee41792). Other UI-consumer projects can adopt
the format incrementally — old DESIGN.md files without YAML frontmatter
remain valid (defensive parsing per §11.6).

## [0.8.5] — 2026-05-01 — INDEX + AGENTS.md template updates for v0.8.x

Documentation patch — no functional changes. Continues the v0.8.4 docs
sweep with two additional surfaces.

### Updated

- **`specs/INDEX.md`**: `release-management.md` entry bumped from v1.0.0
  description to v1.2.0 description. Now lists the §3.4 supersede,
  §4.4 pre-commit diff mode, §4.5 AI-reviewer feedback loop, §5.5
  trace fields (Branch + Base SHA), §5.6 Profile A/B, §6.5 pre-flight
  rebase additions explicitly so consumer projects browsing the INDEX
  see them at-a-glance.

- **`templates/new-project/AGENTS.md.tmpl`**:
  - Bootstrap directive (§0) now requires reading `release-management.md`
    at session start in addition to `dispatcher-chain.md`. Calls out the
    critical sections (§4.5, §5.6, §6.5).
  - Capability map (§5) gains 4 new entries: `opsx_apply_companion.py`
    (pre-flight), `bootstrap_gh_project.py --profile auto`,
    `auto_transition_blocked_todo.py`, `check_slice_dependencies.py`.

### Migration

Bump submodule v0.8.4 → v0.8.5. Existing consumers' AGENTS.md files are
NOT auto-rewritten (they are project-owned), but the spec contract in
release-management.md §0 is what the AI loads at session start anyway.
New consumers onboarded via `bootstrap.py` get the updated template.

To retroactively add the bootstrap directive + capability entries to
existing consumers' AGENTS.md, copy the relevant sections from
`templates/new-project/AGENTS.md.tmpl` v0.8.5 manually.

## [0.8.4] — 2026-05-01 — Runbooks updated for v0.8.x release-management

Documentation patch — no functional changes. Brings the runbooks
constellation in lockstep with the v0.8.0–v0.8.3 functional changes
(Profile A/B, AI-reviewer feedback loop, supersede, /opsx:apply
companion, date refresh, auto-transition + dep-check scripts).

### Updated

- **`runbooks/release.md` v1.1.0**: adds rc-first mode for breaking
  releases; adds Step 7 "AI-reviewer signoff per consumer" and Step 8
  "post-merge bootstrap re-run with `--profile auto`"; adds Quick-
  reference flow diagram for the post-v0.8.x release sequence;
  documents supersede behavior in Step 6.

- **`runbooks/onboard-new-project.md` v1.1.0**: adds Profile A/B
  decision matrix as a "decisión previa"; adds Step 7 "Bootstrap GH
  Project + Profile A/B enforcement"; adds Step 8 "Install CodeRabbit
  GH App" (Profile A only); adds Step 9 "Configure consumer-d_GOD_MODE
  secret" for private-submodule CI; adds Step 11 "Copy auto-transition
  + dep-check workflow templates"; refreshes cross-references with new
  scripts + templates.

- **`runbooks/propagate-bump-troubleshooting.md` v1.1.0**: adds
  "Expected behaviors (v0.8.0+)" section explaining supersede +
  date refresh as features (not bugs); adds Pattern F "supersede
  helper failure" with manual-cleanup fix; adds Pattern G "pre-v0.8.3
  stale updated: date" as historical context (fixed in v0.8.3).
  Updates diagnosis flow to include the new patterns.

### Migration

Bump submodule v0.8.3 → v0.8.4 to pull the runbook updates locally.
No code change required.

## [0.8.3] — 2026-05-01 — /opsx:apply companion + skills-bump date refresh

Closes the last two pending follow-ups from the v0.8.0 release-management
overhaul.

### Added

- **`scripts/opsx_apply_companion.py`** (per release-management.md §6.5):
  Branch + Base SHA capture + pre-flight rebase as a CLI companion to the
  upstream-managed `openspec-apply-change` skill. The skill itself is
  re-generated by `npx openspec` so we cannot embed §6.5 logic inside it;
  instead, the worker AI invokes this companion BEFORE the first task
  commit on `slice/<change-id>`.

  Behavior:
  1. Verify clean working tree (fail if dirty).
  2. `git fetch origin`.
  3. Capture `Base SHA = git rev-parse --short origin/main`.
  4. If on `slice/<change-id>`: `git rebase origin/main`. Conflict →
     abort + exit 1 (worker AI MUST notify human; do NOT auto-resolve).
  5. Set `Branch` + `Base SHA` text fields on the matching project item
     via GraphQL (calls `ensure_trace_fields()` if absent).

  Idempotent. CLI:

  ```bash
  python -m scripts.opsx_apply_companion \\
      --change-id <slice> --owner <user> --project-number <N> --repo <owner/repo>
  ```

  `release-management.md` §6.5 now references this script explicitly so
  the contract has a runnable implementation.

### Fixed

- **`scripts/propagate_skills_bump.py`** (gotcha surfaced 2026-05-01):
  `_edit_frontmatter_skills_source()` now refreshes the `updated:` line
  in lockstep with `skills_sources` rewrites. Previously, automated
  bumps left AGENTS.md frontmatter with a stale date — observed in
  consumer-e's PR #32 (rc7 bump) where AGENTS.md kept `updated:
  2026-04-30` after a 2026-05-01 bump.

### Migration

Bump submodule v0.8.2 → v0.8.3. After merge, the next propagate-skills-
bump cycle will refresh `updated:` dates correctly.

For consumers ready to start slice work: invoke the companion as the
first step of `/opsx:apply` work. See `release-management.md` §6.5 for
the full contract.

## [0.8.2] — 2026-05-01 — Auto-transition + dep-check scripts (workflow templates ride-along)

Completes the v0.8.0 promised features. The
`.github/workflows/project-status.yml.tmpl` and `dep-check.yml.tmpl`
templates shipped in v0.8.0 now have their backing scripts.

### Added

- **`scripts/auto_transition_blocked_todo.py`** (per release-management.md §6.3):
  walks the project board for items with Status=Blocked, looks up each
  item's `Depends on` from `docs/openspec-slice.md`, and transitions to
  Status=Todo when every dep has Status=Done. Idempotent. Reuses
  `parse_slicing()` + GraphQL helpers from `bootstrap_gh_project.py` so
  the slicing format and Status schema stay synchronized. Supports
  `--dry-run` for safe preview.

  CLI: `python -m scripts.auto_transition_blocked_todo --owner X --project-number N --slicing-file docs/openspec-slice.md`

  Wired by `templates/new-project/.github/workflows/project-status.yml.tmpl`
  on push to main. Smoke-tested on consumer-e Project #2 (correctly
  identifies 1 transitionable + 17 still-blocked-with-unmet-deps + 2
  other-status items across the 20-slice plan).

- **`scripts/check_slice_dependencies.py`** (per release-management.md §6.2):
  hard enforcement of the dependency graph at PR merge time. Given a
  change-id from `slice/<change-id>`, walks declared deps and FAILS
  (exit 1) if any dep is not yet Status=Done. Outputs structured CI
  annotations listing each dep's current status. PASS (exit 0) when all
  deps are Done OR slice has no declared deps.

  CLI: `python -m scripts.check_slice_dependencies --owner X --project-number N --slicing-file docs/openspec-slice.md --change-id <slice>`

  Wired by `templates/new-project/.github/workflows/dep-check.yml.tmpl`
  on PR open. OPT-IN: branch protection's required-status-checks must
  include "Dependency check" for the workflow to actually block merge.

### Migration

Bump submodule v0.8.1 → v0.8.2. Consumers that copied the workflow
templates from v0.8.0 (and saw graceful "script not found" warnings)
will now get the actual transitions / checks.

For Profile A consumers: add "Dependency check" to `--required-checks`
on next bootstrap run if hard dep enforcement is desired (opt-in).

## [0.8.1] — 2026-05-01 — AI-reviewer feedback loop + bootstrap UX fixes

Closes the gap surfaced when the v0.8.0 rollout itself admin-merged 5 PRs
without checking CodeRabbit's feedback. The flow ASSUMED the AI reviewer
was a defense layer; the SPEC didn't enforce that the worker AI read its
output. v0.8.0 was rate-limited so no real comments were missed in
practice, but the audit trail had no record of comments being read at all.
v0.8.1 codifies the contract.

### Added

- **`specs/release-management.md` v1.2.0**:
  - **§4.5 AI-reviewer feedback loop**: worker AI MUST poll for the
    reviewer's "review completed" check, read `gh pr view <N> --comments`,
    triage every actionable comment (address / reject with reason / defer
    to follow-up), re-poll until clean, AND populate the new
    "AI-reviewer signoff" subsection in the PR body before requesting
    Gate F. Profile B repos (no AI reviewer) degrade to self-review with
    structured logging.
  - **§3.2 PR body template**: new `## AI-reviewer signoff` subsection.
  - **§9 anti-patterns**: 2 new — skipping AI-reviewer triage, clicking
    auto-merge before §4.5 satisfied.

### Fixed

- **`scripts/bootstrap_gh_project.py`**:
  - **gotcha #13**: `apply_branch_protection()` now auto-detects the
    repo's default branch via `detect_default_branch()` (queries
    `gh repo view --json defaultBranchRef`). No longer hardcodes `main`.
    consumer-c-legacy (default `master`) and other legacy consumers now work.
  - **gotcha #12**: `apply_branch_protection()` now UNIONS `required_checks`
    with the existing protection's contexts via
    `fetch_existing_required_checks()`. Re-running bootstrap no longer
    silently drops project-specific checks (AGPL boundary, LICENSE
    checksums, etc.). New informational output: `+ adding N new check(s)`
    and `+ keeping M existing check(s)`.

### Migration

Consumers on v0.8.0 → v0.8.1: bump submodule pointer (auto-PR via
propagate-bump). After merge, optionally re-run bootstrap to pick up the
default-branch detection (no-op on consumers already on `main`).

For Profile A consumers that lost project-specific checks during a v0.8.0
bootstrap re-run, rerun with the FULL list to add them back; v0.8.1's
UNION semantics will preserve them on subsequent calls.

## [0.8.0] — 2026-05-01 — Profile A/B + Branch+SHA + supersede + spec-edit fix (stable)

Promotes v0.8.0-rc7 to stable after validation against consumer-e. The
supersede logic was demonstrated **end-to-end in production**: when the rc7
propagate-bump fired against 5 consumers, 30+ stale `chore/bump-playbook-*`
PRs (v0.7.0 through rc6, accumulated across 6 prior tag pushes in 4 of the
5 consumers) were auto-closed within a 60-second window — exactly the
pile-up failure mode the supersede helper was designed to prevent.

This stable promotion contains zero functional changes vs rc7. See the
rc7 entry below for the full feature list. The rc7 → stable validation
matrix:

- consumer-e (Profile A, public): bumped, both bump PRs CI green incl.
  CodeRabbit review, merged via `--admin`. `bootstrap_gh_project.py
  --profile auto` ran idempotently — 0 schema additions (everything was
  already manually applied 2026-04-30→05-01), Profile A re-applied.
- 4 other consumers received clean rc7 bump PRs with all prior PRs
  superseded: consumer-c-legacy (closed 8 stale PRs), consumer-d (closed 8),
  consumer-b (closed 8), livekit (closed 8). Net: 32 PRs auto-closed,
  4 fresh PRs opened.

## [0.8.0-rc7] — 2026-05-01 — Profile A/B + Branch+SHA + supersede + spec-edit fix

Substantial release-management upgrade surfaced through consumer-e slice 1
dogfooding (2026-04-29 → 2026-05-01). Codifies the visibility-driven
enforcement model so consumer projects pick the right setup automatically,
adds trace fields for slice-branch diagnostics, and fixes two upstream bugs
that made every consumer PR fail.

### Added

- **`specs/release-management.md` v1.1.0** (PR #13):
  - §3.4 Bump-bot supersede expectation: each new `chore/bump-*` PR auto-
    closes prior open PRs on the same change-stream.
  - §4.4 Pre-commit MUST run on the PR diff in CI (`--from-ref/--to-ref`),
    not `--all-files`. Stops legacy-file false-positives.
  - §5.5 Trace fields `Branch` + `Base SHA` on every consumer's project board.
  - §5.6 Visibility-driven enforcement profile (A: Public OSS, B: Private Solo).
  - §6.5 Pre-flight rebase before slice start.
  - §8.1 Migration matrix for Arturo's 8-consumer constellation (May 2026).
- **`scripts/bootstrap_gh_project.py` `--profile {auto,public,private}`** (PR #14):
  - Detects repo visibility and applies branch protection + auto-merge
    + .coderabbit.yaml (Profile A) or repo settings only (Profile B).
  - New `--required-checks` flag for required CI status check names.
  - Adds `Branch` + `Base SHA` TEXT fields to project schema (idempotent).
  - New helpers: `detect_repo_visibility`, `apply_branch_protection`,
    `apply_repo_settings`, `write_coderabbit_template`, `ensure_trace_fields`.
- **Templates** (PR #15):
  - `templates/new-project/.coderabbit.yaml.tmpl` — Profile A copy target.
  - `templates/new-project/.github/workflows/project-status.yml.tmpl` — auto-
    transitions Blocked → Todo on dependency merge (§6.3).
  - `templates/new-project/.github/workflows/dep-check.yml.tmpl` — opt-in
    hard dep-graph enforcement at PR merge time (§6.2).

### Fixed

- **`scripts/_bumper.py`** (PR #16): added `supersede_open_bump_prs()` helper
  closing any open PR whose head branch starts with the given prefix when a
  newer bump PR opens. Wired into both `propagate_bump.py` (prefix
  `chore/bump-playbook-`) and `propagate_skills_bump.py` (per-source prefix
  `chore/bump-skills-<source>-`). Prevents the rc1→rc6 pile-up of 10 stacked
  pairwise-conflicting PRs observed in consumer-e.
- **`scripts/block_manual_spec_edit.py`** (PR #16): hook now intersects
  input candidates with the actual diff (`git diff --cached` /
  `--from-ref/--to-ref` / `HEAD~1..HEAD`) before applying the archive-marker
  check. Fixes false-positive that broke every consumer PR running pre-commit
  with `--all-files` after openspec/specs/ files existed in main.

### Validated against

- consumer-e (Profile A, public): branch protection + auto-merge applied
  manually 2026-04-30; trace fields added to Project #2 manually 2026-05-01.
  PRs #22 (slice 1) + #23 (CodeRabbit config) shipped through new flow.
- Migration matrix (§8.1) reflects audit results: ai-playbook + 4 consumers
  stay private (Profile B); consumer-e + consumer-c-legacy + consumer-d-skills go
  public (Profile A).

### Migration

Consumers on rc6 → rc7: bump submodule pointer (auto-PR opens via
propagate-bump on this tag). After merge, run:

```bash
python .ai-playbook/scripts/bootstrap_gh_project.py \
    --owner Wizarck --project-number <N> \
    --repo Wizarck/<repo> \
    --profile auto
```

Idempotent — only applies what's missing.

## [0.8.0-rc6] — 2026-04-30 — agents-md-v1 schema accepts pre-release semver suffix

Hot fix surfaced when bumping consumer-e's `inherits_from` pin to
`v0.8.0-rc5`: the schema regex didn't allow the `-rcN` suffix, so the
`schema-validate-agents` pre-commit hook rejected it. This is a real
limitation — pinning to an rc tag during dogfooding (before stable
promotion) is exactly the use case `release-management.md` §8 calls
out for migration.

### Fixed

- `specs/agents-md-v1.schema.json`: `inherits_from` items pattern
  extended to `^github\\.com/[^/]+/[^@]+@v?\\d+\\.\\d+\\.\\d+(-[\\w.]+)?$`.
  Now accepts: `@v1.0.0`, `@1.0.0`, `@v0.8.0-rc1`, `@v1.0.0-beta.3`,
  `@v2.0.0-alpha.1.draft`, etc. (per https://semver.org §9 pre-release).

## [0.8.0-rc5] — 2026-04-30 — UTF-8 subprocess encoding for `gh api graphql`

Hot fix surfaced when re-running `bootstrap_gh_project.py` against a populated project on Windows: the previous run's card bodies (with Spanish accented characters like "ñ", "á", "í") came back from `gh api graphql` as UTF-8 bytes. Python's `subprocess.run(..., text=True)` defaults to the system locale on Windows (`cp1252`), which silently dropped the response body. `result.stdout` was effectively None, breaking `json.loads`.

### Fixed

- `scripts/bootstrap_gh_project.py` — all four `subprocess.run` calls now pass `encoding="utf-8"` explicitly. This is portable (UTF-8 is also the modern default on Linux/macOS) and prevents the silent-drop on Windows.

### Validated against

Re-run on Wizarck/consumer-e#2 with cards already populated: 20 items inspected via `list_items` (response includes accented characters), 0 errors, body-refresh diff computed correctly.

## [0.8.0-rc4] — 2026-04-30 — mcp-validate pre-commit context + GH Project card body template

Two friction fixes surfaced during consumer-e's slice 1 implementation:
(a) `mcp-validate` pre-commit hook failed on missing env vars (live in
SOPS-encrypted dotenv files, not sourced before `git commit`) and on
consumer-d's stale personal layer; (b) GH Project cards rendered the
scope note as a wall of text without back-references to the source
artefacts in the repo (violates DRY — the truth is in `docs/openspec-
slice.md`, the card should *link* to it).

### Updated — mcp-validate (`scripts/mcp/validate.py`)

- **Pre-commit auto-skip env-check**: when invoked with `PRE_COMMIT=1`
  in env (set automatically by pre-commit framework), the env-required
  check downgrades to a soft notice (logs how many env vars would have
  fired). CI / explicit runs still hard-fail. Add `--skip-env-check`
  for offline CI parity.
- **Personal-layer fallback notice**: when the resolver falls back to
  `~/Projects/consumer-d/mcp-servers.yaml` (or Windows equivalent),
  emit a stderr notice so the dev sees the cross-project read happening.
  Set `$AIPLAYBOOK_PERSONAL_MCP_FILE` or create `~/.config/mcp-servers.yaml`
  to override.

### Updated — bootstrap_gh_project (`scripts/bootstrap_gh_project.py`)

- **Card body template** (`_render_item_body` helper) — three sections:
  header (bounded context · deps · FRs/NFRs as one-liner), scope-note
  paragraph from `docs/openspec-slice.md` verbatim, and a References
  block with markdown links to slice plan row, proposal.md, ADRs, data
  model, project structure, HITL gates log. Requires `--repo` for
  absolute URLs; falls back to relative paths when omitted.
- **Idempotent body refresh**: existing items whose body diverges from
  the rendered template get auto-updated via the
  `updateProjectV2DraftIssue` mutation. Per release-management.md §5.4:
  the slicing artefact is the single source of truth — never edit the
  card body manually; re-run bootstrap_gh_project to refresh.
- **`SliceRow` dataclass** extended with `frs: str` (the FRs/NFRs
  column from the table). `parse_slicing` now reads column index 3
  for FRs.
- **Read-only operations in dry-run**: `list_items` (and `list_linked_repos`
  for repo-link) now run in dry-run mode so the diff report is accurate.
  Mutations remain skipped.

### Validated against

- `mcp-validate` no longer fails consumer-e's `pre-commit run --all-files`
  on a fresh shell with no env vars sourced.
- consumer-e's Project #2: 20 cards body-refreshed; one example shows
  bounded-context · deps · FRs header + scope note + 4-link References
  block (slice plan row anchor + proposal + arch/data/structure docs +
  HITL gates log).

## [0.8.0-rc3] — 2026-04-30 — repo linking + visibility for bootstrap_gh_project

Surfaced when consumer-e's GH Project #2 didn't appear in the repo's
Projects tab after the initial bootstrap — Projects v2 always live at
user/org scope and need an explicit link mutation to be visible from
the repo page. v0.8.0-rc1's `bootstrap_gh_project.py` knew how to
create+populate the project but not how to link it; that gap is now
closed.

### Added

- **`scripts/bootstrap_gh_project.py` `--repo <owner/name>` flag** —
  idempotent link of the project to a repo via GraphQL
  `linkProjectV2ToRepository`. Read-only `list_linked_repos` precheck
  skips re-linking if the link already exists.
- **`scripts/bootstrap_gh_project.py` `--visibility {private,public,keep}`
  flag** — sets project visibility on the web. Default is `keep` so
  re-runs don't surprise the operator with an unintended visibility
  change. New projects default to `private`; flip to `public` for
  community / OSS work.
- **`specs/release-management.md` §5.4** new subsection covering the
  user/org-vs-repo scope distinction + visibility independence.

### Validated against

Wizarck/consumer-e#2 (already linked from the manual `gh project link`
that surfaced the gap): dry-run reports "already linked" + skips the
mutation, exit 0 — confirms idempotency.

## [0.8.0-rc2] — 2026-04-30 — bootstrap_gh_project script bug fixes

(see PR #8 for full details — unchanged)

## [0.8.0-rc1] — 2026-04-30 — release management contract

Codifies the source-control + project-board side of the BMAD+OpenSpec hybrid flow. Until now the runbook said "implementation in `slice/<id>` branch" and Gate F said "implementation diff + tests pass" without normatively answering: **is each `tasks.md` checkbox a separate branch + PR, or do all tasks of a change ship in one PR?** The implicit answer (one branch per change, tasks as PR checklist) was correct but undocumented; that gap surfaced in `consumer-e` 2026-04-29 when slicing reached Gate E. v0.8.0-rc1 closes the gap.

This is a **release candidate** — the contract is validated via consumer-e Wave 0 (slices 1-3) before promoting to v0.8.0 stable. Existing consumers on v0.7.x are NOT auto-bumped; they migrate per `release-management.md` §8 when ready.

### Added — Release management contract

- **`specs/release-management.md`** v1.0.0 — defines the universal contract for how OpenSpec changes ship: 1 branch = 1 change = 1 PR (tasks tracked as PR checklist, never per-task branches), Status field schema with five canonical options (`Todo`, `Blocked`, `In Progress`, `Review`, `Done`), recommended `Risk` + `P&L impact` custom fields, CI-green-required-for-Review transition, dependency-driven merge order (Wave N before N+1), bootstrap-via-script (§7), migration path for existing consumers (§8), anti-patterns (§9). Complements `issue-tracking.md` v1.0.0 (which already automates ticket↔proposal sync) on the source-control side.
- **`scripts/bootstrap_gh_project.py`** — one-command setup for a consumer's GH Project board: looks up project, adds canonical Status options idempotently (preserves existing names; flags case-only divergence as a soft warning), adds recommended custom fields (`Risk`, `P&L impact`), and (with `--slicing-file`) creates one draft project item per change row from `docs/openspec-slice.md` with initial Status set per dep graph. Stdlib-only (subprocess + json + urllib not used; just `gh api graphql`). Idempotent.

### Updated — runbook v1.1.0

- **`specs/runbook-bmad-openspec.md` §3.6** — new section, "Branch, PR + merge contract", points at `release-management.md` for the normative source-control contract. One-paragraph summary in the runbook for skim-readers; full detail in the spec.
- **`specs/runbook-bmad-openspec.md` §5** — Gate F row now mentions "CI green on slice branch" as prerequisite (was implicit before).
- **`specs/runbook-bmad-openspec.md` §6** — cross-refs add `release-management.md` + `issue-tracking.md`.

### Validated against

- **consumer-e (Wizarck/consumer-e)** — bootstrap of GH Project #2 successful in dry-run mode (3 status options already aligned, 2 added: `Blocked`, `Review`; both recommended custom fields already present; 20 slice rows parsed; 20 draft items would be created). Real run pending v0.8.0-rc1 merge to playbook main + consumer-e bump.

### Roadmap

- v0.8.0 stable promotion: after consumer-e Wave 0 (slices 1-3) lands, retro confirms the contract works under load. Items 1-10 from `specs/v0.8.0-roadmap.md` are still tracked separately; this RC is **scoped only** to release management.
- Optional follow-ups (not blocking v0.8.0 stable):
  - GH Action template `.github/workflows/project-status.yml` for auto Status transitions (commit-passing-CI → Review; squash-merge → Done; downstream-deps-merged → Blocked-to-Todo). Doc placeholder in spec §6.3; implementation deferred.
  - Optional hard dependency-check workflow `.github/workflows/dep-check.yml` per spec §6.2.

## [0.7.1] — 2026-04-29 — apply-fix contract (Phase 5 bring-forward)

Adds the `apply-fix-contract.md` spec — the canonical contract any workflow MUST honor when mutating prod state via human-in-the-loop approval. Lifts the propose-only ceiling that previously kept all `langgraph-aiops/workflows/*.py` write paths blocked behind `NotImplementedError("APPLY_FIX mode deferred to T29")`. Sibling to `break-glass.md`; different audiences (CLI gate overrides vs workflow mutation contracts).

### Added

- **`specs/apply-fix-contract.md`** v1.0.0 — two-tier permission model (autonomous tier for `watchdogs.py`-class auto-mutators, HITL-gated tier for everything else), envelope shape (`command_preview`, `idempotency_key`, `reversal_hint`, `risk`, `mode`, `max_approval_age_seconds`), exact-match invariant (bytes-of-action MUST equal approved bytes), idempotency contract (workflows requesting `mode="apply"` MUST supply a precheck callable), identity binding rule (env-bound approvers; rejection logged not silently dropped), risk-tier rule (`risk=high` always HITL even on cron), Python helper API (`request_approval`, `verify_apply_safety`, `record_apply_outcome`), structured logging contract (rows to `incidents.jsonl` with `request_id` correlation).

### Stale references retired (in consumers)

- The strings `"T29"` and `"break-glass.md §propose-only ceiling"` no longer appear in any new code authored against v0.7.1+. The `§propose-only ceiling` section never existed in `break-glass.md`; the citation was a forward-reference to a milestone that was never scheduled. Consumers updating to v0.7.1 should also update their own `langgraph-aiops/workflows/hitl.py` and `langgraph-aiops/consumer-d_ops/tools.py` to drop the `NotImplementedError("APPLY_FIX mode deferred to T29")` guards and reference `apply-fix-contract.md` instead. consumer-d lands this companion change in its own commit (Change A Phase 1).

### Notes

- v0.7.1 is **additive** — no existing spec is modified, no contract is broken. v0.7.0 consumers can adopt at their own pace.
- The companion code refactor (replacing the `NotImplementedError` guards in `hitl.py` and `tools.py`) lives in consumer-d, not in this repo. The v0.7.1 bump in consumers via `propagate-playbook-bump.yml` opens the playbook-pin PR; the consumer-d code refactor is a separate consumer-d commit gated by the new pin.
- Phase 5 background: the `apply-fix-contract.md` spec, the consumer-d code refactor, and the upcoming HITL channel adapters (Telegram + WhatsApp via wa-mcp + Hermes), durable notification queue, LiteLLM enforcement, and incident-response/model-migration spec completion are tracked in `consumer-d/docs/openspec-slice-phase5.md` as 4 OpenSpec changes (one of which — `add-hitl-channels-and-apply-fix` — authored this v0.7.1 spec).

## [0.7.0] — 2026-04-28 — alignment + bridges + audit incorporation

Major hardening of the BMAD↔OpenSpec hybrid flow. v0.7.0 closes the seam between Phase 2 (BMAD discovery + design) and Phase 3 (OpenSpec implementation), incorporates two patterns from external skill audits, adds a soft-warn lint for SKILL.md description quality, and records a roadmap of items deferred to v0.8.0. Additive against v0.6.x; existing consumers may migrate at their own pace.

### Added — Phase 2 → Phase 3 bridge

- **`specs/bmad-openspec-bridge.md`** v1.0.0 — defines the canonical slicing artefact (`docs/openspec-slice.md`) that BMAD writes at Gate C and `openspec-propose` reads at the start of Phase 3. Resolves the v0.6.x drift where the Phase 2 → 3 handoff was implicit. Also settles the `docs/` (canonical) vs `_bmad-output/planning-artifacts/` (workflow trail) path-canon split with explicit rules.
- **`templates/openspec-slice.md.template`** — copyable starting point for the slicing artefact. Schema includes change-ID table (with bounded context, FRs, journeys, components, dependencies) plus per-change scope notes (copy-paste-quality prose, no `<TBD>` placeholders).

### Added — Cross-cutting discipline specs (lifted from external audits)

- **`specs/output-completeness.md`** v1.0.0 — anti-skeleton-output rules. Bans `// TODO`, "for brevity", placeholder skeletons, ellipses-as-substitute, and self-narration. Defines the deferral protocol (the only legitimate exit) and the PAUSED check-in pattern. Pattern adopted from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)'s `output-skill`; adapted for the hybrid flow.
- **`specs/verification-before-completion.md`** v1.0.0 — iron law: no claim of completion without fresh verification output in the same message. Defines what "fresh verification" means (after the work, observable output, specific to the claim) and the synthesis-claim exception for non-code artefacts. Pattern adopted from [obra/superpowers](https://github.com/obra/superpowers) (MIT, © Jesse Vincent); adapted for the hybrid flow.

### Added — Verdict vocabulary

- **`verdict-contract.md` v1.1.0** — adds 4th canonical verdict literal **`⛔ ARCHITECTURE QUESTIONED`** for the case where repeated rework reveals a structural design issue rather than an implementation gap. Distinct from `❓ CLARIFICATION NEEDED` (spec ambiguity) — `⛔` is when the spec is clear but the design that satisfies it isn't viable. Triggers `blocked-by-architecture` lifecycle state and an architect-level review (human or `bmad-agent-architect`). Punctuation note added: `⚠️ ISSUES FOUND (iter N)` uses a SPACE (not underscore) — caught during the v0.7.0 audit.

### Added — SKILL.md schema + lint

- **`skills-distribution.md` §1** — required SKILL.md sections updated. `## Anti-patterns` and `## Verification` sections are now part of the canonical schema for skills authored or revised under v0.7.0+. Existing skills migrate opportunistically (no flag day); new skills MUST conform. Description-field rule (CSO — "command-style operations") added: descriptions tell the LLM **when** to invoke the skill, not what it does internally.
- **`scripts/check_skill_descriptions.py`** — soft-warn lint that flags descriptions matching summary-verb / workflow-mechanics patterns or missing when-to-use indicators. Default mode is warning-only (exit 0 even with findings); `--strict` exits non-zero for CI use. 14 tests in `tests/test_check_skill_descriptions.py`.

### Updated — runbook

- **`runbook-bmad-openspec.md` §2.4** — slicing now produces the canonical artefact at `docs/openspec-slice.md`; path-canon split made explicit.
- **`runbook-bmad-openspec.md` §3.1** — `/opsx:propose` reads the slicing artefact and supports `--batch` mode for many-change modules. Workers in `/opsx:apply` cite `verification-before-completion.md` for verdict emission and `output-completeness.md` for deliverable shape. `openspec archive` chains a retro write to `retros/<change-id>.md` automatically.

### Roadmap

- **`specs/v0.8.0-roadmap.md`** v0.1.0 — records design objectives + work items deferred from v0.7.0 to v0.8.0. Highlights:
  - **KISS single-versioning** (Master, 2026-04-28): collapse `ai-playbook` + `consumer-d-skills` semver streams to one. Reduces AGENTS.md drift and per-consumer pin inconsistency.
  - Complete the `bmad-create-ux-design` v1→v2 migration (workflow.md was rewritten in v0.6.0; the steps/ files underneath still produce the v1 monolithic doc).
  - Vendor / lift `systematic-debugging` from `obra/superpowers` for the `/opsx:apply` worker debug path; wire the "3 failed fixes" rule to emit `⛔ ARCHITECTURE QUESTIONED`.
  - Two-stage review split (spec-compliance vs code-quality) per the superpowers audit.
  - Apply CSO description rewrites to existing skills (audit doc + batch rewrite, post-v0.7.0 propagation).
  - Implement CI hardening of `check_output_completeness.py` and `check_verification.py`.

### Notes

- v0.7.0 is **additive**. Existing consumers' v0.6.x docs and skill folders are valid; the new rules apply going forward.
- Skill fixes (5 surgical edits to bmad-create-prd, bmad-create-architecture, bmad-code-review, openspec-propose, openspec-archive-change) align them with the new specs. None breaks backwards compatibility — they add the right next-step pointers and verdict literals where they were missing or wrong.
- Consumer propagation via the existing zero-touch loop will open auto-bump PRs across the 5 consumers (consumer-c-legacy, consumer-b, consumer-d, consumer-e, livekit) once this lands on `main`.

## [0.6.1] — 2026-04-27 — declarative tracker_kind + notify drift fix

Hardening pass on the consumers-routing layer that surfaced during the v0.6.0 PR. Two unrelated fixes bundled because both touch the same automation surface and shipping them together is cheaper than two propagation rounds.

### Fixed

- **`scripts/propagate_bump.py`** — was importing `emit` from `scripts/notify.py`, which exports `notify`. The mismatch logged `notify failed: cannot import name 'emit'` warnings during propagation but did not block PRs. Aligned the import + call site. Notifications now reach the JSONL queue + SMTP again.
- **`scripts/issue_sync.py`** — replaced the implicit "private repo → Jira fallback" heuristic with a **declarative `tracker_kind` field** read from `consumers.yaml`. The previous flow had two latent failure modes: (a) any consumer name not in `consumer-b_PROJECTS` fell silently to `consumer-a`, regardless of whether a Jira project should exist for it; (b) `gh` CLI unavailability triggered the Jira branch even for GH-only consumers. Both are gone. `decide_surface` now raises `RuntimeError` for any active consumer without a valid `tracker_kind` instead of silently picking a default. The class of drift the v0.6.0 PR caught (tests asserted `consumer-b`, code returned `consumer-a`) cannot recur.
- **`scripts/release_cut.py`** — the Jira-fixVersion path now reads the project key via the new `issue_sync.jira_project_for(consumer_root)` public helper (registry-driven). The private `_jira_project_for(name)` heuristic was removed.

### Added

- **`tracker_kind` field** in `consumers.yaml` schema (`github | jira`, required for active consumers). When `jira`, `jira_project` is also required.
- **`tests/test_consumers_yaml.py`** — schema validation that runs on every CI build. Asserts every active consumer declares `tracker_kind`, every `jira` consumer has `jira_project`, and the status / repo / default_branch fields are present. The committed registry is the test target — drift between code and registry fails CI, not after-the-fact.
- **`AIPLAYBOOK_CONSUMERS_YAML`** environment override for tests / vendored consumers.
- **`issue_sync.jira_project_for(consumer_root)`** public helper for callers that need the Jira project key directly.

### Removed

- `scripts/issue_sync.py` private constants `consumer-b_PROJECTS`, `consumer-a_PROJECTS`, and `_jira_project_for(consumer_name)` function — replaced by the registry lookup.
- `tests/test_issue_sync.py::test_jira_project_for_names` (function deleted).
- `tests/test_issue_sync.py::test_decide_surface_private_falls_back_to_jira` (asserts behaviour that should not exist — there is no silent fallback to Jira).

### Notes

- All 5 active consumers default to `tracker_kind: github` in this release. The registry comment documents how to flip a consumer to Jira (set `tracker_kind: jira` + `jira_project: <KEY>`).
- The propagation loop will open auto-bump PRs across the 5 consumers; the runtime behaviour is identical for all of them (everyone was already on GH path before, so this is a structural cleanup with no behaviour change for current consumers — just defence against future drift).

## [0.6.0] — 2026-04-27 — UX Track v2: three-step order, palette decoupling, OKLCH-canonical, components catalogue

Substantial expansion of the UX Track from v0.5.0's framing into operational rules, based on consumer learnings (consumer-c-legacy Module 2 UX track). Additive against v0.5.0; existing consumers may migrate at their own pace.

### Added

- **`specs/ux-track.md` v2.0.0** — rewritten and expanded. New sections:
  - §3 **Three-step order** (mandatory): inspiration → palette validation → variant generation. Visual artefact at every step; text descriptions never substitute.
  - §5 **Variant generation pattern** — one agent per creative engine in parallel; the 5-engine starter set codified (impeccable, taste-skill, huashu-design, ui-ux-pro-max-skill, awesome-design-md).
  - §6 **Self-documenting deliverables** — banner + HTML head-comment audit format with internal-only citations (`DESIGN.md §N`, never external repo paths).
  - §7 **Index/compare page** mandatory.
  - §8 **Iteration loop** — palette decoupling as a separate visual step; bones+layer remix naming (`mock-X<N>-<descriptor>.html`).
  - §9 **Phase A scrub + Phase B consolidation** — mechanical recipe for archiving rejected variants and consolidating to canonical DESIGN.md.
  - §10 **OKLCH-canonical colour rule** — declare colours in `oklch(L% C H)`; hex as derivation comment only. Why: perceptual uniformity, wide-gamut display fidelity.
  - §11 **Per-journey docs format** — frontmatter + 8-section structure (Goal / Trigger / Walkthrough / Components used / Capabilities satisfied / Edge cases / Decisions / Notes for implementation).
  - §12 **Components catalogue Storybook-style** — written *after* journey mocks; per-component entries with TS data shape, states, tokens, edge cases, planned stories; explicit stewardship clause.
  - §13 **Anti-patterns checklist** baked into the audit (~25 items).
  - §14 **WCAG-AA verification ritual** — every new text pair recorded with ratio in the audit.
  - §15 **Anti-pattern: hand-coded mocks pretending to be design** — they are baseline only.
- **`templates/ux/`** — 6 copyable templates: `inspiration.md.template`, `palette-options.html.template`, `variants-index.html.template`, `DESIGN.md.template`, `journey.md.template`, `components.md.template`. Consumers copy on first use.
- **`specs/runbook-bmad-openspec.md` §2.3** — expanded UX Track summary inline (the three steps + Phase A/B + OKLCH discipline) so the runbook is self-explanatory without requiring a jump to ux-track.md for the high-level shape.
- **`skills/bmad-create-ux-design/workflow.md`** — rewritten to invoke the three-step order explicitly, point at the templates, and require: parallel agent fan-out at step 3, OKLCH declarations, internal-only citations, WCAG-AA verification block in the audit.

### Changed

- **Gate B verification checklist** in `runbook-bmad-openspec.md` §2 expanded to include: DESIGN.md ↔ ADR data-shape consistency, every PRD journey has a mock or design-intent doc, components catalogue matches journey usage, no engine references leaked into canonical artefacts after scrub.

### Removed

- **`specs/ux-track.md` §6.1 License compliance** (from v1.0.0). Was scaffolding; replaced with a one-line "consumers must check each engine's licence against their own project's licensing constraints" in the curated-engines table. Engines are referenced, never vendored — licensing remains the consumer's responsibility for their own use case.

### Notes

- v0.6.0 is **additive**. Existing consumers' UX docs from v0.5.0 are valid; the new rules apply going forward. Migration is opt-in; no consumer is forced to retrofit.
- Star counts and license fields for the 5 engines verified via `gh api repos/{owner}/{repo}` on 2026-04-27. Refresh annually.
- Consumer propagation via the existing zero-touch playbook propagation loop will open auto-bump PRs across the 5 consumers (consumer-c-legacy, consumer-b, consumer-d, consumer-d-rag, consumer-d-skills) once this lands on `main`.

## [0.5.2] — 2026-04-27 — docs-deploy: gate the deploy job behind PAGES_ENABLED

### Fixed

- `.github/workflows/docs-deploy.yml` — deploy job now `if: ${{ vars.PAGES_ENABLED == 'true' }}`. After v0.5.1 unblocked the build phase (drop `--strict`), the deploy step still fails on private repos that don't have GitHub Pages enabled (free-tier limitation: Pages on private repos requires GitHub Pro/Team/Enterprise). The conditional skips the deploy job by default; consumers enable it by setting the `PAGES_ENABLED` repo variable to `true` once Pages is available.
- For ai-playbook itself (currently private + free tier): build verifies site assembles, deploy skipped. To re-enable: make repo public OR upgrade plan, then set `PAGES_ENABLED=true` in repo Settings → Variables.

## [0.5.1] — 2026-04-27 — release-cut + docs-deploy resilience

### Fixed

- `scripts/issue_sync.py::_load_jira_creds` — reject malformed `ATLASSIAN_URL`
  values (missing `http://` / `https://` scheme) at creds load time. Previously
  a bad URL like `mycompany.atlassian.net` would slip through and crash
  `release_cut.py` deep in `urllib.request.Request` with `ValueError: unknown
  url type`. Now `_load_jira_creds` returns `None` for malformed URLs and the
  caller's existing graceful "credentials missing" path triggers cleanly.
- `.github/workflows/docs-deploy.yml` — drop the `--strict` flag from
  `mkdocs build`. The nav references files outside `docs_dir` (under
  `../specs/*` and `../templates/*`) which mkdocs warns about then aborts on
  under strict. The cross-tree references are intentional (specs dogfood the
  docs site); the warnings are expected. Builds now publish with warnings
  rather than not at all. Future enhancement: adopt `mkdocs-monorepo-plugin`
  or move specs/ under docs/ to silence the warnings.

### Notes

- For private repos with `ATLASSIAN_URL` secret set, the URL value MUST
  include the `https://` scheme. Verify in repo Settings → Secrets and
  variables → Actions before next release.
- Both fixes are pre-existing-bug repairs surfaced during the v0.5.0 cut;
  they do not change any spec or workflow contract.

## [0.5.0] — 2026-04-27 — UX Track formalised between Gate A and Gate C

Adds a normative UX design phase to the BMAD+OpenSpec workflow. Previously the
runbook was silent on UX; mocks lived ad-hoc inside individual `design.md` per
OpenSpec change, producing two recurring failures: no coherent UX vision across
changes, and component sprawl during `/opsx:apply`.

### Added

- `specs/ux-track.md` (v1.0.0) — full spec for the UX Track: position in
  workflow, artefacts (`docs/ux/DESIGN.md` 9-section format + per-journey
  files + components.md), Storybook-first component-library curation pattern,
  design-review trigger for non-trivial components, QA discipline mirroring
  [parallel-review.md](specs/parallel-review.md), and curated external-skill
  recommendations.
- Curated third-party skill recommendations (not vendored — distribution per
  RFC-0001): pbakaus/impeccable + Leonxlnx/taste-skill (drop-in),
  nextlevelbuilder/ui-ux-pro-max-skill (adapt), VoltAgent/awesome-design-md
  (inspire-from / format pattern), modstart-lib/skillui (skip).

### Changed

- `specs/runbook-bmad-openspec.md` — phase map updated to show UX Track in
  parallel with Architecture; new §2.3 cross-references [ux-track.md](specs/ux-track.md);
  Gate B now waits on both Architecture and UX (HITL summary updated). Headless
  / API-only consumers declare `no-ui-consumer` in `docs/ux/README.md` and skip
  the UX gate.

### Compatibility

- **Backward-compatible** for consumers shipping a UI: their existing UX work
  (if any) needs to be expressed in the new `docs/ux/` layout. Per
  [contributing.md](docs/contributing.md) §6, deviations from the recommended
  DESIGN.md format land in the consumer's `AGENTS.md` §7.
- **No-op** for headless / API-only consumers via the one-line escape hatch.

### Validating use-case

consumer-c-legacy Module 2 (Recipes/Escandallo) PRD discovery (2026-04-26 — 2026-04-27)
surfaced the UX gap in real time. Five external skill repos analysed; star
counts + licenses verified via `gh api repos/{owner}/{repo}` on 2026-04-27.

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
