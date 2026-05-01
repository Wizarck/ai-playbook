# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

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
