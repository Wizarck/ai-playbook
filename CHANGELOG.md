# Changelog

All notable changes to `ai-playbook` are documented here. Semver.

## [0.21.0] — 2026-08-01 — feat: rules-gate (one always-on, requireable CI gate)

### Changed
- **Five paths-filtered rule workflows consolidated into one always-on job.**
  `check-link-integrity`, `check-doc-language`, `check-agents-md-size`,
  `validate-pairing` and `check-rule-schemas` each carried its own `paths:`
  filter, which made every one of them **unrequireable**: a required status
  check whose workflow is paths-filtered never reports on a PR that misses the
  filter, and GitHub then blocks that PR forever waiting for a check that will
  not arrive. The consequence was that the branch ruleset could require none of
  them, and pytest was the only enforced gate.

  `rules-gate.rule.yml` runs all eight checks on every PR as steps of a single
  job. One job rather than five plus an aggregator: the job name IS the stable
  required context, so there is no aggregation logic to get wrong and no second
  place where a renamed job silently drops out of the gate. Every step carries
  `if: ${{ !cancelled() }}`, so one failure still reports the rest — a gate that
  stops at the first error costs a full round trip per finding.

  Verified check-for-check: 8 commands in the five old workflows, 8 in the new
  gate, none lost.

  Cost: ~40s on one hosted runner per PR, against 15–21s each for the five it
  replaces. On a PR touching docs and rules it is roughly a wash.
- `rule-use-cases-matrix` L3 column now reads `rules-gate (shared)` for the 38
  rules that rode the old shared workflow.

### Notes
- The branch ruleset gains `rules-gate` as a required status check alongside
  `pytest (3.11)` and `pytest (3.12)`. That is the point of the change: five
  quality gates that existed but could never be enforced now can be.

## [0.20.1] — 2026-08-01 — feat: stacked-pr-guard (pre-merge dependent check)

### Added
- **Rule `stacked-pr-guard`** — enforced, with paired hardrule. A PR whose head
  branch is the base of another open PR has dependents; merging it orphans
  them. GitHub closes a PR whose base branch is deleted, and that close is
  **terminal**: `gh pr reopen` answers *"Could not open the pull request"* and
  `gh pr edit --base` answers *"Cannot change the base branch of a closed pull
  request"*. The commits survive on the head branch; the PR does not, and must
  be replaced — losing its review thread, CI history, and approvals.

  Born from this repo: #145 was stacked on #144, #144 merged with
  `--delete-branch`, #145 closed with no path back, and the work had to be
  reopened as #146.

  `validate --pr <n>` exits 0 (no dependents), 1 (dependents found — the error
  names each one and the exact `gh pr edit … --base <base>` command to retarget
  it), or **2** when it could not determine the answer. That third code is the
  point: a guard that reports "all clear" because `gh` was missing or
  unauthenticated is worse than no guard. 11 tests. Break-glass
  `AIPLAYBOOK_STACKED_PR_GUARD_SKIP`.

  On-demand rather than hook-fired — there is no pre-merge git hook to attach
  to, which is the same shape `auto-merge-discipline` already uses.

## [0.20.0] — 2026-08-01 — feat: code-entropy taxonomy + sweep contracts (F0, spec-only)

Phase 0 of the code-entropy work: taxonomy and contracts, no detector yet. Ships
the vocabulary every later phase references, in the cheap artefact where getting
it wrong costs an edit rather than a rewrite.

### Added
- **Concept `code-entropy`** — the curative half of code discipline, alongside
  ponytail's preventive half. Defines five axes (`orphan-file`, `dead-symbol`,
  `unused-dependency`, `unwired-capability`, `disk-residue`) and three design
  positions that shape everything downstream:
  - **Decidability picks the enforcement mode.** Three axes are facts a machine
    settles alone and belong in rules with paired hardrules; two need judgement
    and belong in a skill. Only two of five axes need a model at all, so most of
    the system runs continuously at zero marginal cost.
  - **Preventive and curative are one loop, closed by a ratchet.** A sweep that
    emits only a report is a campaign and recurs; one that emits a ratchet
    cannot be undone by inattention. Per finding, the follow-up question is
    whether it can become a preventive assertion.
  - **Never auto-delete.** The ledger is the deliverable; execution is separate.
    Justified by this repo's own v0.19.29 incident, where a tier 1 entry whose
    safety shared a bug with its action destroyed 623 lines across 7 files.
  - Axis 5 is classified by **regeneration cost × value**, not size — a cheap-to-
    rebuild artefact that provides value is reported *stale*, never *deletable*.
    A stale map is worse than no map, because it is consulted with confidence.
- **`specs/wiring-assertions.schema.yaml`** — the assertion contract for
  `unwired-capability`. Registries are project-specific but the assertion is not:
  every case is *every artefact matching X is referenced in Z by pattern Y*. The
  playbook ships the engine, the consumer ships its own `wiring.yaml`.
  Interpolation tokens: `{dir}` `{stem}` `{name}` `{symbol}` `{path}` `{capture}`.
- **`specs/wiring-assertions.example.yaml`** — six assertions measured against a
  real consumer tree rather than illustrated. Every `by` regex round-trips out
  of the YAML, compiles, and matches a quoted real line.
  - **The precedent is regression-proven.** `celery-task-routed` run against the
    commit that introduced the missing-route bug produces the finding; against
    its fix and against HEAD it matches the route. The load-bearing detail is a
    negative lookbehind on `"task": ` requiring the task name in *entry*
    position — a bare-name regex passes on the buggy commit, because that slice
    did add the `beat_schedule` entry and only the route was missing. Precision
    in the pattern is the whole assertion.
  - **One assertion ships `advisory`, not enforced**, because it has two live
    findings in the consumer today (two channel modules with no label entry).
    The page degrades to the raw identifier rather than breaking, so the grade
    is S3; it flips to enforced in the PR that adds the labels.
  - **One requested assertion was not encodable and was not faked.** "A sync
    task has no registry entry" is not statically decidable there: only 8 of 26
    task functions are user-facing entry points and no static marker separates
    them, so the assertion would run ~69% false-positive and be silenced by its
    own allow list. Substituted by the decidable half of the same bug — every
    `*_entries.py` must be imported, since registration is an import-time side
    effect — with the runtime check that already covers the other direction
    named in the file.
- **`schemas/schema-sweep-manifest-v1.json`** — the findings ledger. Tier,
  action and safety enums are exactly the `cleanup-zombies` executor's, and the
  tier×action and tier×safety matrices are reproduced as conditional blocks, so
  a ledger row projects onto an executor entry with one field lift
  (`adjudication.tier` → `tier`) and no translation. The authoritative tier sits
  under `adjudication` on purpose: authority travels with its attribution rather
  than existing twice.
  Enforced structurally: evidence is mandatory (a finding without it, or with
  zero locations, is schema-invalid), and adjudication cannot erase a finding —
  there is no `delete` decision, the weakest outcome is `dismiss`, which keeps
  the row, is pinned to Tier 3 and demands a rationale. An LLM may not escalate
  into Tier 1; delete authority is reserved for `human`. For `disk-residue`,
  regeneration cost and value are separate dimensions, so `expensive` or
  `irreproducible` can never be `DELETABLE` and a cheap-but-valuable artefact
  lands on `STALE` with a rebuild command.
- **`enforcement-status` row** for `code-entropy` at 📋 spec-only, with the
  per-axis landing targets and the triggers that flip it 🟡 and ✅.

## [0.19.29] — 2026-08-01 — fix: cleanup-zombies stops eating docs that document it

### Fixed
- **`auto-managed-orphan-blocks` demoted Tier 1 → Tier 3** (report-only). Three
  subsystems materialise auto-managed blocks — `auto_managed.py` for `specs/*`,
  plus the caveman and ponytail toggles for their own prefixes — so "this block
  has no owner" is a judgement across three state files, not a safe basis for
  auto-deletion. Detected in geeplo, where the entry destroyed **623 lines
  across 7 files** of the playbook's own tree, truncating several mid-sentence
  and removing a `verdict-contract` FOOTER (an instructional-defense control).
- **Safety `auto_managed_orphan` now delegates to `auto_managed.find_sections`**
  instead of re-implementing the parser. The hand-rolled version matched BEGIN
  markers with `re.search` (so prose *documenting* the syntax parsed as a live
  block), never reset its skip state when no END followed (so it deleted from
  the false BEGIN to end of file), and resolved `<source>` against the consumer
  root (so every live `caveman/*` and `ponytail/*` block read as an orphan).
  The canonical parser anchors on full trimmed lines, skips fenced code blocks,
  and raises on nested/unterminated markers — "cannot parse" now means "report
  nothing", never "delete the rest of the file".
- **Orphan classification is namespace-aware.** `specs/*` resolves through
  `compute_expected`; `caveman/*` and `ponytail/*` through their toggle state
  files; an unrecognised namespace is never an orphan.
- **`**/*.md` no longer walks the playbook submodule.** A glob from the consumer
  root reached into `.ai-playbook/`, i.e. this repo's own documentation. All
  observed damage was confined there.
- **Tier 3's no-mutation guarantee is now structural.** `_process_entry` returns
  before the action dispatch for every Tier 3 entry regardless of safety outcome
  or `--apply`. Previously the documented guarantee held only by accident,
  because `report_only` always failed its safety and short-circuited earlier; a
  Tier 3 entry with a passing safety would have mutated.

### Changed
- **Tier and safety decoupled in `TIER_SAFETY_MATRIX`.** Tier governs mutation,
  safety governs detection. The 1:1 coupling forced any entry wanting real
  detection to also claim auto-delete rights — the root cause of the incident
  above. Tier 3 may now carry `auto_managed_orphan` so its advisory names
  specific findings.
- `manifest_version` → `2026-08-01.1`.

## [0.19.28] — 2026-07-13 — feat: anti-drift gates (lint-parity-precommit + migrate-seed-smoke)

### Added
- **Rule `lint-parity-precommit`** (#143) — enforced, with `apply`. Linters that
  gate CI must also run at pre-commit with the same pin (v1 scope: ruff).
  `apply` appends the ruff-pre-commit block using the CI-detected pin
  (append-only; refuses to invent a rev; warns on pin drift). Born from the
  2026-07-13 geeplo incident: a wave merged with 41 ruff errors nobody saw
  locally because pre-commit never ran ruff.
- **Rule `migrate-seed-smoke`** (#143) — enforced, validate-only. Repos with an
  alembic tree AND a DB seed script must exercise the migrate→seed contract in
  CI: fresh database → `alembic upgrade head` → seed twice (idempotency).
  Drop-in job at `templates/ci/migrate-seed-smoke.yml`. Kills the class where a
  NOT NULL migration outruns the e2e seeder and explodes days later in an
  unrelated PR's e2e job (geeplo 0070/0072 vs bootstrap-test-db.py).
- **Concept `anti-drift-gates`** (#143) — the four-layer defense-in-depth model
  (laptop / PR CI / merge lock / continuous), the breakage-class→layer map, and
  ratchet-only-down guidance (baselines block growth AND demand lowering when
  the count drops).

## [0.19.27] — 2026-06-28 — feat: ponytail dashboard panel + caveman/ponytail default to ultra

### Added
- **Ponytail discipline dashboard panel** (#139) — the code-minimalism twin of the
  Caveman panel. Counts real `ponytail:` markers in the consumer tree (stock) plus
  markers added within the dashboard window via git (flow). Honest by construction:
  no LLM self-report, no fabricated dollar figure. `ponytail_state` + `panels.ponytail`
  are additive on `dashboard-data/v1` (optional; renderer guards absence — no version
  bump). New `scripts/ponytail/stats.py`.

### Changed
- **Caveman + Ponytail now default to `ultra` intensity** (#140) — both already shipped
  default-ON with all components at bootstrap; the only dial not at maximum was the
  intensity mode, flipped `full → ultra` everywhere a mode is defaulted (bootstrap
  bundle, toggle defaults, `caveman on --mode` default, apply_config fallback, config-UI
  `default_mode`, dashboard display fallback, runbooks + ponytail SKILL). Explicit
  settings still win; `caveman compress` keeps its own `full` default.
- **Config UI Mode control** (#139) — only rendered for features that declare modes.
  Modeless features (e.g. Graphify) no longer show an empty Mode dropdown or export a
  schema-invalid `mode` into the bundle.

### Fixed
- **Dashboard cost-methodology link** (#139) — corrected to a valid relative path and
  added the `#cost-methodology` anchor in `caveman-mode.md`.
- **Rules inventory** (#139) — regenerated to include `confirm-before-termination`
  (#137 shipped the rule without refreshing the inventory, leaving `check-rule-schemas`
  red on `main`).

### Notes
- Internal/additive: no consumer-facing surface removed or renamed (no zombie-manifest
  entry). Verified end-to-end — dashboard sidecar generated against a real git consumer
  with ponytail ON surfaces `markers` + `markers_window`; full suite green on 3.11/3.12.

## [0.19.26] — 2026-06-21 — feat: confirm-before-termination rule + doctor uv-aware docs

### Added
- **`confirm-before-termination` rule** (#137) — L2 doc + L1 PreToolUse hook (soft +
  hard variants) that vetoes Bash commands which would terminate the agent/session
  without an explicit confirmation.

### Changed
- **`doctor --install-deps` docstrings** (#136) — note the `uv` fast-path used when
  installing `pyyaml`/`jsonschema` in uv-managed (pip-less) venvs.

### Notes
- Backfilled: this section was omitted when v0.19.26 was tagged; recorded here for a
  coherent changelog.

## [0.19.25] — 2026-06-20 — fix: dependency self-heal + file-path invocation

### Fixed
- **Chicken-and-egg dependency guard** — guarded modules (`rules_toggle`,
  `apply_config`, `schema_validate`, the caveman/ponytail/graphify toggles) used
  to `raise SystemExit(2)` at import time when `jsonschema`/`pyyaml` were absent,
  *before* any self-heal could run. They now call the new
  `scripts/_ensure_deps.ensure_runtime_deps()`, which installs the missing deps
  into the running interpreter (`uv pip install` → `pip` → `ensurepip`) and
  continues. Fixes the common "uv venv lacks jsonschema" wall on install/update
  in any consumer, including pip-less uv venvs.
- **File-path invocation of rule scripts** — running any
  `python .ai-playbook/scripts/rules/<name>.rule.py …` from a consumer root failed
  with `ModuleNotFoundError: No module named 'scripts'` unless the package was
  editable-installed. All 41 rule entrypoints now put the playbook root on
  `sys.path` in their `__main__`, so the documented file-path form works without
  `PYTHONPATH` or `cd .ai-playbook && python -m …`. (Also clears 31 pre-existing
  test failures that only passed when the package happened to be installed.)
- **`doctor --install-deps`** is now uv-aware: it installs `pyyaml`+`jsonschema`
  via `uv` when available (handling pip-less uv venvs) before falling back to the
  editable `pip install -e` + `ensurepip` path.

### Added
- `scripts/_ensure_deps.py` — stdlib-only, zero-cost-to-import self-heal helper
  (`ensure_runtime_deps(*import_names)`), with tests in `tests/test_ensure_deps.py`.

### Notes
- Internal-only fix: no consumer-facing surface removed/renamed (no zombie-manifest
  entry). Smoke-tested per §7 against a real consumer (file-path invocation, exit 0)
  and a fresh pip-less uv venv (self-heal installed both deps, exit 0).

## [0.19.24] — 2026-06-19 — feat: opt-in weekly telemetry issue (UI-configurable)

### Added
- **`telemetry_weekly_issue` global flag** (#132) — config UI → Global flags tab,
  **default OFF**. Opt in to the weekly rule-event digest posted as a GitHub issue.
  When ON, `apply_config` **seeds** `.github/workflows/rule-event-report-weekly.yml`
  into the consumer (seed-only — never clobbers a consumer edit; delete the file to
  turn it off or re-seed) and `bootstrap` creates the `telemetry-report` label
  (best-effort `gh`; prints the manual command if `gh` is unavailable, and reports
  what it did). New workflow template under `templates/new-project/`. A scheduled
  workflow can't read the gitignored bundle, so the file's presence is the toggle.

### Fixed
- **Weekly telemetry workflow no longer posts empty digests** (#131) — the run now
  parses the event count and skips the issue when the window has 0 events. Removes
  the noise (and the unlabelled-issue accumulation) on any repo without committed
  telemetry. The `telemetry-report` label is now created at install rather than by
  the workflow's create-fallback.

### Docs
- `telemetry-design.md` "Weekly digest issue (opt-in)" + README telemetry section +
  `run-telemetry-report` runbook automation section (#132, #133).

## [0.19.23] — 2026-06-19 — fix: reconcile-door footguns + L-tier model flip + 0.19.x doc sync

### Fixed
- **`apply_mcp_render` gated on MCP intent** (#129) — toggling a non-MCP feature
  through the reconcile door no longer re-renders the consumer's entire MCP
  surface (`.mcp.json` + `.gemini/settings.json` + the global gemini config). A
  bundle with no `mcps_enforce` / `mcp_project_servers` section now reports the
  render slot as a skipped no-op, in both the real and dry-run paths.
- **Dispatcher PreToolUse hook hardened** (#129) — the generic L1
  `hook_dispatcher.py` hook is now anchored to `$CLAUDE_PROJECT_DIR` (was a bare
  relative path that resolved against the hook's cwd — possibly a sibling repo)
  and is suppressed when the consumer's submodule pin lacks `hook_dispatcher.py`
  (an absent script would `exit 2` and block every Edit/Write/Bash, gating its
  own repair). Template updated to the anchored command.

### Changed
- **litellm L-tier base flips Haiku → Gemini Flash Lite** (#128) — `triage` /
  `safety_judge` / `conversational_agent` now default to
  `gemini/gemini-2.5-flash-lite` (free quota); Haiku drops to a fallback so it
  stays reachable on Gemini quota/errors. Consumers call by task-class, so no
  consumer change is required.

### Docs
- 0.19.x doc-drift sync (#130): corrected the README Dashboard tab (shipped
  v0.19.6 — was marked "not shipped yet"); added a Graphify section to the README
  + the AGENTS.md dispatcher index; added 0.19.x feature docs that were orphaned
  from the mkdocs nav + a new Operations section.
- Retired the `baseline` branch (commit preserved by tag `v0.1.0`); the rollback
  pointer is now `git checkout v0.1.0`.

## [0.19.22] — 2026-06-18 — feat: MCP absorb — migrate a pre-existing inline .mcp.json into the layers

Slice B (final) of the `lossless-adoption` change.

### Added
- `scripts/mcp/absorb.py` + `render.py --absorb`: a repo adopting the playbook with
  a hand-authored inline `.mcp.json` can migrate its servers into the source layers
  (otherwise they vanish on the next render). **Safe-default contract:** tenant
  instances (`<base-server-type>-<tenant-slug>`, e.g. `google-workspace-arturo`) are
  auto-written to the LOCAL personal layer (`~/.config/mcp-servers.yaml`); every
  other server is **reported, never auto-written**, so a misclassification can never
  leak a personal server into the committed `mcp-servers.project.yaml`. Only env-var
  NAMES are carried (no secret values); the personal layer is backed up + de-duped
  (never clobbers a curated entry); the `.mcp.json` is captured as a BASE snapshot;
  `--dry-run` previews. Opt-in (`--absorb`), idempotent.

## [0.19.21] — 2026-06-18 — feat: lossless adoption — pre-existing files preserved as BASE snapshots

Slice C of the `lossless-adoption` change.

### Added
- `bootstrap.copy_templates` (first-run onboarding only — `--update` already skips
  it) now captures any pre-existing consumer file it is about to overwrite
  (`CLAUDE.md`, a hand-authored `AGENTS.md`, `GEMINI.md`, configs, …) as a **BASE
  snapshot** via `backup_base` before writing the template. BASE is the
  never-overwritten pre-playbook anchor (`restore_base` recovers it); capture is
  idempotent. Adoption no longer silently discards prior content.
- `_report_adoption_backups` prints which files were preserved and points dispatcher
  files at `python -m scripts.curate --dry-run` (then `--yes`) to re-absorb their
  prose into `AGENTS.md` §1/§4/§8 (the renderer is template-authoritative, so prose
  is re-injected through `curate`/`project_meta`, not preserved in place).

## [0.19.20] — 2026-06-18 — fix: AGENTS.md inherits_from list-form pin no longer blanked

Slice A of the `lossless-adoption` change.

### Fixed
- `_extract_agents_md_frontmatter` now parses `inherits_from` as a YAML list (the
  template's own shape) as well as an inline scalar, so `compute_substitutions`
  recovers `PLAYBOOK_PIN` instead of blanking it on re-render. A multi-item list
  prefers the `@`-bearing pin; a present-but-pinless `inherits_from` resolves to an
  empty pin and emits one advisory stderr `warning:` so a future frontmatter-shape
  regression is loud, not silent. Fixes `bootstrap --update` re-rendering a
  template-shaped consumer's `inherits_from` without its pin.

## [0.19.19] — 2026-06-18 — docs: idempotent MCP-untrack migration command

### Fixed
- `upgrade-playbook-pin.md` migration snippet: `git rm --cached` now uses
  `--ignore-unmatch` so it no longer errors when a consumer never tracked
  `.mcp.json`/`.gemini/settings.json`; tagged the fenced block `bash` (MD040).
  (CodeRabbit on #123.)

## [0.19.18] — 2026-06-18 — MCP rendered configs are local (gitignored) build artifacts

Phase 1 of the agnostic-playbook plan: the playbook must never let a user's
personal/tenant MCP servers land in a committed work artifact.

### Changed
- `.gitignore.tmpl` (playbook-patterns block) now ignores `.mcp.json` and
  `.gemini/settings.json` — they are LOCAL build artifacts of the
  personal>project>base render, regenerated per machine via
  `scripts/mcp/render.py`. The committed source of truth stays
  `mcp-servers.project.yaml` (no personal) + `~/.config/mcp-servers.yaml`
  (personal, local-only, never committed). Fixes personal/tenant servers being
  baked into committed `.mcp.json`/`.gemini/settings.json` in consumer repos.
- `AGENTS.md.tmpl` §6 + the upgrade-playbook-pin runbook document the
  local-render model, the one-time `git rm --cached` migration for repos that
  committed these files before, and the fresh-clone render step.
- Genericised the one personal-flavoured example in `mcp-servers-schema.md`
  (`google-workspace-arturo` → `google-workspace-<you>`).

### Added
- Regression test: the shipped `.gitignore.tmpl` ignores both rendered MCP
  outputs.

### Deferred (later phases)
- Lossless adoption (backup + absorb existing config into the layers; also fixes
  the markerless-AGENTS.md render) and the generic personal `pack/unpack` bundle.

## [0.19.17] — 2026-06-17 — fix: bootstrap.py runnable by direct path

### Fixed
- `scripts/bootstrap.py` lacked the sibling-import sys.path shim, so the
  documented `python .ai-playbook/scripts/bootstrap.py --update` (printed by the
  upgrade-playbook-pin runbook AND by `update-playbook --execute`) failed with
  `ModuleNotFoundError: No module named 'scripts'`. Added the canonical shim
  (`sys.path.insert(0, <repo root>)`, matching retain_memory.py et al.) so
  direct-path invocation works; `--update` defaults its target to cwd. Found by
  dogfooding the v0.19.15/16 consumer-upgrade flow.
- Regression test (`tests/test_bootstrap.py`): `bootstrap.py --help` via direct
  path from a foreign cwd exits 0.

### Known issue (deferred)
- `render_agents_md` renders the template OVER a hand-authored / markerless
  consumer `AGENTS.md` (blanking its `inherits_from` pin + duplicating static
  sections). A naive markerless guard breaks the intended marker-seeding path,
  so the correct fix (preserve consumer frontmatter + de-dup on seed) is tracked
  for a dedicated change. Workaround: keep `bootstrap --update` to consumers
  whose `AGENTS.md` already carries `ai-playbook:` markers.

## [0.19.16] — 2026-06-17 — fix: AGENTS.md template prose example parsed as a real marker

### Fixed
- `templates/new-project/AGENTS.md.tmpl` carried a prose EXAMPLE marker
  `<!-- ai-playbook:begin id=… -->` inside explanatory text. `parse_blocks`
  matched it as a real (unclosed) marker, so `render_agents_md` raised
  `marker mismatch: begin id='…', end id='bootstrap-directive'` — breaking
  `bootstrap --update` managed_files for every consumer that renders AGENTS.md.
  Escaped the example (dropped the `<!-- -->` delimiters). Found by dogfooding
  the v0.19.15 upgrade flow on a real consumer.
- Regression test (`tests/test_renderers.py`): the shipped template renders +
  round-trips its 4 managed blocks (bootstrap-directive, dispatcher-index,
  capability-map, mcp-sources) without raising.

## [0.19.15] — 2026-06-17 — consumer upgrade UX: graphify setup, doctor self-heal, executable pin bump

### Added
- `graphify setup` subcommand (`scripts/graphify/cli.py`) — automates the
  per-machine/per-clone bootstrap (`uv tool install "graphifyy>=0.8.31"` +
  `graphify hook install`), so operators no longer run those by hand. `--dry-run`
  previews; degrades with an actionable error when `uv` is absent.
- `doctor --install-deps` (`scripts/doctor.py`) — self-heal for the common
  "consumer venv lacks jsonschema/pyyaml" failure: editable-installs the
  playbook (`pip install -e`, with an `ensurepip` fallback) then runs the checks.
- `update-playbook.rule.py apply --execute` — promotes the bump from plan-only
  to executing it: fetch + checkout latest tag + re-pin `inherits_from` in
  AGENTS.md + stage both (no commit; reconcile then commit together).
- New runbook `docs/runbooks/upgrade-playbook-pin.md` — the canonical
  bump → `bootstrap.py --update` (reconcile) → `doctor` flow, ending the
  per-consumer "discovery" of how to upgrade a pin.

### Fixed
- `.gitignore` now anchors `/graphify.json` and `/ponytail.json` alongside
  `/caveman.json`, so enabling those features no longer leaves the submodule
  root dirty in consumer repos (regression from the v0.19.12/v0.19.14 feature
  additions, which shipped the toggles without the matching ignore entries).

## [0.19.14] — 2026-06-17 — ponytail feature (lazy/minimal code mode) + subagent-prompt hardening

### Added — `ponytail` feature (lazy/minimal code mode) + `ponytail-reinforce` rule

Ports [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT) —
the code-minimalism twin of caveman — into a first-class, toggleable playbook
feature. Where caveman compresses how the agent *talks*, ponytail disciplines
what it *builds* (YAGNI → stdlib → native → installed dep → one line → minimum),
while never simplifying away trust boundaries (validation, error handling,
security, accessibility). The two are orthogonal and compose.

- **New subsystem `scripts/ponytail/`** (`toggle` / `materialise` / `cli`,
  `python -m scripts.ponytail status|on|off`) mirroring the caveman feature shape
  and reusing the shared utilities (`scripts._project_root`,
  `scripts.auto_managed`, `scripts.caveman.backup`). Per-project state at
  `.ai-playbook/ponytail.json` (schema `ponytail-toggle/v1`); four components —
  `code_style` (materialises a ladder block in AGENTS.md + per-turn
  reinforcement, the only side effect) and `review_ponytail` / `audit_ponytail` /
  `debt_ponytail` (capability gates). Three intensity modes (lite / full / ultra).
- **New skills** `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`,
  `ponytail-help` under `skills/`. The `auto_managed` dispatcher learns the
  `ponytail/ruleset:<mode>` source so the AGENTS.md block round-trips through the
  drift checker.
- **New advisory rule `ponytail-reinforce`** (`UserPromptSubmit`,
  `scripts/rules/ponytail-reinforce.rule.py` + `docs/rules/ponytail-reinforce.rule.md`)
  — a ≤50-token per-turn nudge when `code_style` is on; silent-fail, never blocks.
  Wired into the bootstrap `.claude/settings.json` template alongside
  `caveman-reinforce` (both coexist; each no-ops when its feature is OFF).
- **Config UI Features tab** gains a Ponytail card; `apply_config.py` delegates
  `features.ponytail` to `python -m scripts.ponytail on/off` (preflight + audit +
  rollback reconciliation, mirroring caveman/graphify). `schema-ponytail-toggle-v1.json`
  + a `ponytail` block in `schema-ai-playbook-config-v1.json` + `defaults.json`.
- **Bootstrap**: ponytail is **default-ON**, like caveman — opt out with
  `--no-ponytail`. The playbook dogfoods it ON (the `ponytail/ruleset:full`
  block is committed in this repo's `AGENTS.md`).
- **Docs + tests**: concept / architecture / runbook docs, the `ponytail-toggle`
  spec, a 3-arm eval harness under `tests/evals/ponytail/` (measures **code lines**,
  honest delta ponytail-vs-minimal), and `tests/test_ponytail_*.py` mirroring the
  caveman toggle/cli/materialise/reinforce/evals coverage.

### Changed — subagent prompt hardening + force-push deny (CL4R1T4S-informed)

Hardened the spawn-time guarantees of isolated subagents, prompted by reviewing
the system-prompt patterns in [elder-plinius/CL4R1T4S](https://github.com/elder-plinius/CL4R1T4S)
(production agent prompts consistently encode anti-fabrication, ask-don't-assume,
and explicit stop-conditions — gaps our isolated subagents had, since they do not
inherit the interactive operator's global principles).

- **`templates/subagent-prompt.md.tmpl`** — three new Hard rules (6–8), each
  mapped to an existing failure mode in
  [agentic-failures.md](docs/concepts/agentic-failures.md): **#6 no fabricated
  verification output** (`over_confidence` §2.5 / `hallucination` §2.1), **#7 no
  silent assumptions — surface `❓ CLARIFICATION NEEDED`** (`hallucination` §2.1),
  **#8 no `done` with silent loose ends** (`premature_completion` §2.8). Five-section
  structure unchanged; additive only.
- **`templates/new-project/.claude/settings.json.tmpl`** — deny-list now blocks
  raw `git push --force origin*` / `git push -f origin*` on **any** branch (not
  just main/master). `--force-with-lease` stays allowed so the §6.5 pre-flight
  rebase flow is unaffected.

## [0.19.13] — 2026-06-16 — fix: alembic-single-head CLI parses on CPython 3.11/3.12

### Fixed

- **`alembic-single-head.rule.py` CLI argparse** — the rule used a bare
  `choices`-positional (`subcommand`) followed by a `nargs="*"` positional
  (`paths`). On CPython 3.11/3.12 that shape fails to consume the trailing path
  (`error: unrecognized arguments: <dir>`), so the rule's own test suite was red
  on the `test` CI job (3.11 + 3.12) since v0.19.10 — even though it passed on
  3.13. Restructured to a `validate` **subparser** (the version-robust shape
  already used by `scripts/caveman/cli.py`); behaviour, flags (`--base`), and
  exit codes are unchanged. Greens the `test` job across all supported Pythons.

## [0.19.12] — 2026-06-15 — graphify feature (adoption rule + skill + Features-tab)

### Added — `graphify` feature + `graphify-adoption` rule

Promotes [graphify](https://github.com/safishamsi/graphify) (a committed AST
knowledge graph under `graphify-out/`) into a first-class, toggleable playbook
feature alongside caveman.

- **New opt-in rule `graphify-adoption`** (`activation: manual`; not-applicable
  when the repo does not commit a graph). `scripts/rules/graphify-adoption.rule.py`
  (`validate`/`apply`, exit 0/1/2) enforces that the per-machine/per-run graph
  state (`.graphify_python`, `.graphify_uncached.txt`, `cost.json`, `cache/`,
  dated snapshot dirs) is gitignored and that `graphify-out/graph.json` has a
  union-merge driver registered (via `graphify hook install`). `apply` converges
  `.gitignore`; the `.gitattributes` half is delegated to `graphify hook install`
  (graphify owns the driver name). A `graphifyy < 0.8.31` is an advisory.
- **New skill `skills/graphify/SKILL.md`** — agent-facing usage (query-first
  navigation, prefer the graph over grep, update-after-edit).
- **New concept** `docs/concepts/graphify.md` (graph vs RAG, multi-dev model)
  and **runbook** `docs/runbooks/graphify-setup.md` (install + `graphify hook
  install` + verify + uninstall).
- **Features surface** — graphify is now a toggleable Feature in the config UI
  (mirrors caveman): new `scripts/graphify` package (`toggle` + `materialise` +
  `cli`: `python -m scripts.graphify status|on|off`), state schema
  `schema-graphify-toggle-v1.json`, `features.graphify` in the config-bundle
  schema, `features-inventory.json` + `defaults.json` entries, and an
  `apply_graphify` delegation section in `scripts/apply_config.py` (with
  preflight + non-transactional rollback-reconcile parity). Unlike caveman
  (in-repo CLI), graphify wraps an EXTERNAL PyPI tool — the toggle manages the
  in-repo side effects (AGENTS.md guidance block + `.gitignore` hygiene) and
  surfaces, but cannot run, the per-machine `uv tool install graphifyy>=0.8.31`
  + per-clone `graphify hook install`.

## [0.19.10] — 2026-06-04 — alembic single-head rule (single-head invariant)

### Added — `alembic-single-head` rule (single-head invariant, L1 + L2 + L3)

- **New paired rule `alembic-single-head`** enforcing that the Alembic migration
  chain resolves to **exactly one head**. A forked multi-head chain makes
  `alembic upgrade head` abort ("Multiple head revisions are present"), breaking
  deploys, the CI migrate step, and any container entrypoint that runs
  `alembic upgrade head` (e.g. `sh -c "alembic upgrade head && uvicorn ..."`).
  Complements [`migration-slot-reservation`](docs/rules/migration-slot-reservation.rule.md)
  (which prevents the slot collision at propose time) with a merge-/CI-time
  safety net for repos that merge with red CI / no branch protection.
- **L1** `scripts/rules/alembic-single-head.rule.py` — STATIC validator (no DB,
  no `alembic` install): parses `revision`/`down_revision` via `ast`, computes
  heads (revisions no other migration names as a parent), exits 1 on >1 head or
  on an empty/orphaned migration file. A file argument resolves to its parent
  directory, so editing one migration checks the whole `versions/` folder.
  Supports `--base <gitref>` (or `--base auto`, which resolves the remote's
  default branch — origin/sole-remote; main/master/trunk/develop — with no
  `main`/`origin` assumption) to union the branch's migrations with the base's
  (read via `git show`) so a sibling head that already merged into the base is
  caught WITHOUT a local rebase — the fetch+rebase discipline made enforceable.
- **L2** `docs/rules/alembic-single-head.rule.md` — sandwich-defended contract +
  the "how to fix a multi-head chain" recipe (no-op merge node).
- **L3** `templates/new-project/.github/workflows/alembic-single-head.yml.tmpl` —
  consumer-installable required check (toggle-aware).
- **Tests** `tests/test_alembic_single_head_rule.py` — 16 fixtures (single head,
  two heads, merge-node collapse, empty orphan, non-migration skip, file→dir
  resolution, annotated assignment, missing path, empty dir, plus three
  git-integration cases for `--base`: cross-branch fork detection, merge-node
  resolution, graceful degrade, plus `--base auto` resolution across
  main/master/trunk and origin/non-origin remotes).
- Registered in `AGENTS.md` Rule Map, `docs/rules/INDEX.md`, and the config-UI
  rules inventory. Origin: the `033_*` two-head fork that broke geeplo
  deploys + e2e api boot on 2026-06-03.

## [0.19.9] — 2026-06-01 — config-UI file:// + green CI

### Fixed — CI gates green again (`chore/ci-green-ruff-and-gates`)

- **`ruff check .` clean.** Cleared the 97 accumulated lint violations the `test`
  workflow was failing on (which also blocked pytest from running): auto-fixable
  ones via `ruff --fix` (+ vetted `--unsafe-fixes`: `isinstance` PEP-604 unions,
  `Callable` moved to `collections.abc`, etc.), `E402` on intentional
  post-preamble imports marked `# noqa: E402`, long lines wrapped, two unreadable
  auto-generated ternaries reverted to `if/else`.
- **`apply-skill-enforcement.rule` workflow** invoked its validator as
  `python -m scripts.rules.apply-skill-enforcement` — a kebab-case name that is not
  an importable module (`No module named …`), so the gate failed on every PR. Now
  invoked by path (`python scripts/rules/apply-skill-enforcement.rule.py …`), matching
  the script's own documented usage.
- **`check-rule-schemas.rule` concept validation** failed on
  `docs/concepts/skills-mcps-enforcement.md`: its frontmatter used `description`/`audience`
  (not in `schema-concept-v1.json`) and lacked the required `title`. Conformed to the
  schema (`description`→`summary`, added `title`, dropped the non-schema `audience`).

### Added — config-UI works under `file://` (`feat/config-ui-file-sidecars`)

- **No local server required.** The config UI's six inventories (rules, features,
  global-flags, skills, mcps, defaults) now each ship a `.js` sidecar
  (`window.RULES_INVENTORY = {…}`, etc.) loaded via `<script src>` — which browsers
  permit under `file://`, where `fetch()` is blocked by CORS. The UI is now a true
  double-click HTML, matching the existing applied-config/files-state/dashboard
  sidecars. `app.js` prefers the injected global and falls back to `fetch()` of the
  `.json` when served over http(s), so the JSON stays the source of truth for
  programmatic/CI use.
- **`scripts/build_ui_sidecars.py`** generates the `.js` from whatever the committed
  `.json` holds; `--check` is a freshness gate wired into `check-rule-schemas.rule.yml`
  and a `ui-sidecars-check` pre-commit hook, so a `.json` edited without regenerating
  its sidecar fails CI rather than silently shipping a stale UI.

### Fixed — bump_consumers robustness (`fix/bump-consumers-robustness`)

- **Force-fetch tags.** `bump_consumers` now runs `git fetch --tags --force` on each
  submodule, so a release tag that moved on the remote no longer makes the whole
  fetch exit non-zero (`would clobber existing tag`) and abort the bump for
  consumers pinned at older tags.
- **Compare the committed gitlink, not the checked-out HEAD.** A submodule checked
  out at the target while the parent still pinned an older commit was wrongly
  reported `up-to-date` and skipped — the pointer bump (the whole point) never got
  committed. The comparison now reads `HEAD:.ai-playbook`.

### Changed — CI maintenance + docs

- **GitHub Actions bumped to Node-24 majors** (`chore/bump-gh-actions-node24`):
  `checkout` v4→v6, `setup-python` v5→v6, `github-script` v7→v9,
  `upload-pages-artifact` v3→v5, `deploy-pages` v4→v5, `upload-artifact` v4→v7 —
  ahead of Node.js 20's removal from GitHub-hosted runners (2026-09-16).
- **README** now sources the "neuro-symbolic" claim at its first mention (the TL;DR
  links to `docs/concepts/academic-foundations.md`), and the IBM entry there is
  retitled from "Position Paper" to a research overview (the cited URL is a blog).

## [0.19.8] — 2026-05-31 — reconcile foundation + agnostic config surface

### Added — template security guardrails (`feat/template-deny-guardrails`)

- **`permissions.deny` in the new-project template.** `templates/new-project/.claude/settings.json.tmpl` now ships 38 universal safety 
  guardrails (force-push to main/master, `git reset --hard`, `rm -rf` of system/root 
  dirs, `DROP DATABASE`/`DROP TABLE`/`TRUNCATE`, `dd`/`mkfs`, `shutdown`/`reboot`) so 
  every new consumer inherits the deny net. `deny` is enforced even under 
  `bypassPermissions`. Promoted from the maintainer global config during the 
  `~/.claude` audit; existing consumers pick it up on next bootstrap-from-template.

### Added — rules-lifecycle-hardening (`feat/rules-lifecycle-hardening`)

Makes adding/removing a rule safe and the config-UI 100% generated from the rules
that exist — closing the silent-drift failure modes found in the rule system.

- **Inventory freshness gate (A).** `rules_toggle inventory --check` regenerates
  in memory and diffs the committed `config-ui/rules-inventory.json` (ignoring
  `generated_at`), exit 2 on drift; also flags dangling hooks (a settings tmpl
  command pointing at a missing `scripts/rules/<slug>.rule.py`). Wired into
  `check-rule-schemas.rule.yml` + a `rules-inventory-check` pre-commit hook.
  Fixed a dead output path: both inventory generators wrote to the removed
  `tools/config-ui/` instead of the live `config-ui/`.
- **Live inventory + orphan prune (B).** `apply_config` builds the rules
  inventory live (stale-proof env-var projection) and drops bundle slugs absent
  from it, guarded so a missing inventory never wipes valid toggles.
- **Self-describing advanced sub-toggles (C).** `advanced` moved from the
  hardcoded `ADVANCED_SUB_TOGGLES` dict into each rule's frontmatter. Realigned
  `schema-rule-v1.json` with the canonical apply-skill-enforcement doc
  (description length, break_glass `_OVERRIDE`/`rollback_env`, `MultiEdit`
  trigger, new `advanced[]`); all 50 rule docs validate.
- **Per-AI capability (D).** Inventory gains `applies_to` + `l1_effective`
  (`has_l1 AND triggers AND claude-targeted`). The config-UI rules tab badges L1
  `n/a` where it can't fire and shows an "Applies to" chip strip (mirrors the
  Settings-tab D9/D10 gating).
- **Dispatcher executes rules in-process (E).** `hook_dispatcher` now RUNS matched
  rules (was match-only): a rule opts in via `pretooluse(event)`/`posttooluse(event)`
  (`scripts/rules/_hook_contract.py`), honouring the consumer's L1 toggle +
  `applies_to`, emitting real-verdict telemetry, failing OPEN on a rule error.
  `secrets-handling` (block on secrets in new content) and `english-only-docs`
  (block non-English full-file doc Writes) are retrofitted; the settings renderer
  ensures a generic dispatcher PreToolUse entry (`merge_required_dispatcher`,
  alongside the bespoke openspec-apply-enforce hook), so new trigger-rules
  auto-fire with zero settings edits. The git/PR/session validators
  (link-integrity, delegated-shipping-prompt, subagent-envelope-schema,
  update-documentation, …) are deliberately NOT dispatcher-executed — their
  inputs aren't in a tool event or would false-positive; they keep CI/pre-commit
  `validate` enforcement.

### Changed — reconcile foundation: one door for all writes (`feat/reconcile-single-door`)

Collapses the parallel file-writing paths into a single idempotent operation.
`apply_config.apply` is now THE door: bootstrap (the *first reconcile*),
`--update`, and the new `--check` (drift-CI gate) all funnel through it.
CHECK = `apply --dry-run`; REMEDY = `apply`. There is no second write path.
(openspec change: `reconcile-foundation`.)

- **Single entrypoint.** `scripts/bootstrap.py` no longer calls
  `materialise_skills` / `render_mcp_configs` / `enable_caveman_default` inline
  (all three deleted). A fresh install synthesises an "everything ON" defaults
  bundle (caveman omitted iff `--no-caveman`) and runs it through the door;
  `--update` resolves the consumer's bundle (`applied-config.json` or
  `migrate_to_bundle`) and reconciles the same way. New `bootstrap --check`
  runs a read-only reconcile and exits non-zero on drift.
- **`*_enforce` executes its consequence as a door section.** `skills_enforce`
  → `apply_skills_materialise`; `mcps_enforce` → `apply_mcp_render`. The
  state file is the input; the consequence runs right after it commits. Fixes
  the fresh-clone bug where `.claude/skills/` was never regenerated (the mirror
  is now a section of the door, materialised on every reconcile).
- **Additive, provenance-aware skills materialisation.** `materialise_skills`
  no longer `rmtree`s the whole mirror. A new `scripts/_skills_manifest.py`
  (`ai-playbook-skills-manifest/v1`, at `.ai-playbook-state/skills-manifest.json`)
  records playbook-owned dirs per mirror; only stale owned dirs are removed,
  user-added skills are preserved, and an absent manifest seeds
  `present ∩ desired` (deletes nothing). `SkillsMaterialisationResult` gains
  `user_dirs_preserved` + `stale_removed`.
- **Transactional managed-files write.** `apply_managed_files` now stages all
  renders in memory (a staging error aborts before any write) then commits the
  batch under one `session_id`; a commit failure rolls the batch back via the
  new `_backup_helper.restore_session` (restores pre-session content + deletes
  newly-created files). `applied-config.json` does NOT advance when the batch
  rolls back, so on-disk state and the persisted bundle never diverge.
- **Section registry.** `apply_config.SECTION_ORDER` + `SectionResult.section_id`
  replace the hand-numbered headers (and the duplicate `# Section 5`).
- **Telemetry.** The door (`apply_config`) is entry-wrapped with
  `script_emit("apply_config", main)` so a standalone invocation is observable;
  in-process it nests under the caller's span. A child `reconcile` span carries
  `ai_playbook.reconcile.mode` (`first_run` / `update` / `check`) — modes are
  distinguished by attribute, not by a separate slug, preserving metric
  continuity. The managed-files transaction emits
  `reconcile.managed_files.{staged,stage_failed,committed,rolled_back}` events
  with canonical `ai_playbook.managed_files.*` attributes.

### Changed — provenance conflict detection + agnostic settings (`feat/reconcile-single-door`)

- **Never overwrite silently.** The door now detects when a consumer edited a
  sealed canonical block (two-state: the `sha=` in the block's own on-disk marker
  vs the SHA of its current content — no external manifest). A drifted block with
  no curate decision is a CONFLICT: the file is skipped, the section reports
  failure, and `apply --dry-run` (= `bootstrap --check`, the drift-CI gate) fails
  on it. `keep_mine` restores + re-seals the consumer's content; `take_playbook`
  overwrites with a backup. Conflicts are per-file skips, not a full-batch abort,
  but still block `applied-config.json` from advancing past unresolved drift.
- **`.claude/settings.json` folded into the door.** New `_renderers/settings.py`
  does an identity deep-merge: it guarantees the openspec-apply-enforce PreToolUse
  invariant and projects the agnostic `settings` surface while preserving every
  consumer-authored key. Byte-level no-op when nothing changes (formatting kept).
  The legacy `claude-settings.rule.py apply` is superseded; its `validate` stays
  the L1 gate and now matches the enforce hook by command identity under any
  matcher (fixing the `Edit|Write|MultiEdit|Bash` template vs exact-matcher rule
  mismatch — no more false drift / duplicate entries).
- **Model-agnostic `settings` bundle key** (`hooks[]` with optional per-item
  `targets`, `permissions_allow`, `additional_directories`). One logical surface,
  projected per model. `claude_settings_extras` kept for backwards-compat
  (union-merged into settings.json permissions). Bootstrap's synth defaults carry
  `settings: {}` so the door owns `.claude/settings.json` from the first reconcile.
- **Gemini merge-preserve.** `mcp/render.py` now replaces ONLY `mcpServers` in an
  existing `.gemini/settings.json`, preserving user keys (theme/telemetry/hooks);
  Gemini hooks are not yet projected (capability-gated). Cursor degrades (no
  settings/MCP target — the door never invents `.cursor/mcp.json`).
- **caveman transaction-safety.** A pre-flight snapshots caveman's enabled-state
  before any mutation; when a managed-files batch rolls back after caveman ran,
  the report surfaces the exact manual reconcile step. caveman is NOT reordered to
  run last (that would break the locked caveman→MCP-render ordering the
  `mcp_shrink` post-hook depends on).
- **Conflict telemetry.** `reconcile.managed_files.conflict` event (file +
  conflicting block ids); the staged event carries a `conflicts` count.

### Changed — compare-and-swap round-trip + config-UI cleanup (`feat/reconcile-single-door`)

- **Optimistic concurrency (compare-and-swap).** `build_files_state.py` now emits
  a `\n`-normalised whole-file `file_sha` per managed file; the config UI stamps
  those into `bundle.base_shas`; `apply_config` recomputes each file's on-disk sha
  before writing and SKIPS it (per-file conflict, surfaced in `--check`) when it
  diverged since the UI loaded — so a structured config edited out-of-band is
  never silently clobbered. Complements the marker-block conflict gate.
  `reconcile.managed_files.cas_conflict` telemetry event; optional `base_shas`
  schema key.
- **Removed the stale `tools/config-ui/`.** It was an untracked working-tree
  leftover from the b37f744 move to repo root; deleting it only cleaned local
  cruft (no tracked content, no history rewrite).

### Added — dispatcher curate (`feat/reconcile-single-door`)

- **Structural drift engine** (`scripts/_dispatcher_shape.py`). Detects loose
  prose (>10 substantive lines, principle #2) living OUTSIDE marker blocks in a
  dispatcher (`AGENTS.md`/`CLAUDE.md`/`GEMINI.md`/`.cursor`), with per-chunk
  provenance + a suggested destination. Drift is defined STRUCTURALLY (D3) — once
  prose is moved to a leaf doc (exempt), a re-run is a no-op, so curate converges.
- **Wrap-not-rewrite adoption** (`scripts/_renderers/_wrap_legacy.py`).
  `seed_markers` appends only the canonical blocks a legacy file is MISSING
  (sealed sha), preserving its prose + existing blocks verbatim. Idempotent.
- **BASE snapshot** (`scripts/_backup_helper.py`, D8). `backup_base` captures the
  pre-playbook content of a file once (tag `base`, central, never pruned);
  `restore_base` is the uninstall recovery path.
- **`curate` — the LLM-assisted, human-gated, one-shot consolidator**
  (`scripts/curate.py`, deliberately NOT importable from `apply`). detect →
  announce → guardrail (`secrets_scan` + `prompt_injection_filter`, fails safe;
  tainted prose never reaches the model) → LLM proposes a `curate-plan/v1` of
  VERBATIM moves → `_curate_validate` (anti-fabrication substring check, no path
  traversal, leaf-doc/AGENTS dest, pointer-shaped) → BASE snapshot → move prose +
  leave thin pointers. `--dry-run` previews; `--yes` applies; default refuses
  without consent. The LLM never writes; it only returns a plan.

### Added — config-UI custom surface (`feat/config-ui-custom-surface`)

- **Dispatchers tab** — aggregated `.md` drift view (D14). `build_files_state`
  emits `dispatcher_drift` in the sidecar (via `_dispatcher_shape.collect_drift`);
  the tab renders each loose-prose chunk with provenance + a suggested
  destination, plus a "Copy curate command" trigger.
- **Settings tab** — the model-agnostic surface (D5): hooks (event/matcher/
  command/timeout) with a per-hook capability strip, plus permissions-allow +
  additional-directories. Emits `settings` sparse (omits `targets` when a hook
  applies to all models). Capability-gated (D9/D10): Claude is supported today;
  Gemini (`mcpServers` only) and Cursor render `n/a` — the badges become scope
  toggles when a second model gains hook support.
- **Config files tab** — `.gitignore` extra patterns + `.coderabbit` path
  filters (string lists) **plus native editors** for `.pre-commit-config.yaml`
  hooks (id + common fields + arg/stage/dep lists; unknown keys preserved) and
  `mcp-servers.project.yaml` records (transport / command|endpoint / scope /
  auth / env / capabilities_hint; `scope: personal` disallowed at the project
  layer). `config-files-inventory.json` flips both to `editable_in_ui: true`.
  CodeRabbit `path_instructions` (free-form prose) still round-trip via JSON
  import.
- **Restore (D8)** — `scripts/restore.py`, a human-gated per-file restore CLI
  wrapping `_backup_helper` (preview without `--yes`; `--from` / `--base` /
  `--all-base`). The Files-tab Restore button is un-disabled and copies the
  command for the selected backup.
- **pre-commit renderer** — emits YAML-idiomatic lowercase booleans (was
  `str(bool)`), surfaced by the new `pass_filenames` editor.
- Verified with the Playwright sweep (every tab driven, A=0/B=0), a targeted
  nested-editor round-trip probe, a schema round-trip test on the emitted
  `settings` shape, and `tests/test_restore.py`.

Deferred to follow-up changes: trimming `copy_templates` to a minimal seed and
the formal idempotency / clone-repro / telemetry-emission tests. (The per-file
`dispatch` trigger in the drift view is intentionally *not* built: `curate` is
cross-file by D15, so the single "Copy curate command" is the faithful trigger
for a static-HTML page.)

## [0.19.7] — 2026-05-27 — bundle-driven managed-files redesign

### Added — bundle-driven managed-files redesign (`feat/bootstrap-dispatch`)

Major redesign of how `bootstrap` and `apply_config` interact with consumer
files. Solves the long-standing footgun: re-running bootstrap clobbered
consumer customisations because `copy_templates` overwrote unconditionally.

**Files are now SSOT** (each managed file is authoritative for its own
content). **Bundle is an ephemeral transfer format** — the UI loads files,
parses them, lets the user curate, and the apply pipeline regenerates each
managed file from `(template, substitutions, bundle)`. Re-applying the same
bundle is idempotent (byte-identical, no backup churn). Drift is detected
via SHA-256[:12] of each marker block content against the saved manifest.

**Marker blocks** delimit playbook-canonical content inside the files:
`<!-- ai-playbook:begin id=... -->` (HTML/markdown), `# >>> ai-playbook:begin
id=... >>>` (shell/yaml/gitignore), `// ai-playbook:begin id=...` (JSON5/JS).
Content OUTSIDE markers is consumer-owned and preserved verbatim.

#### Foundation primitives

- **`scripts/_backup_helper.py`** — `backup_once(consumer, file, *, location, with_timestamp, session_id)` with two destinations (`NEXT_TO_FILE` default — alongside source, user-visible; `CENTRAL` — `.ai-playbook-state/backups/<rel-path>.bak`). Discovery via `<consumer>/.ai-playbook-state/backups/index.json` (schema `ai-playbook-backups/v1`). `latest_backup_for`, `list_backups_for`, `restore_backup`, `prune_backups`. Atomic writes via temp+rename. Windows-safe timestamp format (no colons). Stdlib-only.
- **`scripts/_marker_blocks.py`** — `parse_blocks` / `write_blocks` for HTML, hash-comment, and slash-comment styles. Round-trip is byte-exact when nothing changes (idempotency invariant). Raises on unmatched / duplicate / mismatched markers. `style_for_filename` convenience guesser.
- **`scripts/_template_classifier.py`** — `classify(text, style, expected_shas, rel_path)` returns a `FileClassification` whose `sections` list interleaves canonical/drifted/custom segments in document order. Two-state SHA semantics: match = canonical, mismatch (or absent from manifest) = drifted. `build_manifest` + `compute_sha` (SHA-256[:12]).

#### Bundle schema extensions

- **`schemas/schema-ai-playbook-config-v1.json`** — backwards-compatible additive sections: `project_meta` (free-form AGENTS.md content: project_identity, active_work, hard_rules, inherited_overrides, gotchas), `gitignore_extras.patterns`, `pre_commit_extras.hooks`, `coderabbit_extras.{path_filters, path_instructions}`, `claude_settings_extras.{permissions_allow, additional_directories}`, `mcp_project_servers`, `file_states` (per-file SHA manifest), `caveman_section_policy` (user-toggleable compression flags), `backup_preferences` (location + timestamp + retention).

#### Templates with markers

- **`templates/new-project/AGENTS.md.tmpl`** — wraps §0/§2/§5/§6 in marker blocks with semantic ids: `bootstrap-directive`, `dispatcher-index`, `capability-map`, `mcp-sources`. Free-form §1/§3/§4/§7/§8 stay as consumer placeholders.
- **`templates/new-project/.gitignore.tmpl`** — single `id=playbook-patterns` block wrapping the existing + new entries (`.ai-playbook-state/`, `*.bak`, timestamped backups).
- **`templates/new-project/.pre-commit-config.yaml.tmpl`** — `id=playbook-hooks` block. Each hook gets a graceful shim: `bash -c '[ -d .ai-playbook ] && python ... || exit 0'` so deleting the submodule does NOT block commits.
- **`templates/new-project/mcp-servers.project.yaml.tmpl`** — `id=project-servers-baseline` wraps the hindsight bootstrap entry.
- **NEW `templates/new-project/.claude/settings.local.json.tmpl`** — seed-only stub (Claude Code merges this natively on top of settings.json).

#### Per-file renderers (`scripts/_renderers/`)

Pure functions `(template, substitutions, bundle) -> str` — no filesystem access, caller handles backup + atomic write.

- `agents_md.py` — placeholder substitution + project_meta projection + SHA injection into all marker blocks.
- `gitignore.py` — marker block + `bundle.gitignore_extras.patterns` + `current_text` preservation with dedup.
- `pre_commit.py` — marker block + `bundle.pre_commit_extras.hooks` rendered as a `local-extras` repo group.
- `coderabbit.py` — appends extras as YAML comments (proper merge deferred).
- `claude_settings.py` — `render_main` (canonical) + `render_local` (seed-only when no extras present).
- `mcp_project.py` — marker block + `bundle.mcp_project_servers` as additional YAML entries.

#### apply_config integration

- **`scripts/_managed_files.py`** — catalog + `apply_managed_files(consumer_root, playbook_root, bundle, session_id, dry_run)` orchestrator. Per-file flow: read template → renderer → `backup_once` if file exists → atomic write. Returns `{file_states, restart_session_needed, changes}`. Seed-only behaviour for `.claude/settings.local.json` (created once, never overwritten on subsequent applies). LLM-read files (AGENTS.md, CLAUDE.md, GEMINI.md, .claude/*) flag `restart_session_needed` for the apply_config banner.
- **`scripts/apply_config.py`** — wired as section 6 (before applied-bundle persistence). Legacy bundles without trigger sections (`project_meta`, etc.) skip this entirely — backwards compatible. Backup preferences honoured via `bundle.backup_preferences`. Section 8 also regenerates `files-state.js` for the UI Files tab.

#### Migrate + bootstrap --update

- **`scripts/migrate_to_bundle.py`** — extracts consumer customisations from an already-bootstrapped project. Parses `AGENTS.md` to lift §1/§3/§4/§7/§8 into `project_meta`; reads `.gitignore` lines outside marker blocks into `gitignore_extras`; reads `mcp-servers.project.yaml` (excluding the hindsight baseline) into `mcp_project_servers`; reads `.claude/settings.local.json` permissions into `claude_settings_extras`. CLI: `python -m scripts.migrate_to_bundle [--target PATH] [--out BUNDLE.json] [--apply]`.
- **`scripts/bootstrap.py --update`** — safe inverse of fresh install. Skips submodule-add + copy_templates (those would clobber). Pipeline: (1) locate `.ai-playbook/applied-config.json` or invoke migrate, (2) `apply_config` on the resolved bundle, (3) re-materialise skills, (4) re-render MCP configs, (5) advisory drift check. `project_name` argument optional under `--update` (taken from AGENTS.md frontmatter).

#### Graceful uninstall

- **`scripts/uninstall.py`** — restores each managed file from the OLDEST `.bak` record (pre-playbook snapshot) when `--restore-from-bak` (default); for files without a `.bak`, strips marker blocks while keeping consumer custom segments verbatim. Removes `.ai-playbook/` submodule (deinit + git rm, falls back to rmtree). Removes `.ai-playbook-state/` unless `--keep-state-dir`. Interactive confirm (skippable with `--yes`).
- Pre-commit shims in templates already make the uninstall non-disruptive: if a consumer simply deletes the submodule, hooks fall back to `exit 0` instead of blocking commits.

#### UI Files tab (v1 read-only inspector)

- **`scripts/build_files_state.py`** — generates `<consumer>/.ai-playbook-state/files-state.js` (window-scoped sidecar). Schema `files-state/v1`: per-file sections with previews + counts + orphan ids, plus the backup index from `_backup_helper`. Apply_config regenerates this on each apply.
- **`tools/config-ui/index.html`** — new Files tab between MCPs and Preview. Left-rail file list (C/X/drift counts), right inspector with per-section badges. Sidecar loaded via `<script src>` so `file://` works.
- **`tools/config-ui/app.js`** — `renderFiles()` paints the rail + inspector. Restore-from-`.bak` dropdown surfaces the index; restore is CLI-only (belt-and-suspenders against accidental destructive UI actions).
- **`tools/config-ui/style.css`** — Files tab styling: badges (canonical green, drifted orange, custom blue), monospace previews with max-height, responsive single-column under 800px.

Curate flow (v2 file-level "keep mine / take playbook / merge") and per-section granular curate (v3) are scoped for follow-up commits — see [roundtable summary](docs/concepts/bundle-managed-files.md) for the deferred work.

#### Caveman policy

- **`scripts/caveman/policy.py`** — codifies the AI/LLM-expert never-compress list. Marker block ids `bootstrap-directive`, `dispatcher-index`, `capability-map`, `mcp-sources` and project_meta key `hard_rules` are NEVER compressed regardless of the user's global toggle (LLMs rely on precise imperative grammar + negations like 'never', 'must not'). Safe-to-compress: `project_identity`, `inherited_overrides`, `gotchas`, `active_work`. MCP server descriptions default OFF, per-server opt-in only. Query helpers: `is_block_compressible`, `is_project_meta_key_compressible`, `is_mcp_description_compressible`.

#### Tests + docs

- **88 new tests** across `tests/test_backup_helper.py` (22), `tests/test_marker_blocks.py` (26), `tests/test_template_classifier.py` (12), `tests/test_renderers.py` (15), `tests/test_managed_files.py` (11), `tests/test_migrate_to_bundle.py` (13), `tests/test_uninstall.py` (8), `tests/test_build_files_state.py` (6), `tests/test_caveman_policy.py` (15).
- **`docs/concepts/bundle-managed-files.md`** — design overview, mode tables, marker grammar, migration flow, uninstall, follow-up scope.

### Consumer action

- **Existing consumers**: re-running `bootstrap` is still safe with the legacy bundle (no `project_meta` / extras sections → managed-files section is a no-op). To opt into the bundle-driven flow, run `python -m scripts.migrate_to_bundle --apply --target .` from the consumer root — extracts current state into a bundle, then `apply_config` renders the managed files with markers + backs up originals.
- **Fresh installs**: `bootstrap <project>` continues to copy templates as before. The marker blocks appear in the resulting files; subsequent `apply_config` invocations honour them.
- **Future updates**: `python -m scripts.bootstrap --update --path .` is the new recommended way to bump playbook versions on an already-bootstrapped consumer (no more `copy_templates` clobber).
- **Uninstall**: `python -m scripts.uninstall` (interactive). `.bak` files in `<consumer>/.ai-playbook-state/backups/index.json` (or alongside originals if `backup_preferences.location=next`) provide the rollback path.

### Added — per-Skill + per-MCP enforcement toggles in the config UI

- **New schemas** — `schemas/schema-skills-enforce-v1.json` and `schemas/schema-mcps-enforce-v1.json`. Negative-list (opt-out) contract: only DISABLED entries are persisted. State files land at `<consumer>/.ai-playbook-state/{skills,mcps}-enforce.json`. Default = all enforced.
- **`scripts/_enforce_state.py`** — stdlib-only helper module imported by hot paths (`materialise_skills`, `mcp/render`, `mcp/validate`). Reads disabled sets tolerantly: missing/malformed/wrong-schema all return empty set ⇒ default behaviour (everything enforced) so a corrupted state file never silently strips skills or MCPs.
- **`scripts/materialise_skills.py`** — `_dir_fingerprint` + `_sync_one` now accept an optional `exclude_top_dirs` / `disabled` set. Disabled skill slugs are excluded from the source fingerprint (idempotency stays correct when the disabled set is stable) AND from the `shutil.copytree(ignore=...)` callable so they never reach `.claude/skills/`, `.gemini/skills/`, or `skills/`. Default-on (empty disabled set) is a byte-identical no-op vs prior behaviour.
- **`scripts/mcp/render.py` + `scripts/mcp/validate.py`** — both call `_enforce_state.disabled_mcps` after `merge_servers` and strip disabled IDs from the merged map before the scope-leak / env-required / drift checks run. Disabled servers never appear in `.mcp.json` or `.gemini/settings.json`.
- **`scripts/apply_config.py`** — two new orchestrator sections, `skills_enforce` + `mcps_enforce`. Each writes its state file with the schema literal + sorted-deduped disabled list + `applied_at` timestamp. Empty disabled array still produces a state file (explicit no-op intent); omitting the section leaves any existing state file untouched.
- **`schemas/schema-ai-playbook-config-v1.json`** — extended the bundle schema with optional `skills_enforce` + `mcps_enforce` sections (each `{disabled: string[]}`). Backwards-compatible — bundles produced by the pre-feature UI still validate.
- **`scripts/build_enforce_inventories.py`** — new helper that re-scans `skills/` + the MCP YAML layers to (re)generate `tools/config-ui/{skills,mcps}-inventory.json`. Run after adding/removing a skill or an MCP server to keep the UI in sync.
- **`tools/config-ui/skills-inventory.json`** + **`mcps-inventory.json`** — generated artefacts consumed by the UI. Today: 78 skill entries + 8 MCP server entries (base layer + project-template).
- **Config UI — two new tabs**:
  - **Skills**: grid of every shipped skill with a default-checked checkbox (enforced). Toolbar: search by slug/description, "only disabled" filter, "Enable all" / "Disable all" bulk actions, live "X/Y enforced (Z disabled)" summary.
  - **MCPs**: grid of every MCP server discovered in the base + project-template layers with id, layer-of-origin, transport, and scope badges. Same toolbar shape as Skills.
- **`tools/config-ui/style.css`** — new `.enforce-toolbar`, `.enforce-list`, `.enforce-row`, `.enforce-cell`, `.enforce-name`, `.enforce-badges`, `.enforce-desc`, `.enforce-summary` styles for the two new tabs. Responsive break at 700 px.
- **`tools/config-ui/app.js`** — state container gains `skills_enforce: {disabled: []}` + `mcps_enforce: {disabled: []}` containers, hydrated from `window.APPLIED_CONFIG` on load. Export bundle is sparse: only emits the section if `disabled` is non-empty. Import/Reset paths handle the new fields.
- **`tools/config-ui/index.html`** — two new tabs (`data-tab="skills"` / `data-tab="mcps"`) and matching `<section>` panels. Header subtitle extended to mention the new categories.
- **Tests** — 31 new tests across `tests/test_enforce_state.py` (10), `tests/test_materialise_skills.py` (+5), `tests/test_mcp_render.py` (+3), and `tests/test_apply_config.py` (+5 — write/read state files, sorted+deduped output, empty-disabled-array intent, no-section-no-file).

### Consumer action

- **None** for existing consumers — default state (no `skills-enforce.json` / `mcps-enforce.json` on disk) is "everything enforced", identical to pre-feature behaviour.
- To disable specific skills or MCPs: open the config UI (Skills or MCPs tab), uncheck the entries, Export bundle, and run `python -m scripts.apply_config <bundle>` from the consumer root. The next `materialise_skills` / `mcp/render` invocation will honour the new state.
- After adding a new skill or MCP server to the playbook, regenerate the inventories with `python -m scripts.build_enforce_inventories` and commit the updated `tools/config-ui/{skills,mcps}-inventory.json`.

### Changed — README

- **`README.md`** — dropped two forward-looking references to a hypothetical v0.20.0 milestone (one in the L1/L2/L3 LLM coverage table, one in the Versioning section). The repo lifecycle no longer name-checks unreleased versions.

## [0.19.6] — 2026-05-25 — config UI + L1 Bash enforcement + OTel tracing + script_emit + Mermaid docs + (post-tag) submodule hygiene + bootstrap-wired ai-playbook-check

> **Note:** the v0.19.6 tag was force-moved on 2026-05-26 to include several post-tag bugfixes accumulated on `main`. Operators who pulled v0.19.6 before the move should re-fetch (`git fetch --tags --force`). The sections below cover BOTH the original 0.19.6 payload (committed up to commit `1d41ee4`) AND the post-tag fixes folded into the same tag.

### Added — telemetry Dashboard tab in the config UI (post-tag)

### Added — telemetry Dashboard tab in the config UI

- **`schemas/schema-dashboard-data-v1.json`** — new sidecar contract (`dashboard-data/v1`). Top-level: `schema_version`, `generated_at`, `pricing_version` (sha256 of `configs/pricing.yaml` at run time), `window`, `empty_state_threshold`, `caveman_state`, `panels`. Panel sub-schemas: hero (incidents + LLM01 sub-count), secondary (obey-rate + cost + emoji), trend (daily buckets), matrix (rule × LLM with drift flag), honesty (`self_check` ↔ `verdict` agreement per LLM), friction (top break-glass rules), caveman (on/off/missing branches via `oneOf`).
- **`scripts/telemetry/build_dashboard_data.py`** — new offline aggregator. CLI: `--window {7d,30d}`, `--output`, `--consumer-root`, `--state-dir`, `--pricing-path`, `--schema-path`, `--empty-state-threshold`, `--quiet`, `--no-validate`. Reads `<consumer>/.ai-playbook-state/rule-events.jsonl` (`rule-event/v2`), invokes `scripts/caveman/stats` via direct import (fallback subprocess `python -m scripts.caveman.stats --json`), pins `configs/pricing.yaml` sha256 per run. Atomic temp+rename write. Torn-line tolerant (skips + counts `events_skipped`). Privacy guards re-validate `target_rel` against glob form. Computes drift in two senses (cross-LLM spread > 0.10; per-LLM time-over-time delta > 0.05) with sample-size floors (matrix 30 events / rule, honesty 50 events / LLM). Validates output against `schema-dashboard-data-v1.json` before atomic rename; on failure exits non-zero and leaves the prior sidecar untouched.
- **`scripts/apply_config.py`** — new `_rebuild_dashboard_sidecar(target)` helper invoked as Section 5 after the `applied-config.js` write. Failure isolated: any exception from the aggregator is captured in the `SectionResult` and never raised, so a broken telemetry pipeline cannot break `apply_config`.
- **`tools/config-ui/index.html`** — new **Dashboard** tab nav button + `<section id="panel-dashboard">`. New `<script>` tags (in order): `dashboard-data.js` sidecar (`onerror` sets `window.DASHBOARD_DATA_MISSING=true`), Chart.js 4.4.7 from `https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js` with `integrity="sha384-vsrfeLOOY6KuIYKDlmVH5UiBmgIdB1oEf7p01YgWHuqmOHfZr374+odEv96n9tNC"` (single external dep, SRI-pinned), `dashboard.js` renderer, then `app.js`.
- **`tools/config-ui/dashboard.js`** — new vanilla-JS renderer exposing `window.DashboardRender.mount(target)`. Branches on missing sidecar / schema mismatch / empty state / chart-library-failed / data-rendered. Renders hero + 3 secondary stats + 5 panels (trend Chart.js line, matrix with drift highlighting, honesty meter, friction bars, Caveman impact with off/missing branches). **Refresh** button copies `python -m scripts.telemetry.build_dashboard_data` to the clipboard (browsers cannot shell out from `file://`); falls back to `document.execCommand("copy")` when the async Clipboard API is denied.
- **`tools/config-ui/style.css`** — appended Dashboard tab styles (`.dash-hero`, `.dash-panel`, `.dash-matrix`, `.dash-bar`, `.dash-empty`, `.dash-footer`, banners, responsive ≤900 px breakpoint).
- **`tools/config-ui/app.js`** — wired Dashboard tab activation to `window.DashboardRender.mount("#dashboard-root")`.
- **`templates/new-project/.gitignore.tmpl`** — added `.ai-playbook/dashboard-data.js` to the consumer-template ignore block so the sidecar never accidentally lands in consumer commits.
- **`docs/concepts/telemetry-dashboard.md`** — promoted from `draft seed (pre-BMAD)` to `spec (post-BMAD)` with the panel structure, data contract, three refresh modes, hard constraints C1–C10, and v2-candidate list ratified by the BMAD product-brief cycle.
- **`docs/runbooks/use-config-ui.md`** — appended Dashboard tab operator section (panel descriptions, refresh modes, empty state, privacy, chart-library-failed behaviour).
- **`tests/test_build_dashboard_data.py`** — new aggregator test suite: golden-shape assertions against the 5k fixture, privacy invariants, atomic-write preservation on validation failure, torn-line tolerance, SLO benchmark (< 2 s on 5 k events, < 100 KB sidecar — 4 s CI budget), empty-state branch, caveman branches (on / off / missing), JSON-schema validation. Optional UI smoke tests deferred to `tests/integration/` once Playwright is wired.
- **`tests/fixtures/telemetry-dashboard/`** — new deterministic generator (seed 42) emitting `rule-events-5k.jsonl` (5000 events over 30 days, 3 LLMs, 10 rule slugs, biased to produce cross-LLM drift), `rule-events-empty.jsonl` (42 events, below the 100 threshold), `rule-events-torn.jsonl` (250 events with the final line truncated), and `caveman-stats.json` (mode=full snapshot).

### Consumer action

- **None.** This change is additive: the sidecar appears for consumers on the next `apply_config` run; the Dashboard tab appears in the bundled UI; no rule-event schema bump.
- Air-gapped / proxy-blocked consumers will see a `chart library failed to load` banner on the Dashboard tab until the native-SVG fallback ships in a later release. Numbers still render without charts.

### Changed — untrack the dogfood `caveman.json` to kill the submodule-mount "inception" visual

- **`.ai-playbook/caveman.json`** — `git rm --cached`-ed. The playbook still dogfoods caveman locally (writes the state file at the same path on every `caveman on`); it just no longer commits it. Reason: as long as ANY file inside `.ai-playbook/` is tracked, consumers that mount this repo as a submodule see `<consumer>/.ai-playbook/.ai-playbook/<file>` in their tree, which operators read as "inception" pollution. With the file untracked the nested directory disappears entirely from consumer working trees (the playbook's own untracked-state still lives at the same local path, just not in the index).
- **`.gitignore`** — dropped the `!.ai-playbook/caveman.json` negation that previously kept the dogfood file tracked. Comment block rewritten to document the new contract: `.ai-playbook/*` blankly ignores everything; the playbook may still write state there locally for self-validation but does not version it. Existing per-pattern coverage of `caveman.json` / `backups/` / `rules-toggle.json` / etc. at the gitignore root (added in 1c45e65) remains in place — those handle consumer-side spillover when this repo is mounted as a submodule.
- **Net consumer effect:** existing consumers already mounted on a `b7f930e`-or-earlier pin see no change until they bump their submodule. After bump, the `<consumer>/.ai-playbook/.ai-playbook/` directory becomes empty (or disappears) and `git status` inside the submodule stays clean — fully matching the operator's expected "no nested anything" mental model.
- **GitHub-side trade-off:** repo viewers can no longer see "this repo dogfoods caveman with mode=full/components=…" by browsing the file on GitHub. Same signal still recoverable by reading the materialised block inside `AGENTS.md`.

### Added — bootstrap wires `ai-playbook-check` validate-only

- **`scripts/bootstrap.py`** — new step 7 in `main()` runs `python -m scripts.ai_playbook_check <target> --check` after `apply_from_config` and before the next-steps banner. Drift items (e.g. single-tree layout from `bare-layout`, missing dispatchers, gitignore-entries gaps) surface during bootstrap instead of staying invisible until the next manual `/ai-playbook-check`. New helper `run_playbook_check(target_dir, dry_run)`, new CLI flag `--no-check` (opt-out, mirrors `--no-caveman`), new `BootstrapArgs.no_check`. Closes the wiring gap left by commit `ee65e4b` (orchestrator added without touching bootstrap).
- **Behaviour contract:** validate-only — `--check` passed so the orchestrator never offers `apply`. Exit 1 (drift detected) is the expected outcome on a fresh single-tree consumer and prints quietly; exit ≥2 prints a warning but never aborts bootstrap. Migrations stay operator-driven via `/ai-playbook-check` or the runbook against each failing rule.
- **`tests/test_bootstrap.py`** — 6 new tests: invocation arguments, dry-run no-subprocess, drift-exit-no-warning, orchestrator-crash-warning, `--no-check` short-circuit, default surfacing.

### Fixed — submodule-mount hygiene (post-tag)

- **`.gitignore`** (commit `1c45e65`) — anchored 7 patterns to the repo root (`/caveman.json`, `/backups/`, `/rules-toggle.json`, `/rules-toggle-audit.jsonl`, `/feature-flags.env`, `/events.jsonl`, `/.caveman-statusline-suffix`) so consumer-side state files don't pollute submodule `git status` when this repo is mounted at `<consumer>/.ai-playbook/`. Standalone playbook checkouts unaffected.
- **`scripts/_project_root.py`** (commit `b7f930e`) — new shared helper centralising the "walk up to find AGENTS.md" project-root discovery. Skips candidates whose path segments include `.ai-playbook` or `.skills-sources` (playbook submodule mount points) so direct/manual caveman/rules-toggle invocations from inside the submodule no longer mis-resolve the project root and write nested `.ai-playbook/.ai-playbook/<state>.json` artefacts. Three call sites updated (`scripts/caveman/toggle.py`, `scripts/rules_toggle.py`, `scripts/rules/caveman-reinforce.rule.py`). Defense-in-depth — bootstrap already passes `--project` correctly so the trap fires only on manual invocations.

### Fixed — orchestrator drift false-positives (post-tag)

- **`scripts/rules/secrets-handling.rule.py`** — `validate` now invokes `scripts/secrets_scan.py --staged` by default (was previously no-arg, which triggered the scanner's "no inputs" usage banner and returned non-zero on every clean repo). Matches the rule's docstring claim ("no secrets detected in staged content"), makes the rule a no-op on a clean tree, and turns it into a real check during PR / commit hooks.
- **`scripts/rules/update-documentation.rule.py`** — the HEAD-commit-message read for the `[no-doc-impact]` escape tag now passes `encoding="utf-8", errors="replace"` so commit messages containing non-ASCII characters (em-dashes, ←/→ arrows, accented chars) no longer crash the rule with a `UnicodeDecodeError` on Windows (cp1252 default codec).

---

> **Original v0.19.6 payload below** (committed up to `1d41ee4` on 2026-05-25). VERSION file lagged at `0.19.4` while tag `v0.19.5` was cut (release-runbook drift); the original 0.19.6 release fixed the mismatch by jumping VERSION 0.19.4 → 0.19.6 and bundling everything accumulated on `main` since `v0.19.5` into a single tag.

Backwards-compatible aggregate: 20+ commits across 9 PRs, all additive (new scripts, new schemas, new docs, new tests). One consumer-facing knob change (`.claude/settings.json` matcher must include `Bash`) — see the **Consumer action** sections below.

### Added — apply-skill-enforcement L1 Bash + L3 PR-diff + telemetry v2

- **`.claude/hooks/openspec-apply-enforce.py`** — Bash interception added to `GATED_TOOLS`. The hook now reads `tool_input.command` on PreToolUse Bash events and applies a closed-set regex panel to detect explicit mutations to declared `write_paths`. Patterns cover POSIX (redirects `>` `>>`, `tee`, `sed -i`, `awk -i inplace`, `perl -i`, `python -c "open(...,'w')"`, `python -c "...write_text(...)"`, `node -e "writeFileSync(...)"`, `mv/cp dest`) and PowerShell (`Out-File`, `Set-Content`, `Add-Content`, `New-Item -ItemType File`). Conservative high-confidence-or-pass policy: ambiguous commands pass with a stderr warning; the L3 PR-diff catches everything the heuristic misses. Three additional surfaces added: (a) `AIPLAYBOOK_BASH_INSPECTION=0` env flag to disable only the Bash branch (emergency rollback), (b) per-process `_parse_write_paths` memoization keyed by file mtime to amortise tasks.md parsing cost, (c) decision-level telemetry emission via `scripts.telemetry.rule_event_logger.log_event` (rule-event/v2 schema) on every allow/block/warn/override. Error messages differentiate Bash vs Edit/Write and surface both the `OVERRIDE` and `ROLLBACK` env vars.

- **`schemas/schema-rule-event-v2.json`** — new event schema, additive over v1 (v1 file retained for reference). Adds 9 optional fields: `block_class` (enum: `none`/`apply_phase_bypass`/`outside_project`/`change_own_folder`/`flag_disabled`/`helper_missing`), `block_tool` (enum: `Edit`/`Write`/`MultiEdit`/`Bash`), `change_id`, `matched_pattern`, `target_rel` (NB: deliberately not `target_path` — the literal substring `path` is on the `scrub_event` denylist, so the field name avoids collision-by-substring if hardening of the denylist ever extends to substring matching), `bash_pattern_kind` (closed enum of 15 heuristics), `marker_present`, `override_reason`, `feature_flag`. `additionalProperties: false` preserved; future additions land as v3.

- **`scripts/telemetry/rule_event_logger.py`** — `SCHEMA_LITERAL` bumped to `"rule-event/v2"`. Existing v1 events on disk remain readable; new emissions carry the v2 literal. Logger already supported optional `extra: dict` passthrough (per v1 design); v2 simply documents the fields it expected to receive.

- **`scripts/rules/apply-skill-enforcement.rule.py`** — new `validate-pr-diff` subcommand invokable as `python -m scripts.rules.apply-skill-enforcement validate-pr-diff --base <sha> --head <sha> [--repo-root <path>]`. Computes `git diff <base>...<head>`, intersects changed paths with every active change's `## Owns (write_paths)`, and requires a `start` record in the matching `.apply_log.jsonl`. Exit 0 (clean) / 1 (violation) / 2 (schema break). Helpers `_parse_write_paths` and `_path_matches` are deliberately duplicated from the hook (sys.path injection from a PreToolUse subprocess is fragile cross-platform); equivalence to be guarded by a forthcoming `tests/test_apply_enforce_helpers_equivalence.py`.

- **`.github/workflows/apply-skill-enforcement.rule.yml`** — new L3 workflow. Runs on every PR to `main`, invokes the validator above with `fetch-depth: 0`. To be marked as a required check in branch protection (manual step; not automatable from code).

- **41 new tests** across `tests/test_apply_enforce_hook_template.py` (16 Bash + telemetry + flag cases on top of the original 10) and `tests/test_apply_skill_enforcement_rule.py` (7 fixture-based validate-pr-diff cases on a real git repo, plus the 5 existing `validate` cases). Cross-platform Bash patterns verified on Windows Git-Bash via subprocess invocation.

- **`tests/test_apply_enforce_helpers_equivalence.py`** — guards INV-5. Loads the hook template (`.tmpl`) via in-memory `compile`/`exec` into a fresh `types.ModuleType` (deliberately NOT `importlib.SourceFileLoader` — that path writes a `.pyc` sibling under `templates/.../__pycache__/` that poisons the bootstrap-template suite). 10 tasks.md fixtures + 11 (target, write_path) cases + regex-pattern byte-identity checks.

- **`tests/test_apply_log_jsonl_concurrent.py`** — guards INV-2. 10 processes × 10 rows each appending concurrently to a single `.apply_log.jsonl`; asserts JSONL well-formedness, total count, distinct rows, newline count. Confirms POSIX atomic-append semantics hold on Windows for the typical marker-helper write size.

- **`scripts/telemetry/report.py`** — three new aggregators driven by rule-event/v2 fields: `compute_block_breakdown(events, top_n=25)` groups by `(slug, block_class, block_tool, bash_pattern_kind)`, `compute_top_blocked_paths(events, top_n=10)` ranks `target_rel` by block frequency, `compute_override_ratio(events, flag_threshold=0.05)` per slug with automatic flagging when overrides exceed 5% of fires. Wired into the `Report` dataclass + `to_dict()` (JSON output) + `render_markdown` as new sections 1.bis "Block reasons breakdown", 1.ter "Top blocked paths", and 6.bis "Override ratio (per slug)" with a ⚠ flag rendered when `over_threshold=True`.

- **`.github/workflows/rule-event-report-weekly.yml`** — scheduled workflow (Mondays 09:00 UTC, plus `workflow_dispatch` with weekly/monthly/custom window). Renders both Markdown and JSON reports as artifacts; posts/updates a single tracking issue labelled `telemetry-report`. Source of events is the consumer's `.ai-playbook-state/rule-events.jsonl` (gitignored, so a fresh clone produces a "no data" report unless the consumer's own CI/aggregation pipeline populates it).

### Changed

- **`docs/rules/apply-skill-enforcement.rule.md`** — frontmatter `triggers` extended to `[Edit, Write, MultiEdit, Bash, PreToolUse]`. New sections: "Bash heuristics" (full POSIX + PowerShell pattern table), "Edge cases (FN/FP documented)" (table of inspected vs pass-through patterns with rationale for each), "Telemetry fields (rule-event/v2)" (table of every field emitted). `## Process supervision` rewritten to call out the three independent enforcers (L1 hook + L2 doc + L3 workflow) and the byte-identical helper invariant.

- **`docs/concepts/telemetry-design.md`** — Event schema section split into "Required (unchanged across v1 → v2)" + "Optional fields added in v2". New "Why `target_rel` and `matched_pattern` are not PII" subsection documents the naming decision (no literal `path` substring to remain robust against future denylist hardening). Concrete example block now includes both a minimal allow and a Bash-block decision with the enriched v2 fields.

- **`templates/new-project/.claude/settings.json.tmpl`** — `PreToolUse[*].matcher` bumped from `"Edit|Write|MultiEdit"` to `"Edit|Write|MultiEdit|Bash"`. Consumer projects bumping past v0.20.0 MUST update their own `.claude/settings.json` accordingly (the matcher is a project-local file rendered on bootstrap, not a template-managed file thereafter).

- **`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`** — byte-mirrored from `.claude/hooks/openspec-apply-enforce.py`. Tests assert byte-equivalence on each invocation.

### Added — runbooks

- **`docs/runbooks/upgrade-to-bash-enforcement.md`** — step-by-step guide for consumer projects bumping past v0.20.0. Covers: submodule bump, hook re-render, matcher update, local smoke test (`echo "x" > <write_path>` should block), rollback flag (`AIPLAYBOOK_BASH_INSPECTION=0`), full submodule revert path, telemetry verification, and L3 required-check activation in branch protection. Includes a "Common upgrade errors" table.

### Consumer action

**Required** (post-bump) for every consumer past v0.20.0:

1. Bump the `.ai-playbook` submodule.
2. Re-render `.claude/hooks/openspec-apply-enforce.py` from the template.
3. Update `.claude/settings.json` matcher to include `Bash`: `"matcher": "Edit|Write|MultiEdit|Bash"`.
4. (Optional but recommended) Activate the new L3 workflow as a required status check in GitHub branch protection on `main`.

Forgetting step 3 leaves the Bash branch uncovered (silent regression). The [upgrade-to-bash-enforcement runbook](docs/runbooks/upgrade-to-bash-enforcement.md) walks through it.

If false positives emerge from the heuristic, the rollback path is one env var: `export AIPLAYBOOK_BASH_INSPECTION=0`. This disables the Bash branch only; Edit/Write/MultiEdit remain gated. The L3 PR gate continues to enforce on merge.

### Added — rules-toggle + apply_config + HTML config UI

- **`tools/config-ui/`** — single-page HTML UI (`index.html` + `app.js` + `style.css`, vanilla JS, no build) for managing three categories of toggleables in one place: rules (~50 with paired L1/L2/L3 + optional per-rule advanced sub-toggles), features (caveman with mode + 6 components), global flags (binary env-driven toggles). On open, the UI **reads the consumer's current applied state** via `<script src="../../applied-config.js">` (a sidecar regenerated by `apply_config` — see below). When the sidecar is absent (consumer never applied), the UI falls back to `defaults.json` and the user sees the all-ON baseline. Static inventory JSONs (`rules-inventory.json` generated by `scripts.rules_toggle inventory`; `features-inventory.json` + `global-flags-inventory.json` + `defaults.json` static) are loaded via `fetch()` from the same directory. Exports a sparse `ai-playbook-config/v1` bundle JSON the user downloads with the canonical filename `applied-config.json` so it can drop straight into `<consumer>/.ai-playbook/`. file:// CORS fallback for inventories documented (`python -m http.server`); the applied-state sidecar uses `<script src>` which works even when `fetch()` from `file://` is blocked.

- **`schemas/schema-rules-toggle-v1.json`** + **`schemas/schema-ai-playbook-config-v1.json`** — two new schemas, `additionalProperties: false` throughout. The bundle schema wraps three sparse sub-sections (`rules{}`, `features{caveman}`, `global_flags{}`). Caveman's bundle representation is a declarative subset (no `schema` / `applied_at` — those are populated by the caveman CLI when it writes the actual state file).

- **`scripts/rules_toggle.py`** — CLI + state IO. Subcommands `list / status / on / off / inventory / init`. Per-rule advanced sub-toggle catalogue (e.g. `bash_inspection` for `apply-skill-enforcement`) hard-coded in the script (one rule today; will promote to YAML when the catalogue grows). State file at `<consumer>/.ai-playbook/rules-toggle.json` (sparse — rules absent are implicitly ON). Audit log at `<consumer>/.ai-playbook/rules-toggle-audit.jsonl`. Schema validation on every write. Atomic temp+rename. `status --slug X --layer L3 --exit-code` returns 0 if ON, 1 if OFF — used by the L3 workflow to skip validation when a rule is L3-disabled. `off` for a rule with declared `break_glass.env` requires `--reason >=10 chars` (persistent equivalent of the shell-scoped override contract).

- **`scripts/apply_config.py`** — bundle applier. Validates the bundle against the schema, then runs four sections best-effort: (1) **rules** writes `.ai-playbook/rules-toggle.json` (sparse) and derives env entries from any `advanced{}` sub-toggles via the rules-inventory mapping; (2) **features.caveman** subprocesses to `python -m scripts.caveman on/off ...` — never writes `caveman.json` directly (the schema literal mandates CLI delegation so AGENTS.md materialisation + backups + MCP wrap stay coherent); (3) **global_flags** writes a marker-bracketed block (`# >>> ai-playbook-config: ... >>>` / `# <<< ai-playbook-config <<<`) to `.ai-playbook/feature-flags.env` (idempotent — re-apply replaces in place, preserves user-added lines outside markers); (4) **applied-bundle** persists the just-applied bundle as `.ai-playbook/applied-config.json` (canonical source of truth for "what's live") + `.ai-playbook/applied-config.js` (a sidecar that assigns `window.APPLIED_CONFIG = <bundle>` so the HTML config UI can render the live state on next open over `file://`, where `fetch()` is blocked). One failed section never blocks the others; each section appends an audit line. Markdown report (or `--json`).

- **`scripts/bootstrap.py`** — new `--from-config PATH` flag. When present, after the base bootstrap flow (and after caveman default-on), invokes `apply_config.apply(bundle, target)`. Mutually compatible with `--no-caveman` (bundle wins on caveman state). Best-effort: section failures are surfaced but bootstrap exits 0.

- **`templates/new-project/.gitignore.tmpl`** — three new entries under a marker-bracketed block: `.ai-playbook/rules-toggle.json`, `.ai-playbook/rules-toggle-audit.jsonl`, `.ai-playbook/feature-flags.env`. Per-consumer toggle state is gitignored by design (decision: "repo virgen"); only the framework's toolkit (schemas, CLI, UI, inventories) is committed upstream.

### Changed — enforcement layers respect the toggle

- **`.claude/hooks/openspec-apply-enforce.py`** + template (byte-mirrored) — new `_is_rule_disabled(project, slug, layer)` helper with mtime-keyed cache (mirrors `_TASKS_CACHE` pattern). Check at the top of `_decide_edit` and `_decide_bash`: if the rule is OFF at L1, emit a telemetry event with `verdict=warn`, `block_class=rule_disabled`, `toggle_layer=L1`, and return 0. Duplicated from `scripts.rules_toggle.is_rule_disabled` to avoid `sys.path` injection from a PreToolUse subprocess (cross-platform fragile); equivalence guarded by `tests/test_apply_enforce_helpers_equivalence.py`.

- **`scripts/rules/_telemetry.py`** — `cli_emit` short-circuits before invoking `main_fn` if the consumer's `rules-toggle.json` declares the rule OFF at L1. Emits `verdict=warn` + `block_class=rule_disabled` + `toggle_layer=L1` and returns 0 without running the rule. Fail-safe: any IO/import error in the toggle subsystem defaults to running the rule (defensive: enforce > silent skip).

- **`.github/workflows/apply-skill-enforcement.rule.yml`** — new `Check rule toggle` step before validation. Calls `python -m scripts.rules_toggle status --slug apply-skill-enforcement --layer L3 --exit-code`; `continue-on-error: true`. The validation step is gated on `if: steps.toggle.outcome == 'success'`, so an L3-OFF rule skips its workflow with a `::notice` annotation in the GH Actions step summary.

- **`schemas/schema-rule-event-v2.json`** — additive: `rule_disabled` added to `block_class` enum (was 6 values → now 7); new optional `toggle_layer` enum (`L1` / `L2` / `L3`) for events triggered by the rules-toggle short-circuit. `additionalProperties: false` preserved.

### Added — config UI tests (+50 over baseline)

- **`tests/test_rules_toggle.py`** (21 cases) — discovery, default state, read/write roundtrip, schema rejection, `is_rule_disabled` cascade (rule absent / full disable / layer-specific / invalid layer / corrupt file), inventory generation, all CLI subcommands incl. `--exit-code` semantics for the L3 workflow gate.

- **`tests/test_apply_config.py`** (12 cases) — bundle validation (missing / invalid JSON / wrong schema), per-section apply (rules / global_flags / caveman delegation via mocked subprocess), env-block idempotency on re-apply, preservation of user-added lines outside the marker block, caveman-failure-doesn't-block-other-sections, dry-run no-op.

- **`tests/test_hook_respects_rule_disabled.py`** (4 cases) — end-to-end hook + toggle integration. Renders the template, seeds an active OpenSpec change with declared write_paths, writes a `rules-toggle.json` with the rule disabled, invokes the hook on stdin via subprocess, and asserts exit 0 + telemetry `block_class=rule_disabled`. Covers Edit/Write/MultiEdit + Bash + the L3-OFF-but-L1-ON case (must still block at L1).

- **`tests/test_config_ui_smoke.py`** (10 cases) — asset presence, HTML references, app.js fetches the right inventories, defaults validate against the bundle schema, inventory shapes match the consumed contracts (rule keys, caveman component names match `schema-caveman-toggle-v1.json`, global-flag entries carry `env_var`/`value_on`/`value_off`).

- **`tests/test_rules_telemetry.py`** — 3 new cases for the `cli_emit` toggle short-circuit (skip + warn + rule_disabled emission, normal run when rule ON, no-toggle-file fallback to baseline behavior). Existing 13 cases unchanged.

### Added — docs

- **`docs/concepts/ai-playbook-config.md`** — concept doc for the three-category surface. Three mermaid diagrams: (1) export → bundle → apply, (2) runtime layer consult, (3) `apply_config` internals. Documents the caveman delegation rationale, the "persistent toggle vs one-shot env var" decision tree, and the schema-additive contract for rule-event/v2.

- **`docs/runbooks/use-config-ui.md`** — operator walkthrough. Open the UI (incl. file:// CORS fallback) → configure across the three tabs → export → apply via bootstrap or apply_config → source the env file in shell init → verify the toggle took effect → view audit log → restore defaults. "Common errors" table covers the five most likely friction points.

### Changed — config UI direct-save + Next Steps panel

- **`tools/config-ui/app.js`** — `onExport` now uses the File System Access API (`showSaveFilePicker`) when available (Chrome 86+, Edge 86+). First export prompts the user once for the save location (`<consumer>/.ai-playbook/applied-config.json`); the resulting `FileSystemFileHandle` is persisted in IndexedDB (`ai-playbook-config-ui` db, `handles` store, key `applied-config-handle`) and reused on subsequent exports — **no dialog, file is written directly**. `queryPermission` / `requestPermission` guard each reuse; stale handles (file moved/deleted) trigger silent cleanup + a fresh prompt. Firefox/Safari (no API) keep the legacy anchor-triggered download — behaviour is detected at runtime, never hard-coded per browser. Closes the "manual mv from ~/Downloads/" friction.

- **`tools/config-ui/index.html`** — new `<aside id="next-steps">` panel revealed after every successful export. Shows: (1) for the download-fallback path only, the `Move-Item` / `mv` command to shift the file from `~/Downloads/` into `.ai-playbook/`; (2) the `python -m scripts.apply_config .ai-playbook/applied-config.json` invocation in PowerShell + POSIX form; (3) a paste-able Claude Code prompt that asks Claude to run the apply + verify the three state files were touched. Each row has a one-click Copy button (Clipboard API + `execCommand` fallback). The panel auto-scrolls into view on first reveal and is dismissable.

- **`tools/config-ui/style.css`** — styles for the Next Steps panel: green-tinted card matching the success banner, monospace command rows, tag chips for PowerShell/POSIX labels, copy-button hover states.

- **`tests/test_config_ui_smoke.py`** (+7 cases, 19 total) — assertions for: `showSaveFilePicker` + `indexedDB` + `queryPermission`/`requestPermission` references in `app.js`; `createWritable` for the direct path; `Blob` + `createObjectURL` fallback markers present alongside the modern API; Next Steps panel scaffolding (`#next-steps`, `#ns-dismiss`, `#ns-saved-info`, `#ns-move`) + the five `data-copy` targets; static `python -m scripts.apply_config` commands in PowerShell + POSIX form; Clipboard API + `execCommand` fallback wiring; `showNextSteps` switches between `"direct"` and `"download"` modes.

### Consumer action — config UI

**Optional**: existing consumers can adopt the config UI without re-bootstrap by:

1. Running `python -m scripts.rules_toggle list` from the consumer root to confirm the inventory loads.
2. Opening `<playbook-submodule>/tools/config-ui/index.html` in a browser (or `python -m http.server` from that dir).
3. Exporting a bundle and applying with `python -m scripts.apply_config <bundle>`.
4. Manually adding the three entries to the consumer's `.gitignore` if not present:
   ```
   # >>> ai-playbook-config: per-consumer toggle state >>>
   .ai-playbook/rules-toggle.json
   .ai-playbook/rules-toggle-audit.jsonl
   .ai-playbook/feature-flags.env
   # <<< ai-playbook-config <<<
   ```
5. Sourcing `.ai-playbook/feature-flags.env` in shell init (direnv `.envrc` recommended).

The UI surfaces are **opt-in**: no state file = all rules ON, caveman OFF, no env-driven flags. The pre-existing per-rule break-glass env vars continue to work for one-shot shell-scoped overrides.

### Previous Unreleased entries (continue here)

- **`scripts/mcp/render.py`** — SOPS-decrypted secrets resolution + Antigravity global config update (#94). Three new functions: `find_secrets_env(consumer_root)` probes two known siblings for `eligia-core/secrets/secrets.env`; `decrypt_sops_env(secrets_path)` shells out to `sops -d` (auto-setting `SOPS_AGE_KEY_FILE` from `~/.config/sops/age/keys.txt`) and parses the result as `KEY=VALUE`; `update_global_antigravity_mcp(merged, resolved_env, dry_run)` writes the merged MCP spec to `~/.gemini/antigravity/mcp_config.json` (when present) with CF-Access headers added for `auth: cf-access` servers and the known cf-access name prefixes (`google-workspace*`, `atlassian*`, `hindsight*`). The `run()` orchestrator wires them: SOPS file → `os.environ` fallback for `CF_ACCESS_CLIENT_{ID,SECRET}` before the Antigravity update. Dry-run preserved end-to-end. Known hardcodes documented in the PR body (sibling path, server-name heuristic, `HINDSIGHT_BANK_ID` "geeplo" fallback) — pragmatic, grep-and-fix later.

- **`scripts/bootstrap.py`** + **`scripts/auto_managed.py`** + **`AGENTS.md`** + **playbook self** — caveman default-on for new projects (#95). Bootstrap now activates caveman as step 4.6 (post-templates, pre-mcp-render) with `mode=full` and all six components, so the `mcp_shrink` post-render hook wraps `.mcp.json` + `.gemini/settings.json` on the first pass. Opt out with `--no-caveman`; existing consumers flip it manually with `python -m scripts.caveman on`. The playbook itself dogfoods caveman: `.ai-playbook/caveman.json` toggle is committed (gitignore exception added so only the toggle is tracked, not `notifications.jsonl` / `overrides.log` / `backups/`), and `AGENTS.md` carries the materialised `caveman/ruleset:full` block. `scripts/auto_managed.py` grew a special-case for `caveman/ruleset:<mode>` that delegates to `materialise.render_block_content` — byte-identical to `caveman on` by construction. 4 new bootstrap tests covering default-on invocation, `--no-caveman` opt-out, dry-run no-op, and best-effort failure handling. Runbook updated with the default-on policy + opt-out path.

### Added — agent telemetry pipeline (OTel + Langfuse)

- **`scripts/tracing/`** (new package) + **`scripts/tracing/README.md`** — OTel tracing pipeline scaffold. `otel_setup.py::init_tracing()` initialises an explicit `TracerProvider` and passes it to `Langfuse(tracer_provider=provider)` directly (instead of relying on the SDK fetching whatever happens to be installed as the process-global TracerProvider) — robust to other libraries mutating the global tracer-provider state after init. Dual-export remains intact (Langfuse Cloud + OTLP collector). `trace_emit.span(name, attrs)` exposes a no-op-safe context manager that yields a real span when OTel is initialised and a `nullcontext(None)` otherwise. Kill switch via `AI_PLAYBOOK_DISABLE_TRACING=1`. (#85)

- **`scripts/_llm.py`** + **`scripts/hook_dispatcher.py`** + **`scripts/hindsight.py`** + **`scripts/notify.py`** + **`scripts/release_cut.py`** — instrumentation of the playbook's load-bearing call sites (#86). Every LLM gateway call, hook dispatch, hindsight retain/recall, notification emission, and release-cut step now opens a `langfuse-shaped` span with `ai_playbook.*` attributes so the same operations that populate the local JSONL log also surface in Langfuse / any OTLP backend in real time. Per-component `latency_ms`, `outcome`, `slug` / `route` / `kind` attributes preserved; raw payloads sanitised through `scripts/secrets_scan.py` before attachment. New test files: `test_hook_latency.py` (64 lines), `test_llm_helper.py` (110 lines), `test_notify.py` (61 lines), `test_release_cut.py` (80 lines).

- **`scripts/rules/_telemetry.py`** — `cli_emit` now wraps `main_fn` execution in an OTel span (`rule.<slug>`) alongside the existing JSONL row (#85). Span attributes (`ai_playbook.rule.{slug,trigger,llm,verdict,latency_ms}`) populate so the same rule fires that already write to `.ai-playbook-state/rule-events.jsonl` also show up in real-time observability UIs. Both transports remain independently fail-safe — an exception in either path never alters the rule's exit code and never blocks the other. 4 new tests cover span attribute population for every verdict + the cross-transport invariant when OTel blows up. Docstring rewrote to describe the dual-transport contract.

### Added — script_emit + count direct-CLI invocations

- **`scripts/rules/_telemetry.py`** — `cli_emit` gains a `kind="rule"|"script"` parameter (#87, backward-compat default `rule` so the 41 existing `*.rule.py` callers keep working unchanged). New `script_emit(slug, main_fn, argv=None)` alias sets `kind="script"` for readability at call sites. 13 direct-CLI scripts that previously had no execution counter are now wrapped: `doctor`, `bootstrap`, `secrets-scan`, `verify-llm-routing`, `openspec-validate`, `gen-indexes`, `validate-pairing`, `verdict-lint`, `schema-validate`, `inject-context`, `upstream-sync`, `simulate-incident-response`, `discover-projects`. Each wrap is a 2-line change to the script's `if __name__ == "__main__":` block. Every invocation now appends a row to `.ai-playbook-state/rule-events.jsonl` with `kind="script"`.

- **`scripts/telemetry/report.py`** — `compute_obey_rate()` carries `kind` through to output rows (legacy rows without the field default to `rule`). New `compute_invocations_by_kind()` for the top-level rule/script split. Markdown table gains a `kind` column.

- **`schemas/schema-rule-event-v2.json`** — additive: `kind` enum (`rule` / `script`) added as optional property. `additionalProperties: false` preserved.

- **`docs/concepts/telemetry-design.md`** — Optional v2 fields table extended with `kind`. The dual-transport section (JSONL + OTel span) documents the cross-link to `scripts/tracing/README.md`.

- **`tests/test_rules_telemetry.py`** — 5 new cases: `kind="rule"` default, `kind="script"` explicit, `script_emit` is alias for `kind="script"`, `argv` threading, fail-safe on logger error.

### Added — docs visuals (15 Mermaid diagrams + cleanup)

- **9 docs gained Mermaid diagrams** (#97), color-coded per the `enforcement-layers.md` convention (green=L1/OK, orange=L2/gate, blue=L3/decision, purple=axis3, red=fail):
  - `docs/concepts/development-flow.md` — 4 diagrams: four-level hierarchy (ROADMAP→PHASE→CHANGE→BRANCH→COMMITS→PR→MAIN→TAG→CONSUMERS), three axes of parallelism decision tree, OpenSpec change path, release path.
  - `docs/concepts/dispatcher-chain.md` — 2 diagrams: resolution pipeline (Router→AGENTS.md→Specs→Personal add-on), override-precedence flow with `OVERRIDE: none` guards.
  - `docs/concepts/memory-hierarchy.md` — 2 diagrams: 4-tier hierarchy (Volatile/Persistent subgraphs), decay-policy conflict-resolution flow.
  - `docs/concepts/incident-response.md` — 2 diagrams: incident lifecycle (trigger→severity classify S1/S2/S3/S4→action→mitigated→resolved→post-mortem), on-call rotation `stateDiagram-v2` (Solo→Family-of-3→Team-of-N with `oncall_eligible` count triggers).
  - `docs/concepts/git-worktree-bare-layout.md` — 1 diagram: `.bare/` shared-objects-DB visualization (ASCII preserved alongside for grep-ability).
  - `docs/runbooks/release.md` — 1 diagram: semver decision tree + rc-first variant + full release sequence with zombie gate + smoke test.
  - `docs/runbooks/onboard-new-project.md` — 1 diagram: 11-step bootstrap dependency graph with Profile A (OSS+CodeRabbit+branch protection) vs Profile B (private, convention-based) branching.
  - `docs/tutorials/02-start-here.md` — 1 diagram: 3-level dispatcher chain (replaces ASCII boxes for better GitHub/mkdocs render).
  - `docs/tutorials/01-architecture-tour.md` — 1 diagram: four doc types with discriminators (rules `paired_hardrule:` vs concepts) + cross-references.

- **Legacy doc cleanup** (#97):
  - `docs/concepts/v080-roadmap.md` deleted — roadmap closed, items shipped or promoted to `v090-roadmap.md`. References cleaned in `mkdocs.yml`, `docs/concepts/v090-roadmap.md`, and a stale `skills/openspec-archive-change/SKILL.md` pointer.
  - `INDEX.md` regenerated via `scripts/gen_indexes.py`.

### Added — UX track author self-render + self-audit

- **`docs/concepts/ux-track.md`** §17 + new §17.1 (#98) — mandates author self-render and self-audit before requesting human review. Adds step 2 to §17 QA discipline (renumbers existing 2→3, 3→4). New §17.1 sub-section with: 11-point visible-failure checklist (clipped CTAs, overflowing text, broken kerning/fallback fonts, mis-sized grids, invisible bar fills, sticky overlaps, mis-aligned decorations, mock-content leaking, duplicate headers, dark-mode regressions), screenshot-as-evidence requirement (`docs/ux/_review-screenshots-YYYY-MM-DD/`), tooling notes (Playwright / Puppeteer / headless Chrome — must be a real browser engine, not static-HTML-to-image converters). Trigger event: 2026-05-13 review of M3 mocks j6-j12 (consumer-c-legacy) found multiple bugs an LLM author would have caught with one render-and-look pass.

## [0.19.5] — 2026-05-25 — Worktree retirement helpers (`wt_remove` + `wt_sweep`)

Closes the missing half of the worktree lifecycle introduced in earlier
versions: `scripts/wt_add.py` created `slice/<change-id>` branches but had
no companion helper to retire them after the PR was merged or closed.
Consumer projects accumulated "zombie" local branches because:

1. `git worktree remove` does NOT delete the underlying branch.
2. Squash-merge creates a new commit on main; the original slice tip is not
   reachable from main, so `git branch --merged` cannot detect it.

Discovered while cleaning up after a geeplo hotfix (`GPLO-1027`) — the
project had accumulated 33 zombie local `slice/*` branches, only 1 of which
corresponded to an open PR. This release codifies the cleanup logic.

Backwards-compatible. `wt_add.py` keeps the same interface (only an
informational hint added to successful output). Consumers see no breakage;
the new helpers are purely additive.

### Added

- **`scripts/wt_remove.py`** — single-target retirement of a worktree + its
  `slice/<change-id>` branch. Verifies the PR state via
  `gh pr list --head slice/<change-id>` before doing anything and refuses
  to proceed if the PR is still OPEN (override with `--force`). Then runs
  `git worktree remove --force` (the `--force` covers submodule directories
  git's bookkeeping does not track), wipes residue that survives, and
  finally `git branch -D slice/<change-id>` (unless `--keep-branch` is
  passed). Other flags: `--dry-run`, `--repo-root`, `--branch-prefix`.

- **`scripts/wt_sweep.py`** — bulk maintenance for projects that have
  accumulated drift (many merged/closed PRs whose `slice/*` branches were
  never retired). Enumerates every local branch matching `--branch-prefix`
  (default `slice/`), queries `gh pr list --head <branch>` for each,
  classifies as `MERGED` / `CLOSED` / `OPEN` / no PR found, and prints a
  deletion plan. Default is dry-run; `--apply` executes; `--remote`
  additionally `git push --delete origin <branch>` (useful when the repo
  lacks `delete_branch_on_merge=true`); `--include-worktrees` retires
  dangling worktrees too.

- **27 tests** (`tests/test_wt_remove.py` + `tests/test_wt_sweep.py`).
  Subprocess + filesystem are stubbed; covers PR-state gating, `--force`,
  `--keep-branch`, `--dry-run`, `--include-worktrees`, `--remote`, and the
  `BranchEntry` classification logic.

### Changed

- **`scripts/wt_add.py`** — on successful worktree creation, prints a
  follow-up hint pointing at `wt_remove.py` so the user discovers the
  retirement step without having to read docs.

- **`docs/concepts/git-worktree-bare-layout.md`** — Tooling section now
  documents `wt_remove.py` and `wt_sweep.py` alongside `wt_add.py`, and
  recommends enabling GitHub's "Automatically delete head branches" at the
  repo level to eliminate remote zombies at source.

- **`docs/runbooks/git-worktree-bare-setup.md`** §4.2 rewritten around the
  `wt_remove.py` invocation; new §4.3 added covering `wt_sweep.py` for bulk
  cleanup. Manual `git worktree remove + git branch -D` remains documented
  as the equivalent for users who prefer not to use the helper.

### Consumer action

Optional but recommended: bump the `inherits_from` pin in your
project-level `AGENTS.md` to `@v0.19.5` and refresh the `.ai-playbook`
submodule to consume the new scripts. There is no breaking change — the
old helpers continue to work as before.

## [0.19.4] — 2026-05-20 — Windows UTF-8 stdout + dispatcher-cursor sibling warning

Two follow-ups surfaced while dogfooding v0.19.3's orchestrator against a
Windows consumer (geeplo). Both backwards-compatible; no consumer action
required beyond the submodule bump.

### Fixed

- **`scripts/rules/_telemetry.py`** — every `.rule.py` entry point now
  reconfigures `sys.stdout` and `sys.stderr` to UTF-8 (`errors="replace"`)
  before the rule's `main()` runs. Before: any rule emitting `→`, `❌`,
  `ℹ`, etc. crashed with `UnicodeEncodeError` on Windows (cp1252 default).
  Hit on `bare-layout.rule.py apply --dry-run`. The reconfigure is wrapped
  in `try/except` so streams that don't expose `.reconfigure` (pytest
  capsys, in-memory captures) are tolerated silently. Fixes the gap not
  covered by v0.19.3's subprocess-layer fix in `ai_playbook_check.py`.

### Added

- **`scripts/rules/dispatcher-cursor.rule.py`** — `apply` now warns (rc=0,
  stderr) when other `.cursor/rules/*.mdc` files reference `AGENTS.md`.
  Those are likely redundant routers from before this rule existed; the
  operator should review and delete duplicates so Cursor loads only the
  canonical `00-AGENTS.mdc`. Warning is emitted on every non-error outcome
  (canonical-already / dry-run / fresh-write).

## [0.19.3] — 2026-05-20 — ai-playbook-check L4 advisor + 10 new rules + `.rule.py apply` contract

Adds the missing cross-cutting **L4 advisor** layer on top of the existing
L1/L2/L3 enforcement model. Backwards-compatible: the new `.rule.py apply`
subcommand is purely additive; `validate` stays the baseline contract and
no existing CLI flag, env var, or event-schema field changes. Consumers
that don't invoke the orchestrator see no behavioural difference.

### Added

- **`scripts/ai_playbook_check.py`** — single orchestrator that loads every
  `docs/rules/<slug>.rule.md` via `hook_dispatcher.load_rules()`, runs each
  paired `validate` against the consumer cwd, and reports a unified drift
  table (text or `--json`). Detects `apply` support via subprocess
  introspection. Offers opt-in remediation through `AskUserQuestion`-style
  interactive multi-select. Never blocks — exit 0 by default; opt-in
  `--exit-on-drift` flag for consumer CI gates. Other flags: `--check`,
  `--yes`, `--select`, `--skip`, `--upgrade-only`. Cross-platform (Windows
  cp1252 ↔ UTF-8 reconfiguration handled in `main()` + every subprocess call).
- **`.rule.py apply` contract** — documented end-to-end in
  `docs/concepts/enforcement-layers.md` §"Rule .rule.py contract".
  Additive: rules MAY implement `apply` + `apply --dry-run` for opt-in
  remediation. Required invariants: idempotency, reversibility,
  refuse-overwrite-custom, dry-run parity, no partial mutations on failure.
  Disambiguated from `apply-fix-contract` (HITL workflow mutations) in
  the doc's "See also".
- **10 new rules** (each L1 + L2 + tests paired):
  - `bare-layout` — detects bare-repo + per-branch-worktree vs legacy
    single-tree clone. `apply` is **plan-only** — prints the migration
    procedure from runbook §3 but never executes (high blast radius).
    `status: warn` (informational).
  - `mcp-render` — mtime-based detection of `.mcp.json` /
    `.gemini/settings.json` staleness vs `mcp-servers.yaml` SSOT.
    `apply` delegates to existing `scripts/mcp/render.py`.
  - `registry-entry` — consumer presence in
    `~/.ai-playbook/projects.yaml`. `apply` invokes `discover_projects.py`.
  - `dispatcher-gemini` — `GEMINI.md` pointer to AGENTS.md exists,
    ≤30 content lines. `apply` writes canonical pointer when missing;
    refuse-overwrite-custom.
  - `dispatcher-cursor` — `.cursor/rules/00-AGENTS.mdc` pointer to
    AGENTS.md (Cursor `alwaysApply: true` frontmatter). Same
    refuse-overwrite-custom semantics as dispatcher-gemini.
  - `claude-settings` — `.claude/settings.json` declares the required
    PreToolUse `openspec-apply-enforce.py` hook. `apply` deep-merges the
    canonical hook block preserving existing user customisations.
  - `pre-commit-hooks` — `.pre-commit-config.yaml` references the
    playbook hooks bundle. `apply` appends a canonical block (idempotent
    by substring check; preserves comments + formatting via line-append
    rather than YAML rewrite).
  - `skills-sync` — `.claude/skills/` reflects playbook skill registry.
    `apply` invokes `materialise_skills.py` when available.
  - `gitignore-entries` — required ai-playbook-managed entries present
    in `.gitignore`. `apply` appends missing entries under a marker
    comment header.
  - `openspec-scaffold` — `openspec/changes/` + `openspec/specs/`
    directories exist when openspec is in use. `apply` mkdirs missing
    subdirs (idempotent).
- **3 existing rules extended with `apply`**:
  - `install-playbook.apply` — plan-only (prints the `git submodule add`
    + checkout + commit sequence; operator runs it manually).
  - `bootstrap-directive.apply` — real mutator. Inserts the canonical
    §0 block into an AGENTS.md that's missing it (preserves YAML
    frontmatter + H1). Refuses to overwrite a §0 that exists but is
    non-canonical.
  - `update-playbook.apply` — plan-only (prints the submodule bump
    sequence with current pin → latest tag).
- **`/ai-playbook-check` skill** at `skills/ai-playbook-check/SKILL.md`.
  Wraps the orchestrator with interactive `AskUserQuestion` multi-select
  for drift remediation. Syncs to consumer `.claude/skills/` via the
  existing materialise mechanism.
- **`docs/concepts/enforcement-layers.md`** — new section "Rule
  `.rule.py` contract" documenting the additive `apply` semantics
  (invariants, what apply MUST satisfy, what it MUST NOT do, invocation
  contexts, relationship to `apply-fix-contract`).
- **`AGENTS.md` §9 Rule Map** — 10 new slugs added under "Enforced"
  group. The rule corpus grows from 39 to 49 rules.

### Carried forward from `[Unreleased]` (pre-v0.19.2 staging)

- **Opportunistic queue drain** — `scripts/retain_memory.py` and
  `scripts/inject_context.py` now drain `<consumer>/.ai-playbook/hindsight-queue.jsonl`
  automatically after any code path that has just proven Hindsight reachable
  for the relevant bank (a successful `POST /retain` or a successful `POST /recall`
  during the `SessionStart` hook). No daemon, no scheduler — the drain piggybacks
  on existing call sites. Failure during drain is logged at WARNING level (the
  primary action is never blocked, but ops gets a signal). New helper:
  `retain_memory.try_opportunistic_drain(consumer_root, bank)` — wraps the
  existing `_drain_queue` in `try/except Exception`, logs via
  `_logger.warning(...)`, and returns `(0, 0)` on any failure. Stderr notices:
  `📤 opportunistically drained N …` (retain path) and
  `📤 SessionStart drain: replayed N …` (recall path).
- **Atomic queue rewrite** — `_drain_queue` now rewrites the queue via a
  sibling `.tmp` + `Path.replace()` (atomic on POSIX and NTFS), eliminating
  the Windows `ERROR_SHARING_VIOLATION` race when retain_memory.main() is
  mid-rewrite and a SessionStart drain fires concurrently.
- **Visibility logs** — `scripts/rules/_telemetry.py::cli_emit` and
  `scripts/mcp/validate.py::resolve_personal_file` no longer fail silently:
  the former emits a WARNING when the rule-event logger drops an event,
  the latter emits a WARNING listing the three searched paths when no
  personal-layer file is found.
- **Docs**: `docs/concepts/degradation-modes.md` §8 "Reconciling
  `DEGRADED_CONTEXT` writes" + `docs/runbooks/hindsight-retain.md`
  Troubleshooting block updated to describe the new auto-drain behaviour and
  the manual `--replay-queue` flag as the escape hatch.

### Changed

- **`scripts/gen_indexes.py`** — fixed two long-standing defects in the
  auto-generated `INDEX.md` tables: (1) the `Status` column has been dropped
  because no `.md` file in the playbook uses the `> **Status**:` blockquote
  convention it sourced from (the column was uniformly `—` everywhere); (2)
  `Summary` now prefers a curated YAML frontmatter field (`summary:` for
  concept docs, `description:` for rules / runbooks / tutorials) and only
  falls back to the first body paragraph when neither is present. Truncation
  raised from 100 → 200 chars so curated summaries can breathe. The four
  `docs/{concepts,rules,runbooks,tutorials}/INDEX.md` files have been
  regenerated. The CI `--check` mode still asserts idempotency, so consumers
  pinning future versions must regenerate their own indexes if they keep
  local copies. Test contract updated (3 status-related tests removed; 4
  frontmatter-related tests added).

### Migration

Consumers absorbing v0.19.3 see zero behavioural change to existing flows.
The new orchestrator is opt-in — invoke `python .ai-playbook/scripts/ai_playbook_check.py --check`
to surface drift, or use the new `/ai-playbook-check` skill in a Claude Code
session. The orchestrator is also useful for first-run audits when bumping
to v0.19.3: it reports any pre-existing drift that the previously-invisible
rules now surface (dispatcher routers missing, `.gitignore` entries
incomplete, etc.).

## [0.19.2] — 2026-05-19 — MCP tenant-specific decoupling (post-flip cleanup)

Fixes two latent issues from the v0.18.x public-flip that surfaced when
bumping a real consumer (geeplo) to v0.19.x:

### Changed

- **`templates/rendered/mcp-servers-base.yaml.tmpl`**: removed the `rag`
  server entry. Its `command: "python -m consumer-d.rag"` was a redacted
  literal that never matched any real consumer install. The base layer is
  now reserved for servers whose every field is parametric; tenant-specific
  `command` / `endpoint` values belong in the project or personal layer.
- **`scripts/mcp/validate.py::resolve_personal_file()`**: removed the
  legacy `~/Projects/consumer-d/mcp-servers.yaml` + `C:/Projects/consumer-d/
  mcp-servers.yaml` fallback paths. They were a pre-flip maintainer
  convenience that only resolved against a redacted name no longer matching
  any real local checkout. The resolver now walks: explicit `--personal-file`
  arg → `$AIPLAYBOOK_PERSONAL_MCP_FILE` → `~/.config/mcp-servers.yaml`.
  Maintainers whose personal layer lives elsewhere must export the env var
  in their shell profile.
- **`docs/concepts/mcp-servers-schema.md`** §3.1 "Tenant-specific servers"
  added — documents the rule that any server whose `command` or `endpoint`
  carries a tenant-specific literal belongs in the project or personal
  layer, never in `base`.

### Migration

- **Consumers that relied on the `rag` server**: add the entry to your own
  `mcp-servers.project.yaml` with the actual command for your stack, e.g.
  `command: "python -m myorg.rag"`.
- **Maintainers whose personal layer lives in a non-XDG location** (e.g.
  `C:/Projects/<your-real-stack>/mcp-servers.yaml`): set
  `AIPLAYBOOK_PERSONAL_MCP_FILE=<absolute-path>` in your shell profile.
  Otherwise the personal layer will be silently skipped.

## [0.19.1] — 2026-05-19 — telemetry wiring + retroactive v0.18.0 + archive cleanup + mkdocs nav

Closes the four secondary audit items called out in CHANGELOG v0.18.3
"Known gaps". Non-breaking.

### Added

- **Retroactive `v0.18.0` tag** at SHA `d612350` (Slice 4 merge — where
  `VERSION` first read `0.18.0`). The tag was missed at the time;
  re-issuing it preserves an honest history.
- **`scripts/rules/_telemetry.py`** — thin CLI wrapper exposing
  `cli_emit(slug, main_fn, argv=None)`. Times the rule script's `main()`
  call, maps the exit code to a `rule-event/v1` verdict
  (`0=allow`, `1=block`, `>=2=warn`), and forwards to
  `scripts.telemetry.rule_event_logger.log_event`. Fail-safe — any
  logger exception is swallowed; the rule's rc is never altered by
  telemetry side-effects. Reads `AI_PLAYBOOK_LLM`,
  `AI_PLAYBOOK_HOOK_TRIGGER`, `CLAUDE_CODE_SESSION_ID` env vars to
  enrich events.
- **`tests/test_rules_telemetry.py`** — 9 tests covering the verdict
  mapping, rc passthrough, JSONL write, fail-safe behaviour, and argv
  handling.
- **`openspec/changes/archive/`** — new directory; the 20 already-shipped
  slice proposals (`add-cleanup-zombies-hook` through `v019-pull-model`)
  moved here. `openspec list` no longer surfaces them as in-progress.

### Changed

- **29 rule scripts re-wired** — every `scripts/rules/<slug>.rule.py`
  bottom block replaced from `raise SystemExit(main())` (or
  `sys.exit(main())`) to:

      if __name__ == "__main__":
          from scripts.rules._telemetry import cli_emit
          raise SystemExit(cli_emit("<slug>", main))

  This is a CLI-surface-preserving change — rule scripts still accept
  the same arguments and exit with the same codes. Telemetry collection
  is now ACTIVE: every L1 hook invocation (pre-commit, PreToolUse,
  manual `python scripts/rules/<slug>.rule.py validate`) appends a
  JSONL row to `<consumer>/.ai-playbook-state/rule-events.jsonl`.
- **`mkdocs.yml` nav** rebuilt for completeness. Every doc under
  `docs/{tutorials,concepts,rules,runbooks}/` (excluding the
  auto-generated `INDEX.md` per category) appears under its section's
  nav. Curated head order is preserved for the high-priority entries
  (verdict-contract, enforcement-layers, etc.); the long tail is
  alphabetical. `mkdocs build --strict` passes.

### Notes

- The 9 `docs/rules/*.rule.md` files without a matching `.rule.py`
  (`apply-fix-contract`, `conflict-resolution-policy`, `data-handling`,
  `hitl-approval-pattern`, `notification-channel-adapter`,
  `notification-level-declared`, `notification-no-secrets`,
  `parallel-wave-anti-collision`, `slice-preflight`) are intentional
  advisory-only rules. They have no L1 hook and therefore no
  telemetry event. The validate-pairing CI workflow already accepts
  this via the pairing-exception condition #3 ("consumer-side surface").
- The propagate-playbook-bump CI workflow is gone since v0.19.0, so
  this release tag's CI surface is just `test` + `docs-deploy`. No
  per-consumer PRs are opened.

## [0.19.0] — 2026-05-19 — pull-model migration (BREAKING) — push pipeline retired

First post-review fix iteration after the v0.18.x architectural reset.
Eliminates the centralised push-bump pipeline and the org-wide `consumers.yaml`
registry; each downstream consumer now manages its own bump cadence and
tracker configuration in its own AGENTS.md frontmatter.

### BREAKING

- **`.github/workflows/propagate-playbook-bump.yml` deleted.** The playbook
  no longer pushes bump PRs across consumers on tag release. Each consumer
  must adopt a pull mechanism: Dependabot/Renovate submodule-update rule, a
  scheduled GitHub Action, or manual `cd .ai-playbook && git fetch && git
  checkout vX.Y.Z`. See README "Consumers: how to bump" + runbook `release.md`.
- **`scripts/propagate_bump.py` deleted.** CI-side propagation script.
- **`consumers.yaml.example` deleted.** No more central registry of consumers
  in the playbook. Existing `consumers.yaml` files on dev machines become
  orphan local-only data with no automation reading them.
- **`docs/runbooks/propagate-bump-troubleshooting.md` deleted.** Diagnosed
  failures of the retired workflow.
- **`docs/runbooks/skills-version-bump.md` deleted.** Described the sibling
  `propagate-skills-bump.yml` workflow that was already retired in v0.17.0.
  The playbook tag itself now covers skill changes (skills are vendored at
  `skills/` inside the playbook repo since v0.17.0).
- **`scripts/issue_sync.py` reads `tracker_kind` from AGENTS.md frontmatter,
  not from `consumers.yaml`.** Consumers who used `tracker_kind` /
  `jira_project` in `consumers.yaml` must move those keys into their own
  `AGENTS.md` frontmatter. `templates/new-project/AGENTS.md.tmpl` updated
  to include the new fields with `tracker_kind: github` as a safe default.

### Removed

- `tests/test_propagate_bump.py`, `tests/test_consumers_yaml.py` (tests
  covered the deleted scripts/files).
- `TestPropagateCrossRef` (the `propagate_bump.ensure_dev_flow_cross_ref`
  test suite inside `tests/test_dev_flow_industrialization.py`). The
  cross-ref migration completed across every consumer before the push
  pipeline retired; the schema validator (Opción 2) is the surviving
  guarantee.
- `_REGISTRY_CACHE`, `_registry_path`, `_load_registry`,
  `_reset_registry_cache`, `_registry_entry` from `scripts/issue_sync.py`.

### Changed

- `scripts/init_org.py` no longer resets a `consumers.yaml` stub in forks.
  Playbook-root detection switched from `templates/rendered/...tmpl +
  consumers.yaml` to `templates/rendered/...tmpl + AGENTS.md`.
- `docs/runbooks/release.md` rewritten for the pull contract: cut tag →
  GitHub auto-creates release → consumers absorb at their own pace.
- `docs/runbooks/onboard-new-project.md` drops the consumers.yaml
  registration step; documents the optional Dependabot config for
  automated bump PRs.
- `docs/runbooks/rotate-secrets.md` removes section A (PAT rotation for
  the retired `PLAYBOOK_PROPAGATION_TOKEN`) and renumbers the remaining
  sections.
- `docs/concepts/issue-tracking.md` §4 reflects the AGENTS.md-frontmatter
  source for `tracker_kind` / `jira_project`.
- `docs/concepts/release-management.md` §3.4 + §4.5.5 + §6.7 references
  rewritten — supersede semantics still apply *within* each consumer's
  own CI, but the playbook no longer ships the bot.
- `docs/concepts/development-flow.md` ASCII diagrams in §1 + §3 updated
  to the pull-model lifecycle.
- `docs/concepts/enforcement-status.md`, `docs/concepts/skills-distribution.md`,
  `docs/concepts/rule-use-cases-matrix.md`, `docs/concepts/root-folder-audit.md`,
  `docs/rules/update-playbook.rule.md` — surface references corrected or
  annotated `RETIRED v0.19.0`.

### Migration notes for existing forks / consumers

1. **Forks of the playbook**: delete any local `consumers.yaml` you maintain.
   Remove the `PLAYBOOK_PROPAGATION_TOKEN` secret from your fork's repo
   secrets (it has write access to consumer repos and is no longer used).
   Revoke the underlying PAT on GitHub.
2. **Consumer repos that used `consumers.yaml` for `tracker_kind`**: add
   `tracker_kind: github` (or `tracker_kind: jira` + `jira_project: PROJ`)
   to your own `AGENTS.md` frontmatter. `scripts/issue_sync.py` will now
   read it from there.
3. **Consumer repos that want automated bump PRs**: add a Dependabot or
   Renovate config — see README "Consumers: how to bump" for the canonical
   Dependabot snippet.

## [0.18.3] — 2026-05-19 — Slice 7 polish for showcase + 10 remaining hardrules

Closes the v0.18.x architectural reset arc. Slice 4 reorganised the filesystem;
Slice 5 rewrote the doc content; Slice 6 instrumented the playbook with
telemetry and retired 14 of 24 deferred hardrules; Slice 7 (this entry) ships
the public-facing polish — a Mermaid-rich README, Mermaid diagrams in the
enforcement-layers concept doc, a new academic-foundations reference doc, a
Pagefind-aware mkdocs build, a per-rule use-cases matrix, and a polish pass
on the 15-minute architecture tour — and retires the remaining 10 deferred
hardrules (5 full implementations + 5 advisory downgrades into a new
"consumer-side surface" pairing-exception condition).

This is the **LAST** slice of the v0.18.x architectural reset arc. Per
user-refined versioning 2026-05-19, the next gate is a user review pause;
fix iterations ship as v0.19.x; v0.20.0 final cut on explicit user OK.

### Why now

The v0.20.0 "world reference" milestone needs a polished GitHub surface
before any external eye looks at it. Slices 1–6 built the architecture;
Slice 7 makes it presentable. The README is the first 30 seconds; the
enforcement-layers diagrams are the visual anchor for the L1/L2/L3 model;
the academic-foundations doc grounds every design decision in a citable
source. The remaining 10 deferred hardrules close the strict-mode pairing
gate so the validator exits 0 with no allowlist.

### Added — 6 sub-deliverables

- **7.A — `README.md` rewrite** (208 lines). Hero paragraph naming the
  Diátaxis-inspired layout and the L1/L2/L3 paired-enforcement architecture;
  Mermaid flow diagram of the three layers with one paired example
  (`cleanup-zombies`); 60-second quickstart (`clone → pip install -e . → run
  validators → pytest`); explicit scope table (Claude / Gemini / Cursor
  supported; Copilot / Codex / Aider / Continue / Windsurf out of scope for
  v0.20.0); doc map pointing at the four Diátaxis-inspired folders + the
  new academic-foundations + rule-use-cases-matrix docs; six GitHub Actions
  status badges (test / validate-pairing / check-link-integrity /
  check-doc-language / check-rule-schemas / docs-deploy).
- **7.B — `docs/concepts/enforcement-layers.md`** rewritten with three
  Mermaid diagrams: (1) the L1/L2/L3 flow from tool call to PR merge; (2)
  the paired-enforcement same-rubric-three-enforcers protocol with the
  D8 tie-break arrow; (3) the cross-LLM degradation matrix
  (Claude/Cursor/Gemini).
- **7.C — `docs/concepts/academic-foundations.md`** (new, 13 citations).
  Stable URLs/DOIs for: Constitutional AI (Bai 2022), PRM800K
  (Cobbe 2023), IFEval (Zhou 2023), IFEval-Robust (2024), length-vs-
  compliance, OWASP LLM Top 10, ChatInject (2024), Diátaxis (Procida),
  AGENTS.md spec, Cursor `.mdc` spec, IBM Neuro-Symbolic AI, OpenTelemetry
  GenAI semconv, LLM rule compliance under prompt injection
  (arXiv 2310.13361). Each entry maps to a D-numbered architectural
  decision in the plan.
- **7.D — `mkdocs.yml` polish + Pagefind**. Refreshed `mkdocs-material`
  theme (light/dark palette toggle, tabs / expand / suggest / highlight /
  share features, Mermaid superfences). Navigation hierarchy now matches
  the Diátaxis-inspired layout: Tutorials → Concepts → Rules → Runbooks →
  Telemetry. `validation:` block softens cross-tree link warnings (many
  docs intentionally cite `scripts/`, `schemas/`, `.github/`) so `--strict`
  exits 0. New `scripts/build_docs.sh` one-shot helper runs
  `mkdocs build --strict && npx pagefind --site site`. New
  `docs/runbooks/docs-build-deploy.md` runbook documents both the local
  and the deploy paths.
- **7.E — `docs/concepts/rule-use-cases-matrix.md`** (new). One row per
  rule under `docs/rules/` (38 rows). Columns: slug (linked to the rule
  doc), status (enforced / warn / advisory), L1 trigger (first sentence
  of the rule's `## Trigger` section), L2 binding clause (verb extracted
  from the RFC 2119 imperative), L3 workflow (dedicated file or shared
  `check-rule-schemas.rule.yml`), live obey-rate (placeholder `—` with
  footnote "first real data lands v0.18.3 + 1 week of consumer adoption").
- **7.F — `docs/tutorials/01-architecture-tour.md`** polish pass.
  Refreshed test count (~1080 expected post-slice-7), added a "What you
  can build next" section with 5 concrete next-steps (modify a rule and
  watch CI catch you / generate a telemetry report on your own session /
  add a concept doc / wire a Cursor mirror / add a smoke test). Length:
  235 lines (under the 350 cap).

### Added — 5 full hardrules (closing the deferred set)

- `scripts/rules/alembic-migration-naming.rule.py` — AST extracts
  `revision = "..."` literal; rejects bare-integer revisions and
  revision/filename drift.
- `scripts/rules/cross-slice-additive-extension.rule.py` — regex on
  Alembic migration source; rejects `ALTER TABLE ... ADD COLUMN ...
  NOT NULL` without `DEFAULT` (the Shape-B sentinel safeguard).
- `scripts/rules/migration-slot-reservation.rule.py` — walks a migrations
  directory; rejects duplicate `<NNNN>_` integer prefixes (slot
  collisions).
- `scripts/rules/agentic-failure-catalog-schema.rule.py` — validates
  `docs/concepts/agentic-failures.md` has a `## 1. Failure catalog`
  section with unique backticked `` `id` `` rows.
- `scripts/rules/break-glass.rule.py` — detects blocking playbook scripts
  (`sys.exit(1)` present) missing both the `scripts._break_glass` helper
  import + `add_break_glass_flag` call and an `OVERRIDE: none` declaration.

Each ships with `tests/test_<slug>_rule.py` covering ≥5 cases (happy path,
each rejection class, missing-file → exit 2, SKIP env var).

### Changed — 5 advisory downgrades (condition #3)

- `docs/rules/notification-channel-adapter.rule.md`
- `docs/rules/notification-level-declared.rule.md`
- `docs/rules/notification-no-secrets.rule.md`
- `docs/rules/apply-fix-contract.rule.md`
- `docs/rules/hitl-approval-pattern.rule.md`

All five rules now carry `paired_hardrule: null` + `status: advisory`. The
runtime surface for each (`scripts/notifications/`, `langgraph-aiops/`,
`hitl.request_approval`, mutation-class DTOs) lives in consumer projects,
not in the playbook tree. A playbook-side hardrule would only see
references that do not resolve here. Consumers MAY mirror the contract
under their own `scripts/rules/` namespace.

`docs/concepts/enforcement-pairing-exceptions.md` now defines a new
condition #3 ("consumer-side surface") alongside the existing #1
(non-deterministic), #2 (informational), and #4 (false-positive storm),
and the pairing-exception register adds 5 rows for the downgraded rules.

### Removed

- `scripts/rules/deferred-hardrules.txt` — the strict-mode allowlist is
  empty (24 → 14 → 10 → 0 over Slices 5.F, 6, 7). The validator now
  rejects any new `paired_hardrule:` value pointing at a missing
  `.rule.py` without an explicit `paired_hardrule: null` + register
  entry.

### Versioning note

Bumps 0.18.2 → **0.18.3**. Per user-refined versioning 2026-05-19, Slice 7
is the LAST slice of the v0.18.x architectural reset arc (Slices 4-7 share
the v0.18.x band). The next gate is a user review pause; fix iterations
ship as v0.19.x; v0.20.0 is the final cut on explicit user approval.

**🛑 STOP-FOR-REVIEW**: post-merge, do not auto-tag v0.19.0 or v0.20.0.
Hand the session back to the user for review.

## [0.18.2] — 2026-05-19 — Slice 6 telemetry pipeline + 5-CLI absorption + 14 hardrules

Closes the third tranche of the v0.20.0 architectural reset. Slice 4 reorganised
the filesystem; Slice 5 rewrote the content; Slice 6 instruments the playbook
with a rule-event telemetry pipeline, absorbs the five formerly-standalone
cost / lifecycle / budget / deprecation / model-migration CLIs into one
`scripts/telemetry/report.py`, and implements 14 of the 24 deferred paired
hardrules.

### Why now

The v0.20.0 "world reference" milestone needs evidence, not assertion (per
[plan](../../.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md) D15).
arXiv 2310.13361 + IFEval establish that LLMs drift on long instructions; the
rate of drift is the metric a portfolio piece needs to publish. Per-rule-fire
JSONL telemetry turns the L1 hook fleet into a measurement instrument, and the
absorbed CLIs let a monthly report answer obey-rate × cost-per-rule-fire ×
lifecycle in one call.

### Added

- `scripts/telemetry/` package:
  - `rule_event_logger.py` — `log_event(slug, llm, verdict, latency_ms, ...)`
    appends one JSONL row per L1 hook fire. Fail-safe; never raises into the
    hook path.
  - `anonymize.py` — `hash_session_id()` (sha256 → 8 hex chars one-way) +
    `scrub_event()` (PII-key denylist: `file_path`, `path`, `diff`, `content`,
    `body`, `message`, ...).
  - `report.py` — unified CLI (`weekly` / `monthly` / `custom --window-days N`)
    emitting markdown or JSON. Eight sections: obey-rate, cost-per-rule,
    cost-per-session, spend-over-time, retirements, break-glass usage,
    OpenSpec staleness, memory-decay stub.
- `schemas/schema-rule-event-v1.json` — JSON-Schema for the event log; required
  fields + optional token fields + optional `escape_hatch` field.
- `docs/concepts/telemetry-design.md` — concept doc covering event schema,
  privacy guarantees, cost methodology, academic references.
- `docs/runbooks/run-telemetry-report.md` — runbook for weekly/monthly/custom
  report generation.
- `docs/telemetry.md` — mkdocs Telemetry nav page; static placeholder until
  Slice 7 wires the generator.
- Hook dispatcher integration: `scripts/hook_dispatcher.py::dispatch()` emits
  one `rule-event/v1` row per matched rule (lazy-imported, fail-safe). Added
  `emit_telemetry: bool = True` kwarg for benchmarks.
- Escape-hatch tracking:
  - `scripts/_break_glass.py::apply_break_glass` emits a `--force-with-reason`
    rule-event.
  - `scripts/check_doc_drift.py` emits a `[no-doc-impact]` rule-event per
    bypassed pair.
- 14 paired hardrules under `scripts/rules/`:
  - Always-loaded (6): `verdict-contract`, `output-completeness`,
    `verification-before-completion`, `error-message-standard`,
    `apply-skill-enforcement`, `bootstrap-directive`.
  - Workflow / contract (8): `ai-reviewer-signoff`, `auto-merge-discipline`,
    `auto-pr-stream-closure`, `delegated-shipping-prompt`,
    `doc-drift-enforcement`, `github-project-board-schema`,
    `pr-tracker-reference`, `subagent-envelope-schema`.
- Tests:
  - `tests/test_telemetry.py` — 23 cases covering logger, report, compute
    helpers, retirement / staleness / budget / migration absorbed logic.
  - `tests/test_telemetry_privacy.py` — 10 cases enforcing the privacy
    invariants (no PII keys, hashed session_id, pricing math correctness).
  - One `tests/test_<slug>_rule.py` per implemented hardrule (≥5 cases each;
    84 new rule tests total).
  - `tests/test_hook_latency.py` extended with telemetry-emission overhead
    assertion (<5ms median per rule).

### Removed

- `scripts/cost_report.py` (~544 LOC) — absorbed into `report.py`.
- `scripts/lifecycle_check.py` (~1022 LOC) — absorbed.
- `scripts/budget_disable_check.py` (~57 LOC) — absorbed as
  `is_budget_disabled()` helper.
- `scripts/deprecation_watcher.py` (~447 LOC) — absorbed.
- `scripts/simulate_model_migration.py` (~361 LOC) — absorbed.
- `tests/test_cost_report.py`, `tests/test_lifecycle_check.py`,
  `tests/test_deprecation_watcher.py`, `tests/test_activation_triggers.py` —
  coverage ported to `tests/test_telemetry.py`.

### Changed

- `scripts/rules/deferred-hardrules.txt` shrinks from 24 to 10 slugs (always-loaded
  + workflow rules now enforced; migrations / notifications / apply / break-glass
  trio still deferred to Slice 7).
- `mkdocs.yml` — added `Telemetry: telemetry.md` nav entry.
- `configs/pricing.yaml` + `configs/anthropic-retirement-list.yaml` — header
  comments updated to point at `scripts/telemetry/report.py`.
- `templates/retro/monthly.md.tmpl` — invokes `python -m scripts.telemetry.report
  monthly` (replaces the old `scripts/lifecycle_check.py` invocation).
- Operational doc pointers in `docs/concepts/{slos, retrospective-cadence,
  notification-policy, notification-queue, rollout-strategy, model-migration,
  issue-tracking, incident-response, channels}.md` + `docs/rules/break-glass.rule.md`
  + `docs/tutorials/06-curriculum.md` — point at the absorbed CLI.

### Versioning note

Bumps 0.18.1 → **0.18.2**. Per user-refined versioning 2026-05-19, Slices 4–7
all live in the v0.18.x band; v0.19.x is reserved for post-review fix
iterations; v0.20.0 is the final visible milestone on explicit user OK.

## [0.18.1] — 2026-05-19 — Slice 5 doc content rewrite complete

Closes the second half of the v0.20.0 architectural reset
([plan](../../.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md)).
Slice 4 (v0.18.0) reorganised the filesystem; Slice 5 rewrites the content
to the canonical formats locked there. Six sub-slices over 24 hours: 5.B
first (sequential anchor lock), then 5.A/5.C/5.D/5.E in parallel, then 5.F
sequential harmonisation (this entry).

### Sub-slices summary

| Sub-slice | PR | Scope | Files touched |
|---|---|---|---|
| 5.B — concepts rewrite | [#67](https://github.com/Wizarck/ai-playbook/pull/67) | `docs/concepts/*.md` × 57 — canonical `concept/v1` frontmatter, RFC 2119 softening (102 substitutions across 33 files), anchor lock, `flagged-for-rule-migration.md` (20 entries for 5.A pickup), refined `STYLE.md` as authoritative exemplar | 57 concept docs + 1 style guide |
| 5.A — rules rewrite | [#71](https://github.com/Wizarck/ai-playbook/pull/71) | `docs/rules/*.rule.md` × ~24 existing rules rewritten + 14 new rules picked up from 5.B flagged passages (ai-reviewer-signoff, auto-merge-discipline, alembic-migration-naming, subagent-envelope-schema, notification trio, etc.); `cross-rule-redundancies.md` R1-R10 report | 38 total rule docs |
| 5.C — runbooks rewrite | [#70](https://github.com/Wizarck/ai-playbook/pull/70) | `docs/runbooks/*.md` × 14 — canonical procedural format (Goal / Prereqs / Steps / Validation / Rollback / See also); `runbook/v1` schema | 14 runbooks |
| 5.D — tutorials rewrite | [#68](https://github.com/Wizarck/ai-playbook/pull/68) | `docs/tutorials/*.md` × 8 — Diátaxis tutorial style; new `01-architecture-tour.md` 15-min cold-start | 8 tutorials |
| 5.E — new process rules | [#69](https://github.com/Wizarck/ai-playbook/pull/69) | 10 new process rules (install-playbook, update-playbook, cleanup-on-bump, update-documentation, openspec-apply-enforcement, gemini-session-start, data-handling, secrets-handling, english-only-docs, link-integrity); 9 paired `.rule.py` stubs; 6 cross-rule integration tests in `tests/integration/test_rule_interactions.py` | 10 rule docs + 9 hardrule stubs + 6 tests |
| 5.F — harmonisation (this PR) | this | Strict-by-default validators, AGENTS.md Rule Map, deferred-hardrules allowlist, dead-link fixes, VERSION bump, comprehensive CHANGELOG entry | See "Changes in 5.F" below |

### Changes in 5.F (this PR)

- **Strict-by-default validators**:
  - `scripts/validate_pairing.py`: default flipped lenient → strict. New `--lenient` flag preserves the Slice-4 lifeline mode. `--strict` kept as a no-op for backward CI compatibility.
  - `scripts/check_link_integrity.py`: default flipped warn-only → fail. New `--warn-only` flag preserves the legacy WARN-only mode. `--strict` kept as a no-op for backward CI compatibility.
  - `.github/workflows/validate-pairing.rule.yml`, `.github/workflows/check-link-integrity.rule.yml`, `.github/workflows/check-rule-schemas.rule.yml`: invocations already match the new strict default; verified consistent.
- **Deferred-hardrules allowlist** (`scripts/rules/deferred-hardrules.txt`): 24 rule slugs whose `paired_hardrule:` names a `.rule.py` not yet on disk. The validator downgrades the "not found" check to a no-op for listed slugs; the audit register in `openspec/changes/slice-5f-harmonization/deferred-strict-failures.md` documents each deferral and the target slice (6 or 7).
- **AGENTS.md Rule Map** (`§9`): hand-curated table of every `docs/rules/<slug>.rule.md` slug grouped by status (10 enforced / 5 advisory / 24 deferred). Required for D3 signal #4 (every slug present in AGENTS.md text). AGENTS.md grew from 92 → 145 lines, well under the 500-line D14 cap.
- **Dead-link fixes**: 13 dead links resolved (docs/index.md 11 + docs/concepts/slos.md 1 + docs/concepts/upstream-sync.md 2 — all pointing to pre-Slice-4 paths or pre-Slice-5.D tutorial filenames).
- **Tone normalisation**: 2 remaining RFC 2119 keywords in concept-doc frontmatter summaries softened (`agent-contract.md`, `v090-roadmap.md`) — the 5.B softening script had focused on body prose.
- **Cross-reference dedupe (R1-R10 from cross-rule-redundancies.md)**: 5.A already shipped the consolidations; 5.F verified each pair (R1 break-glass restatement, R2 verdict-contract preconditions, R3 error-shape, R4 globs+triggers, R5 ai-reviewer triad, R6 migrations chain, R7 notification trio, R8 parallel-wave vs conflict, R9 subagent envelope vs delegated shipping, R10 verdict-contract parallel-review branch). No further extraction required.
- **Pairing-exception register**: `docs/concepts/enforcement-pairing-exceptions.md` table extended with `data-handling` (Slice 5.E rule that strict mode surfaced as missing justification).
- **New tests** (4 added; baseline 925 → 929 passing):
  - `test_main_lenient_flag_restores_legacy_mode` — validates `--lenient` opt-back.
  - `test_deferred_hardrules_allowlist` — validates the deferred-slugs allowlist.
  - `test_deferred_hardrules_allowlist_respects_comments` — validates `#` comment handling.
  - `test_main_exits_two_on_dead_default_strict` (link integrity) — validates new strict default.
  - `test_main_exits_zero_on_dead_warn_only` (link integrity) — validates `--warn-only` opt-back.
- **VERSION**: 0.18.0 → **0.18.1**.

### Versioning note

Aligns with user-refined versioning 2026-05-19: Slices 4-7 use v0.18.x;
v0.19.x is reserved for post-review fix iterations; v0.20.0 final cut on
explicit user approval only. Slice 5 (PRs #67-#71 + this PR) closes with
v0.18.1. Slice 6 targets v0.18.2 (telemetry). Slice 7 targets v0.18.3
(polish for showcase).

### Migration

None — content rewrites preserve every slug. Strict-mode validators apply
to the playbook repo's own CI only; consumer-side invocations continue to
work unchanged (consumers can opt into the new strict modes by removing
their workflow's `--lenient` / `--warn-only` flag, if any).

## [0.18.0] — 2026-05-19 — filesystem reorg + paired enforcement tooling (BREAKING)

Slice 4 of the v0.20.0 architectural reset
([plan](../../.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md)).
Diátaxis-inspired layout under `docs/{rules,concepts,runbooks,tutorials}/`,
top-level `schemas/` (industry convention), `.rule.<ext>` infix on paired
artefacts (D5), and 9 new tooling scripts implementing the paired
enforcement convention (D3 + D9 + D10 + D12 + D14).

**Three commit phases inside one PR**:
- **4.A** — `git mv` only (~135 files, history preserved).
- **4.B** — mechanical cross-reference rewrites via a throwaway
  `scripts/migrate_paths_v0.18.py` (then deleted; CHANGELOG entry IS the
  historical record).
- **4.C** — config + new tooling + new schemas + new tests + new workflows
  + zombies-manifest v4 entries + VERSION bump.

### Migration table

| Old | New | Notes |
|---|---|---|
| `specs/cleanup-zombies.md` | `docs/rules/cleanup-zombies.rule.md` | Rule (paired with `scripts/rules/cleanup-zombies.rule.py`). |
| `specs/apply-skill-enforcement.md` | `docs/rules/apply-skill-enforcement.rule.md` | Rule. |
| `specs/bootstrap-directive.md` | `docs/rules/bootstrap-directive.rule.md` | Rule. |
| `specs/verdict-contract.md` | `docs/rules/verdict-contract.rule.md` | Rule. |
| `specs/output-completeness.md` | `docs/rules/output-completeness.rule.md` | Rule. |
| `specs/verification-before-completion.md` | `docs/rules/verification-before-completion.rule.md` | Rule. |
| `specs/error-message-standard.md` | `docs/rules/error-message-standard.rule.md` | Rule. |
| `specs/break-glass.md` | `docs/rules/break-glass.rule.md` | Rule. |
| `specs/doc-drift-enforcement.md` | `docs/rules/doc-drift-enforcement.rule.md` | Rule. |
| `specs/apply-fix-contract.md` | `docs/rules/apply-fix-contract.rule.md` | Rule. |
| `specs/conflict-resolution-policy.md` | `docs/rules/conflict-resolution-policy.rule.md` | Rule. |
| `specs/cross-slice-additive-extension.md` | `docs/rules/cross-slice-additive-extension.rule.md` | Rule. |
| `specs/migration-slot-reservation.md` | `docs/rules/migration-slot-reservation.rule.md` | Rule. |
| `specs/hitl-approval-pattern.md` | `docs/rules/hitl-approval-pattern.rule.md` | Rule. |
| `specs/<concept>.md` × 46 | `docs/concepts/<slug>.md` | All other former specs (agent-contract, channels, taxonomy, slos, etc.). |
| `docs/start-here.md` | `docs/tutorials/01-start-here.md` | Numbered tutorial. |
| `docs/quickstart.md` | `docs/tutorials/02-quickstart.md` | Numbered tutorial. |
| `docs/bootstrap-new-project.md` | `docs/tutorials/03-bootstrap-new-project.md` | Numbered tutorial. |
| `docs/quickstart-lessons.md` | `docs/tutorials/04-quickstart-lessons.md` | Numbered tutorial. |
| `docs/curriculum.md` | `docs/tutorials/05-curriculum.md` | Numbered tutorial. |
| `docs/why-these-choices.md` | `docs/tutorials/06-why-these-choices.md` | Numbered tutorial. |
| `docs/fork-inventory.md` | `docs/tutorials/07-fork-inventory.md` | Numbered tutorial. |
| `docs/architecture-diagrams.md` | `docs/concepts/architecture-diagrams.md` | Concept. |
| `docs/contributing.md` | `docs/concepts/contributing.md` | Concept. |
| `docs/development-flow.md` | `docs/concepts/development-flow.md` | Concept. |
| `docs/model-migration.md` | `docs/concepts/model-migration.md` | Concept. |
| `docs/session-start-hook.md` | `docs/concepts/session-start-hook.md` | Concept. |
| `docs/zero-touch-automation.md` | `docs/concepts/zero-touch-automation.md` | Concept. |
| `runbooks/<recipe>.md` × 14 + INDEX | `docs/runbooks/<slug>.md` | All recipes moved under `docs/runbooks/`. |
| `scripts/cleanup_zombies.py` | `scripts/rules/cleanup-zombies.rule.py` | Paired L1 hook (only paired script today). |
| `specs/agent-contract.schema.json` | `schemas/schema-agent-contract.json` | Top-level schemas/. |
| `.github/workflows/doc-drift-check.yml` | `.github/workflows/doc-drift-enforcement.rule.yml` | Paired workflow. |

`specs/` after Slice 4 contains ONLY operational YAMLs:
`zombies-manifest.yaml` + `co-edit-pairs.yaml`. The plan's "specs/
disappears" was hyperbole; what disappears is the mixed-purpose content,
not the directory itself.

### Added — new tooling (9 scripts)

- **`scripts/validate_pairing.py`** — meta-validator enforcing D3 4-signal
  pairing: filename slug ⇔ frontmatter slug ⇔ paired_hardrule cross-ref ⇔
  AGENTS.md Rule Map entry. Eats own dogfood (paired
  `docs/rules/validate-pairing.rule.md` lands in Slice 5). 35 drift-fixture
  tests in `tests/test_validate_pairing.py`.
- **`scripts/validate_pairing_oracle.sh`** — parallel pure-shell tripwire
  re-implementing the slug-existence check (D12 defense-in-depth).
- **`scripts/materialise_cursor_rules.py`** — generates
  `.cursor/rules/<slug>.mdc` from `docs/rules/<slug>.rule.md` (D11).
  Validates Cursor co-constraints: `activation: auto ⇒ globs:` required;
  `activation: agent ⇒ description:` ≤300 chars.
- **`scripts/check_doc_language.py`** — ENGLISH-only docs lint per D6.
  `langdetect`-based when available; heuristic (Spanish diacritics) fallback.
  Fails when >5% of files under `docs/` are non-English.
- **`scripts/check_link_integrity.py`** — broken markdown-link detector.
  Walks every relative `[text](path)` link under `docs/` and verifies the
  target exists. Skips external URLs + in-document anchors.
- **`scripts/hook_dispatcher.py`** — single-process L1 dispatcher (D10).
  Loads all rules once per session; routes by `triggers:` frontmatter.
  Hard SLA: p50 ≤50ms per tool call. `--benchmark` mode reports
  p50/p95/p99. `tests/test_hook_latency.py` enforces the SLA.
- **`scripts/check_agents_md_size.py`** — fails CI when AGENTS.md exceeds
  500 lines (D14). Default cap 500; configurable via `--cap`.
- **`scripts/check_deprecated_rules.py`** — warns at PR-time when editing
  a `status: deprecated` rule (D18). Exit 1 (warn) by default; `--strict`
  promotes to exit 2.
- **`scripts/gen_indexes.py`** — already shipped pre-Slice 4; verified
  works against the new `docs/{rules,concepts,runbooks,tutorials}/` layout.

### Added — schemas (D9 disjoint)

- **`schemas/schema-rule-v1.json`** — validates `.rule.md` frontmatter.
  Required: `schema/slug/description/paired_hardrule/activation/status`.
  Forbids fields specific to concept docs (`additionalProperties: false`).
- **`schemas/schema-concept-v1.json`** — validates concept frontmatter.
  Required minimal `schema/slug/title`. Forbids rule-only fields
  (`paired_hardrule`, `activation`, `status`, `triggers`, `break_glass`,
  `applies_to`, `globs`, `rule_bundle`). Disjoint per D9 — schemas force
  the rule-vs-concept distinction at validation time.

### Added — placeholder docs (Slice 5 rewrites content)

- `docs/concepts/enforcement-layers.md` — L1/L2/L3 architecture explainer.
- `docs/concepts/cross-llm-activation.md` — Cursor 4-mode mapping per LLM (D20).
- `docs/concepts/enforcement-pairing-exceptions.md` — advisory-rule justification.
- `docs/concepts/STYLE.md` — writing style guide for Slice 5 authors. ≤30 lines.
- `docs/tutorials/01-architecture-tour.md` — cold-start entry point (content in Slice 7).

### Added — tests (4 files, 70+ cases)

- `tests/test_validate_pairing.py` — 35 drift fixtures (orphan hardrule,
  orphan doc, slug mismatch, plural form, unicode, advisory justification,
  include-local, etc.).
- `tests/test_hook_latency.py` — 8 cases; enforces ≤50ms p50 SLA.
- `tests/test_check_doc_language.py` — 14 cases (heuristic vs langdetect,
  code-block stripping, threshold logic).
- `tests/test_check_link_integrity.py` — 13 cases (external skip, anchor
  skip, image syntax, relative resolution, line-number reporting).

### Added — workflows (5 aggregated rule-workflows, D10/D14 burst mitigation)

- `.github/workflows/validate-pairing.rule.yml`
- `.github/workflows/check-doc-language.rule.yml`
- `.github/workflows/check-link-integrity.rule.yml`
- `.github/workflows/check-agents-md-size.rule.yml`
- `.github/workflows/check-rule-schemas.rule.yml` (validates ALL `*.rule.md`
  against `schema-rule-v1.json` and ALL `docs/concepts/*.md` against
  `schema-concept-v1.json` in one job — avoids 1-workflow-per-rule burst).

### Changed

- **`pyproject.toml`** `[tool.setuptools.packages.find]` updated to reflect
  new package layout; `scripts.rules` is now a sub-package.
- **`.pre-commit-hooks.yaml`** exposes 4 paired hooks for consumers:
  `validate-pairing`, `check-doc-language`, `check-link-integrity`,
  `check-agents-md-size`.
- **`specs/zombies-manifest.yaml`** extended with 5 v4 entries (Tier 3
  report-only) for the path migrations. `manifest_version` bumped to
  `2026-05-19.4`.
- **`scripts/rules/cleanup-zombies.rule.py`** `_resolve_default_manifest`
  walks 3 parents up (was 2) — script moved one level deeper.

### Test results

- `pytest tests/` — 916 passed, 2 skipped (e2e env-gated baseline).
  Compared to pre-Slice-4 baseline: +70 new tests, all green.
- `python scripts/validate_pairing.py` — exit 0 (current rules satisfy
  signal #1 + #2; signal #3 + #4 enforced in Slice 5 once frontmatter is
  authored).
- `python scripts/check_link_integrity.py docs/` — exit 0.
- `python scripts/check_agents_md_size.py` — exit 0 (AGENTS.md 92/500 lines).
- `python scripts/check_doc_language.py docs/` — exit 0 (heuristic mode).
- `python scripts/hook_dispatcher.py --benchmark` — p50 well under 50ms.
- `python scripts/rules/cleanup-zombies.rule.py validate` — exit 0
  (manifest version `2026-05-19.4`, 28 entries).

### Versioning note (per D19, refined 2026-05-19)

v0.18.0 starts the v0.18.x sequence for Slices 4-7. v0.19.x reserved for
post-review fixes. v0.20.0 final by explicit user OK.

## [0.17.1] — 2026-05-19 — root folder cleanup audit (additive PATCH)

Slice 3.5 of the v0.20.0 architectural reset
(`~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md`). Critical-eye
audit of every file at the playbook repo root before slice 4 (filesystem
reorg, v0.18.0 BREAKING) begins. Additive only — no removals from the
consumer-facing surface, just zombie-manifest entries so the 5 sister repos
self-clean on the next bump.

Per-file ledger committed at [docs/concepts/root-folder-audit.md](docs/concepts/root-folder-audit.md).
Decision rationale per move at
[openspec/changes/root-folder-audit/design.md](openspec/changes/root-folder-audit/design.md).

### Deleted

- `FEEDBACK.md` — append-only gripe channel; never triaged under sole-consumer
  reality. Error messages in `scripts/mcp/render.py` + `scripts/mcp/validate.py`
  that previously pointed here now direct stack traces to a GitHub issue.
- `ai_playbook.egg-info/` — `pip install -e .` build artefact; `.gitignore`
  already covers `*.egg-info/` so the directory was always untracked. Removing
  on-disk; regenerates automatically on the next install.
- `.github/workflows/issue-sync.yml` — multi-tenant Jira/GH-Issues sync
  workflow; sole consumer does not use it. The underlying
  `scripts/issue_sync.py` is **not** deleted; slice 6 (telemetry, v0.19.1) may
  absorb it.

### Moved (history preserved via `git mv`)

- `mcp-servers-base.yaml` → `templates/rendered/mcp-servers-base.yaml.tmpl`.
  Conceptually a template that consumers extend — belongs alongside the other
  rendered templates. Internal references updated in `scripts/mcp/validate.py`
  (`resolve_playbook_root` sentinel + `load_layers`), `scripts/mcp/render.py`
  (error message), `scripts/init_org.py` (bootstrap walker), and the matching
  test fixtures.
- `pricing.yaml` → `configs/pricing.yaml`. Runtime configuration data driving
  `scripts/cost_report.py`; same shape as
  `configs/anthropic-retirement-list.yaml`. Slice 6 (telemetry, v0.19.1) will
  continue to load from this location. `scripts/cost_report.py` default path
  + error message updated.

### Added

- `docs/concepts/root-folder-audit.md` — full per-file ledger covering every
  visible root entry + every `.github/workflows/*.yml`.
- `openspec/changes/root-folder-audit/` — proposal, tasks, design.
- `specs/zombies-manifest.yaml` — 5 new v3 entries:
  `feedback-md-removed`, `mcp-servers-base-relocated`, `pricing-yaml-relocated`,
  `ai-playbook-egg-info-orphan`, `issue-sync-workflow-removed`. Manifest
  version bumped from `2026-05-19.2` → `2026-05-19.3`.

### Unchanged at root (documented for the next audit baseline)

`pyproject.toml`, `.pre-commit-config.yaml`, `.pre-commit-hooks.yaml`,
`.gitignore`, `.gitattributes`, `AGENTS.md`, `README.md`, `VERSION`,
`CHANGELOG.md`, `MAINTAINERS.md`, `mkdocs.yml`, `consumers.yaml`. Reasons
documented in `docs/concepts/root-folder-audit.md`.

### Deferred to slice 6 (telemetry, v0.19.1) per D15

Standalone CLIs `scripts/cost_report.py`, `scripts/lifecycle_check.py`,
`scripts/budget_disable_check.py`, `scripts/deprecation_watcher.py`,
`scripts/simulate_model_migration.py` remain in place and continue to work
in v0.17.1. Slice 6 absorbs them into `scripts/telemetry/report.py`.

### Deferred to slice 5 (content rewrite, v0.19.0)

Prose references to `FEEDBACK.md` inside `docs/`, `specs/`, and
`runbooks/*.md` — slice 5 rewrites those documents end-to-end anyway. Slice
3.5 stays surgical: physical file delete + script-error-message rewrite only.

## [0.17.0] — 2026-05-19 — single-source skills reset + Gemini parity (BREAKING)

**BREAKING.** Slice 3 of the v0.20.0 architectural reset
(`~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md`).
Drops RFC-0001 (multi-source skills distribution) entirely. The playbook
submodule is now the single source of truth for skills; the materialiser
fans out to three gitignored mirrors at the consumer side.

Why now: the multi-source pattern shipped 2026-04-26 with 2 submodules + 3
scripts + 1 workflow + 1 pre-commit guard, paid by every consumer for a
feature **no consumer actually used**. consumer-a had already deviated locally
(PR #125, 2026-05-18) with a simpler `sync_skills_local.py`. This release
promotes that pattern upstream and removes the legacy machinery.

Decisions cited: **D1** (single-source skills), **D2** (scripts not mirrored),
**D17** (skills perpendicular rules), **D19** (versioning to v0.20.0).

### BREAKING — Migration table

| Removed in v0.17.0 | Replacement | Consumer action |
|---|---|---|
| `scripts/_skills_materialiser.py` (multi-source) | `scripts/materialise_skills.py` (single-source) | Re-wire any direct invocation; new CLI flags (`--source`, `--quiet`, `--dry-run`). |
| `scripts/propagate_skills_bump.py` | None (single-source = playbook tag IS the skills tag) | Remove any wrapper that invoked `.ai-playbook/scripts/propagate_skills_bump.py`. |
| `scripts/validate_skills_mirror.py` | Built into the new materialiser (fingerprint-equality short-circuit) | Remove from `.pre-commit-config.yaml`. |
| `.github/workflows/propagate-skills-bump.yml` | None (the existing `propagate-playbook-bump.yml` already covers it) | Remove consumer copies if any. |
| `rfcs/RFC-0001-skills-distribution.md` + `rfcs/README.md` + `rfcs/` folder | `docs/concepts/skills-distribution.md` v2.0.0 | Migrate cross-references to the spec. |
| `skills_sources:` block in AGENTS.md frontmatter | None — single-source needs no declaration | Drop the block from `AGENTS.md`. Zombies-manifest flags it as Tier 3 advisory. |
| `skills_pins:` keys in `consumers.yaml` | None | Drop on the next `consumers.yaml` edit. Schema's `additionalProperties: true` keeps them valid as no-ops. |
| `validate-skills-mirror` entry in `.pre-commit-hooks.yaml` | None (drift-detection built-in) | If your `.pre-commit-config.yaml` references it, remove the entry. |
| `.skills-sources/<repo>/` submodule | None — single source is the playbook itself at `.ai-playbook/skills/` | Deregister via `git submodule deinit`, then let `cleanup_zombies.py --apply` remove the orphan directory (Tier 1 entry tightened to `removed_in: v0.17.0`). |

### Added

- **`scripts/materialise_skills.py`** (NEW, ~270 LOC). Single-source materialiser
  with idempotency via sha256 fingerprint comparison per mirror. Reads from
  `<consumer>/.ai-playbook/skills/`, fans out to `<consumer>/skills/`,
  `<consumer>/.claude/skills/`, `<consumer>/.gemini/skills/`. CLI flags
  `--consumer`, `--source`, `--dry-run`, `--quiet`. Exit codes 0/1/2 per spec.
- **`scripts/gemini_start.py`** (NEW). Cross-platform Gemini CLI wrapper that
  runs the materialiser + `inject_context.py` before exec'ing `gemini`. Brings
  upstream the wrapper consumer-a authored locally; adapted to derive `bank_id`
  from cwd (no `consumer-a` hard-codes). POSIX `os.execvp` + Windows `subprocess.run`.
- **`templates/new-project/scripts/gemini_start.py.tmpl`** (NEW). Thin pointer
  template — invokes the upstream `.ai-playbook/scripts/gemini_start.py` per D2.
- **`templates/new-project/scripts/install-playbook-hooks.sh.tmpl`** (NEW). Bash
  installer that points `core.hooksPath` at `scripts/git-hooks/` and runs the
  first skills materialisation + zombie cleanup pass. Replaces consumer-a's local
  `install-skills-hooks.sh` with a broader-scope upstream template.
- **`tests/test_materialise_skills.py`** (NEW, 15 tests). Covers fresh consumer,
  idempotency, orphan removal, mirror parity (Claude vs Gemini vs generic),
  dry-run, source missing, partial mirror regeneration, nested skill assets,
  quiet/loud mode, `--source` override, CLI exit codes (0 / 2), subprocess
  invocation smoke.
- **`schemas/`** (NEW top-level folder per D9). Hosts `schema-agents-md-v1.json`
  (relocated from `specs/`). Future schemas (rule-v1, concept-v1, rule-event-v1)
  land here in slices 4-6.
- **8 v2 entries in `specs/zombies-manifest.yaml`** documenting the multi-source
  artefacts a consumer might still carry: `propagate-skills-bump-script`,
  `validate-skills-mirror-script`, `propagate-skills-bump-workflow`,
  `rfcs-folder-removed`, `skills-sources-submodule-v2` (Tier 1 safe-delete;
  the rest Tier 3 advisory), `skills-sources-frontmatter`,
  `skills-pins-consumers-yaml`, `validate-skills-mirror-precommit-hook`.
  Manifest bumped to `2026-05-19.2` (18 total entries, all schema-valid).
- **openspec change `single-source-skills-reset/`** — proposal + tasks + design
  documenting this slice's scope, decisions, and acceptance criteria.

### Changed

- **`docs/concepts/skills-distribution.md`** rewritten to v2.0.0. Reflects single-source
  design, cites D1 / D2 / D17. New §1 (decisions), §3 (consumer-side layout
  with gitignored mirrors), §4 (materialisation algorithm + fingerprint
  idempotency), §5 (hook wiring incl. Gemini-specific wrapper), §8 (updated KPIs).
- **`scripts/bootstrap.py`** import updated from `scripts._skills_materialiser`
  to `scripts.materialise_skills`. Exit-code mapping updated: exit 2 only when
  source is missing (consumer needs `git submodule update --init`); exit 1 for
  other failures.
- **`scripts/schema_validate.py`** SCHEMA_RELPATH updated from
  `specs/agents-md-v1.schema.json` to `schemas/schema-agents-md-v1.json`.
  Documentation strings updated accordingly.
- **`schemas/schema-agents-md-v1.json`** (moved from `specs/`). `$id` updated to
  reflect the new path. Description annotates the v0.17.0 drop of
  `skills_sources` + `skills_pins` properties (kept valid via
  `additionalProperties: true`; flagged advisory by the zombies manifest).
- **`specs/zombies-manifest.yaml`** existing entries refined:
  - `skills-sources-submodule` (Tier 1) — `removed_in: v0.17.0` (was
    `deprecation_only`); reason clarified.
  - `skills-sources-frontmatter-simplify` (Tier 3) — `removed_in: v0.17.0`;
    detection expanded to flag any `skills_sources:` block (was: single-entry
    only); fix points to the new single-source materialiser.
  - `pre-commit-deprecated-hooks` (Tier 3) — `removed_in: v0.17.0`; reason
    updated to reflect that BOTH scripts are now deleted upstream (was: only
    advisory based on consumer state).
- **`templates/new-project/scripts/git-hooks/post-checkout.tmpl`** and
  **`post-merge.tmpl`** — both now prefer
  `.ai-playbook/scripts/materialise_skills.py` (upstream) over a consumer-local
  `scripts/sync_skills_local.py` (legacy consumer-a path). Fall-back to the legacy
  path preserved for consumers still on v0.16.x.
- **`.pre-commit-config.yaml`** — `validate-skills-mirror` hook entry removed
  (comment retained for archeology).
- **`.pre-commit-hooks.yaml`** — empty hook export with explanatory comment.
  v0.18.0 (slice 4) populates this with the new L1+L2+L3 paired hooks.

### Removed

- `scripts/_skills_materialiser.py` (multi-source RFC-0001 materialiser).
- `scripts/propagate_skills_bump.py` (per-source propagator).
- `scripts/validate_skills_mirror.py` (drift validator — obsoleted by the new
  materialiser's fingerprint check).
- `tests/test_skills_materialiser.py`, `tests/test_propagate_skills_bump.py`,
  `tests/test_validate_skills_mirror.py` (replaced by `tests/test_materialise_skills.py`).
- `.github/workflows/propagate-skills-bump.yml`.
- `rfcs/RFC-0001-skills-distribution.md`, `rfcs/README.md`, and the `rfcs/`
  folder entirely.
- `specs/agents-md-v1.schema.json` (moved to `schemas/schema-agents-md-v1.json`).

### Validation

- `pytest tests/` — 818 passed, 2 skipped (slice 2's `test_apply_enforce_hook_template.py` failures already fixed on main).
- `python scripts/rules/cleanup-zombies.rule.py validate` — exit 0, manifest 2026-05-19.2
  with 18 entries (10 v1 + 8 v2, all schema-valid).
- `python scripts/materialise_skills.py --consumer <tmp> --dry-run` — exit 0
  on a fresh tmp dir seeded with `.ai-playbook/skills/`; idempotent (second run
  is a no-op).

### Notes

- Consumers that never migrated to the multi-source pattern (4 of 5 active:
  consumer-c, consumer-d, consumer-b, consumer-e) require **no migration** —
  their `consumers.yaml.<name>.skills_pins:` keys lingering as dead text is
  the only artefact, and cleanup-zombies surfaces it as a Tier 3 advisory.
- consumer-a (the one consumer that DID migrate) already deviated with
  `sync_skills_local.py`; the new upstream materialiser matches its pattern
  byte-for-byte, so the only consumer-side fix needed is to point
  `scripts/git-hooks/post-merge` at `.ai-playbook/scripts/materialise_skills.py`
  instead of the local copy.
- The new `templates/new-project/scripts/install-playbook-hooks.sh.tmpl` runs
  the materialiser + zombie cleanup on first install; the existing
  consumer-a-local `install-skills-hooks.sh` (single-purpose) is now a Tier 3
  zombie via `pre-commit-deprecated-hooks`.

## [0.16.0] — 2026-05-19 — doc-drift CI enforcement + audit drift fixes

Additive MINOR. Slice 2 of the architectural reset plan v0.15.0 → v0.20.0 (see `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow.md` §"Slice 2"). Ships a declarative co-edit-pairs manifest + a PR-time CI check that fails when one side of a known (code, doc) pair is modified without the other, with a documented `[no-doc-impact]` PR-title escape hatch. Also clears 3 long-standing test failures and 8 dead cross-references that were left over from prior renames.

### Added

- **`docs/rules/doc-drift-enforcement.rule.md`** (NEW, v1.0.0). Full contract: manifest schema (§2), CI gate behaviour (§3), canonical block message shape (§4 — per `docs/rules/error-message-standard.rule.md`), escape-hatch contract (§5 — `[no-doc-impact]` case-insensitive substring in PR title), adoption checklist (§6), invariants (§7), open questions (§8). Future tiers (2 = soft / warn, 3 = informational / telemetry-only) are reserved in the schema; only Tier 1 (strict) is enforced in v0.16.0.
- **`specs/co-edit-pairs.yaml`** (NEW). v1 ships with 12 hand-curated pairs grounded in the real `scripts/` ↔ `specs/` topology: `cleanup-zombies`, `zombies-manifest`, `apply-skill-enforcement-hook`, `apply-skill-enforcement-marker`, `git-worktree-bare-layout`, `auto-managed-sections`, `break-glass`, `verdict-contract`, `error-message-standard`, `doc-drift-enforcement` (self-reference — the rule eats its own dogfood), `doc-drift-manifest`, `mcp-servers-schema`. Schema validation enforced via `check_doc_drift.py validate` (exit 2 on schema break).
- **`scripts/check_doc_drift.py`** (NEW): argparse-driven CLI with two subcommands. `check` (default) reads `git diff --name-only origin/main...HEAD` (triple-dot to capture only THIS branch's changes), evaluates each Tier 1 pair, and either passes (exit 0) or emits a canonical WHY/FIX/OVERRIDE error and exits 1. Honours `--pr-title` for the escape hatch. `validate` runs schema-only check. `--diff-files` flag bypasses git for tests / synthetic probes. 28 tests in [`tests/test_check_doc_drift.py`](tests/test_check_doc_drift.py) covering: 11 schema-validation paths (exit 2), 9 drift-detection paths (exit 0/1), 5 escape-hatch behaviours, and 3 smoke probes against the real shipped manifest.
- **`.github/workflows/doc-drift-enforcement.rule.yml`** (NEW). Triggers on `pull_request: [opened, synchronize, reopened, edited]` — the `edited` trigger is critical so adding `[no-doc-impact]` to the PR title re-runs without a code push. Sticky PR comment pattern (one comment per PR, updated on each run) mirrors `branch-name-validator.yml`. Hard-fails the check on drift; passes when the manifest is clean OR the escape hatch is honoured.

### Changed

- **`docs/concepts/enforcement-status.md`**: new row for `doc-drift-enforcement.md` at ✅ wired (script + 28 tests + CI workflow + manifest schema validator).
- **`docs/concepts/development-flow.md`** §5 enforcement table: new row "Doc-drift on paired (code, doc) tuples" at ✅ wired.
- **`README.md`** status section bumped to v0.16.0 with the new doc-drift summary.

### Fixed

- **`tests/test_apply_enforce_hook_template.py`**: 3 long-standing failing tests (`test_hook_blocks_when_no_marker`, `test_hook_handles_glob_in_write_paths`, `test_hook_writes_canonical_error_shape`) now pass. Root cause was a test-fixture issue, not a template bug: `_invoke_hook` copied `os.environ` whole, leaking the parent harness's `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` env var into the child process. The hook (correctly per `docs/rules/apply-skill-enforcement.rule.md` §3) treated the inherited override as a legitimate break-glass and returned exit 0 instead of the expected block (exit 2). Fix: scrub `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE` from the fixture env unless the test explicitly sets it via the `override` kwarg.
- **`docs/concepts/project-board-sync.md`** × 5 dead cross-refs: `templates/workflows/project-*.yml` (path never existed) → `templates/new-project/.github/workflows/project-*.yml.tmpl` (canonical location).
- **`docs/concepts/release-management.md`** × 1: `templates/new-project/.github/workflows/propagate-playbook-bump.yml.tmpl` (does not exist; bump-bot is a playbook-internal workflow) → `.github/workflows/propagate-playbook-bump.yml` (correct location) + clarifying note.
- **`docs/tutorials/05-curriculum.md`** × 1: `../CLAUDE.md` (playbook itself does not ship a `CLAUDE.md`) → consumer-side guidance with explicit note that the playbook dogfoods AGENTS.md only.
- **`docs/runbooks/coderabbit-fallback.md`** × 1: `../../consumer-e/docs/gotchas.md` (cross-repo broken relative path) → generic consumer-side reference.

### Validation

- `pytest tests/test_check_doc_drift.py` — 28 / 28 green.
- `pytest tests/test_apply_enforce_hook_template.py` — 10 / 10 green (was 7 / 10).
- `python scripts/check_doc_drift.py validate` — exit 0.
- Synthetic probe: `python scripts/check_doc_drift.py --diff-files scripts/rules/cleanup-zombies.rule.py` → exit 1 (drift detected).
- Synthetic escape-hatch probe: same diff + `--pr-title "feat: bump [no-doc-impact]"` → exit 0.
- `python scripts/rules/cleanup-zombies.rule.py validate` — exit 0.

### Notes

- Tier 2 (soft / warn) and Tier 3 (informational / telemetry-only) are reserved in the schema but NOT enforced in v0.16.0. Activation planned for slice 5+ (doc rewrites; may surface many transient pair violations) and slice 6 (telemetry pipeline) per the reset plan.
- Slice 6 will extend the workflow to emit a `rule_event` per check fire with `escape_hatch: true|false`, enabling monthly reports to flag escape-hatch abuse (> 20% / month) or specific pairs that are always escape-hatched (candidates for tier downgrade).
- This slice is concurrent with Slice 3 (`feat/single-source-skills-reset`, target v0.17.0); ownership matrix in `~/.claude/plans/vamos-a-identificar-los-elegant-marshmallow-handover.md`. Whichever lands first; the other rebases through `CHANGELOG.md` + `VERSION`.

## [0.15.0] — 2026-05-19 — consumer-side zombie cleanup hook (declarative manifest + auto-fire)

Additive MINOR. Solves a long-standing hygiene gap: bumping `.ai-playbook` advances the submodule pin but never cleans what prior pins deposited in consumer trees. Patterns observed in `consumer-a` (PR #125, 2026-05-18): orphan `.skills-sources/` submodule + `.git/modules/.skills-sources/` metadata after a single-source simplification, stale `consumer-c-legacy` literals in MCP YAMLs after the v0.14.1 rename, drained-but-fat `hindsight-queue.jsonl` files, orphan `<!-- BEGIN auto-managed: <source> -->` markdown blocks.

This release ships a **declarative zombie manifest** + a **single cleanup script** that consumers invoke automatically from their `post-merge` / `post-checkout` hooks (same pattern as `sync_skills_local.py`).

### Added

- **`docs/rules/cleanup-zombies.rule.md`** (NEW, v1.0.0). Full contract: manifest schema (§2), three-tier policy (§3), six safety checks catalogue (§4), three-channel report contract (§5), exit-code policy (§6 — default invocation NEVER exits non-zero), break-glass clause (§7, `AIPLAYBOOK_CLEANUP_SKIP=1`), consumer adoption checklist (§8).
- **`specs/zombies-manifest.yaml`** (NEW). Rolling declarative inventory. v1 ships with 10 entries — 4 × Tier 1 (safe-delete), 1 × Tier 2 (literal rename), 5 × Tier 3 (advisory-only). Schema validation enforced via `cleanup_zombies.py validate` (exit 2 on schema break — the ONLY non-zero exit in the tool).
- **`scripts/rules/cleanup-zombies.rule.py`** (NEW): default invocation is dry-run; `--apply` executes Tier 1+2; `--quiet` for hook context; `validate` for the manifest schema pre-commit gate; `version` prints the manifest_version. 31 tests in [`tests/test_cleanup_zombies.py`](tests/test_cleanup_zombies.py) covering: manifest schema (9), each safety check (8), decision flow + channels (8), exit-code policy + break-glass (5), idempotency (1).
- **`templates/new-project/scripts/git-hooks/post-merge.tmpl`** (NEW). Two-step bash: skills sync → playbook zombie cleanup. Always exits 0 (`|| true` after cleanup). Activates via existing `scripts/install-skills-hooks.sh` pattern (sets `git config core.hooksPath scripts/git-hooks`).
- **`templates/new-project/scripts/git-hooks/post-checkout.tmpl`** (NEW). Analogous, gated on `$3 == "1"` (branch-checkout flag) so file checkouts don't re-fire.

### Changed

- **`docs/concepts/enforcement-status.md`**: new row for `cleanup-zombies.md` at ✅ wired (script + 31 tests + 2 hook templates + manifest schema validator).
- **`docs/concepts/development-flow.md`** §5 enforcement table: new row for "Consumer-side playbook zombie cleanup" at 🟡 partial (auto-fires per hook; promotion to ✅ when ≥ 1 real consumer adopts and reports a quiet quarter).
- **`docs/runbooks/release.md`** §2: pre-cut checklist gains "If this release REMOVED or RENAMED any consumer-surface artefact (template file, frontmatter field, literal identifier consumers wire against), append an entry to `specs/zombies-manifest.yaml` and bump `manifest_version`."

### Consumer adoption (per consumer, in a follow-up PR)

1. Bump `.ai-playbook` submodule to v0.15.0.
2. Append one line to existing `scripts/git-hooks/post-merge` AND `scripts/git-hooks/post-checkout`:
   ```bash
   python "$REPO_ROOT/.ai-playbook/scripts/rules/cleanup-zombies.rule.py" --apply --quiet || true
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

- **L1 — doc rule**: explicit text in [`docs/concepts/runbook-bmad-openspec.md`](docs/concepts/runbook-bmad-openspec.md) §3.1.1 stating apply phase MUST go through the skill. New row `2.13 apply_phase_bypass` in [`docs/concepts/agentic-failures.md`](docs/concepts/agentic-failures.md).
- **L2 — skill marker**: skill `openspec-apply-change` bumped to v1.1 — new step 0 writes a JSONL `start` record to `openspec/changes/<id>/.apply_log.jsonl` (committed to git for audit). Marker helper `scripts/openspec_apply_marker.py` exposes `start`/`stop`/`override`/`is_active`/`session_started`/`list` subcommands.
- **L3 — PreToolUse hook**: project-local hook at `.claude/hooks/openspec-apply-enforce.py` blocks `Edit`/`Write`/`MultiEdit` on a slice's `write_paths` when no `start` record exists for the current session. Break-glass via `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE=<≥10-char reason>` env (audited via `override` JSONL record).

### Added

- **`docs/rules/apply-skill-enforcement.rule.md`** (NEW, v1.0.0). Marker contract (§1), hook contract (§2), break-glass clause (§3, per [`break-glass.md`](docs/rules/break-glass.rule.md)), invariants INV-1..INV-4 (§4), consumer adoption checklist (§5), retro/audit cadence (§6).
- **`scripts/openspec_apply_marker.py`** (NEW). 6 subcommands. JSONL append-only audit log. Session-id resolution: `--session-id` → `$CLAUDE_SESSION_ID` env → derived `local-<git-user>-<host>-<pid>`. Path resolution walks `cwd` ancestors for `openspec/` dir. Error shape per [`error-message-standard.md`](docs/rules/error-message-standard.rule.md). 9 tests in [`tests/test_openspec_apply_marker.py`](tests/test_openspec_apply_marker.py): happy paths, idempotent start, corrupt-JSONL recovery, override audit record, missing change folder, list subcommand.
- **`templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl`** (NEW). Project-local PreToolUse hook. Reads JSON from stdin per Claude Code hook protocol. Walks `openspec/changes/*/tasks.md`, parses `Owns (write_paths)` section (bullet `* `path`` lines), glob-matches via `fnmatch`. Calls `session_started` subprocess per matching active change. Honours override env. Emits canonical block message per error-message-standard.md. Fail-open on missing helper. Perf budget <250ms p95. 10 tests in [`tests/test_apply_enforce_hook_template.py`](tests/test_apply_enforce_hook_template.py).
- **Skill `openspec-apply-change` v1.1**: new step 0 ("Write apply-session start marker") inserted before existing step 1. Frontmatter `version: "1.0"` → `"1.1"`. Backwards-compatible: pre-v0.14.0 consumers without the helper script see the skill's note about overdue playbook bump but proceed (no block).

### Changed

- **`docs/concepts/runbook-bmad-openspec.md`** §3.1.1 (NEW subsection). Documents the apply-phase orchestration rule + the two enforcement vectors + cross-references to QA pairing (§3.2) and self-validation gates (§3.4).
- **`docs/concepts/agentic-failures.md`** §1 catalog: new row `apply_phase_bypass` (S2, Detectable: Yes). §2 catalog detail: new section §2.13 with Signal/First-response/Detector/Example. Example cites the consumer-a Revalid incident.
- **`docs/concepts/enforcement-status.md`**: new row for `apply-skill-enforcement.md` at ✅ wired. `agentic-failures.md` row flipped from 📋 spec-only to 🟡 partial (mode 2.13 now wired via the hook).
- **`templates/new-project/.claude/settings.json.tmpl`**: registers the new `PreToolUse` hook for `Edit|Write|MultiEdit` matcher.

### Migration (per consumer)

5-step adoption checklist in [`docs/rules/apply-skill-enforcement.rule.md`](docs/rules/apply-skill-enforcement.rule.md) §5:

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
- Hook fails OPEN on helper absence (intentional, see [`docs/rules/apply-skill-enforcement.rule.md`](docs/rules/apply-skill-enforcement.rule.md) §2.4): a missing `.ai-playbook/scripts/openspec_apply_marker.py` warns to stderr but does not block. Consumer pre-v0.14.0 sees no enforcement.

## [0.13.4] — 2026-05-14 — worker-agent delegation prompt contract (`release-management.md` §4.5.5 + §4.5.6)

Patch release. Additive — codifies two prompt-engineering patterns that emerged across 4 consecutive worker-agent-delegated PRs in the `Wizarck/consumer-e` dashboard wave (#149, #150, #151, #152) plus one CI-recovery cycle (PR #152 L2 re-run).

Both failure modes affect the **whole-slice worker-agent delegation** flow (main agent invokes `Agent(isolation="worktree", ...)` to ship apply → lint → push → open PR end-to-end). Neither was previously covered: §4.5.4 only covers *automation* PRs (bump / chore-archive scripts), not *worker-AI* delegation. The new subsections close that gap.

New: [`docs/concepts/release-management.md`](docs/concepts/release-management.md) §4.5.5 — **Worker-agent delegation: STOP-after-`gh pr create` directive.** Prompts MUST embed the literal "STOP after `gh pr create` returns the PR URL. Do NOT poll CI." instruction. Verified on consumer-e PRs #149-#152: worker wall-time dropped from ~16 min to 4-8 min (263 seconds on PR #151, new record) after the directive landed.

New: [`docs/concepts/release-management.md`](docs/concepts/release-management.md) §4.5.6 — **Worker-agent delegation: AI-reviewer signoff canonical block in prompt.** Prompts MUST embed the literal §4.5.3 block (three markers `Profile:`, `Reviewer:`, `Self-review findings:`) verbatim, not a free-form "write a self-review section" instruction. Failure surfaced on consumer-e PR #152 (substantive prose, no markers → L2 re-run cycle, +6 min recovery).

Tracked at [`openspec/changes/agent-spawn-template-improvements/proposal.md`](openspec/changes/agent-spawn-template-improvements/proposal.md).

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.4`. No code changes required — docs-only patch. Main agents that already include the patterns ad-hoc see no change; main agents that don't get a documented contract to follow.

## [0.13.3] — 2026-05-13 — fusion-integration-pattern spec + new-project template polish

Patch release. Additive — codifies the integration pattern for consumer projects that already have a mature OpenSpec custom workflow (their own `openspec/schemas/<name>/schema.yaml` with N artefacts and project-specific Karpathy/discipline rules). The pattern preserves the consumer's accumulated workflow investment and imports the formal contracts the playbook ships (verdict-contract S1-S4, parallel-review context isolation, agentic-failures taxonomy, output-completeness rules, verification-before-completion iron law, agent-contract write_paths, Hindsight recall) without replacing the custom workflow.

First reference implementation: `consumer-a` (FastAPI + Next.js modular monolith, `consumer-a-team` schema with 9 artefacts, 18 changes pre-fusion).

New: [`docs/concepts/fusion-integration-pattern.md`](docs/concepts/fusion-integration-pattern.md) — fusion decision matrix, AGENTS.md §7 template structure, migration policy (existing changes exempt), N-layer parallel review (3 isolated playbook layers + 1 holistic project-reviewer layer with M custom checks; no size opt-out), dual canonical memory sources (Markdown SSOT + Hindsight recall), verdict mapping reference (legacy → canonical), pre-commit hook profile with documented opt-out conditions, worked example.

Template polish (no breaking changes for existing consumers):

- `templates/new-project/AGENTS.md.tmpl`: bump `inherits_from` pin from `v0.3.0` to `v0.13.2` (current shipped at time of v0.13.3 PR). Add §7 comment block linking to fusion-integration-pattern.md for projects with pre-existing custom workflows.
- `templates/new-project/.pre-commit-config.yaml.tmpl`: add `verdict-lint` hook as default (matches `openspec/changes/*/(review|verify).md`). Comment out `block_manual_spec_edit` and `verify_llm_routing` hooks with explicit opt-in activation conditions documented inline. Expand `mcp-validate` `files` regex to match both `mcp-servers.yaml` and `mcp-servers.project.yaml`.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.3`. No code changes required. Existing consumer projects with their own workflow stay on the path they were on; the new spec is opt-in for projects that need it.

## [0.13.2] — 2026-05-13 — upstream-sync §9: containerised forks pin-bump rule

Patch release. Docs-only — `docs/concepts/upstream-sync.md` v1.0.0 → v1.1.0 gains §9 "Containerised forks — base-image pin discipline" capturing a fork-overlay-Docker gotcha learned in [`Wizarck/hermes-agent#6`](https://github.com/Wizarck/hermes-agent/pull/6) on 2026-05-13.

Rule: when a fork ships as `FROM <upstream>@sha256:<digest> + COPY our_source.py`, the pinned digest and the fork source tree MUST advance together during every upstream sync. Skipping the pin bump produces a container where new source files (with new imports) sit on top of an OLD base image without the modules they need → `ModuleNotFoundError` at startup.

Spec adds the rule, a 4-step recipe (merge → resolve digest → bump pin → rebuild), an applicability boundary (only for overlay forks), and a memory-retention hook tagged `upstream-sync, containerised-fork, fork-image-pin`.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.2`. No code changes required. Consumers running fork overlays (Hermes, Hindsight, Paperclip, LightRAG, ...) benefit from the vendored doc.


- **`propagate_bump.py` + `propagate_skills_bump.py` script implementation of §4.5.4 rule**: v0.11.0 codifies the rule (auto-generated bump PRs MUST pre-populate §4.5 markers); the script edits to actually emit the block in `_render_pr_body()` are deferred to a follow-up. Until then, the rule is enforced socially: a bump PR opened without §4.5 will fail the `ai-self-review-required` check and require a manual body edit.
- **Capa 2 of bump-PR safety**: `propagate_bump.py` should scan the consumer's open PRs + branches with recent activity and post a comment listing them as "potentially affected, rebase needed post-merge". Carried forward from v0.10.x.
- **`missing-application-kwarg` warn → strict ratchet**: target 2026-06-05 after 30 days of green CI. Flip pre-commit + CI to `--strict` and add runtime `LLMConfigError` in `_llm.call()` when neither `application=` arg nor `AIPLAYBOOK_APPLICATION` env is set.

## [0.13.1] — 2026-05-13 — enforcement-status row 47 refresh (Phase 1 closure docs)

Patch release. Docs-only — refreshes the `model-routing.md` row in `docs/concepts/enforcement-status.md` (line 47) to reflect post-Phase-1 reality of OpenSpec change `add-litellm-enforcement` in consumer-d. No code or behaviour change.

The row now documents: drift detector covers BOTH direct-SDK and `_llm.call(...)` missing `application=` (v0.13.0 AST check); call-site migrations CLOSED for `prompt_injection_filter.py` (v0.12.1) and `consumer-d/lib/advisor.py:_call_via_litellm` (consumer-d PR #166); application tag lands end-to-end (v0.12.0 + roster in §5 of model-routing.md); CI step `Drift detector (warn-only)` wired in test.yml on 2026-05-13; strict-mode promotion target 2026-06-05 still pending.

### Notes for consumers

- Bump submodule `.ai-playbook` to `v0.13.1`. No code changes required. The vendored copy of `docs/concepts/enforcement-status.md` will reflect the post-Phase-1 reality.

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
- To migrate a flagged call, add the canonical `application="<name>"` per `docs/concepts/model-routing.md` §5 roster, OR annotate with `# llm-routing-allow: env-fallback` if the caller relies on `AIPLAYBOOK_APPLICATION` env in its deployment manifest.

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
- **`docs/concepts/model-routing.md`** v2.1.0 — new §5 "Application tags" with canonical roster (`hermes-bot`, `dashboard-backend`, `aiops-workflow-<name>`, `prompt-injection-filter`, `lib-advisor`, `hindsight-internal`, `claude-code` reserved) + "how to add a new application" recipe + worked examples showing `consumer × application` M:M. §4 OTel attributes table gains `ai_playbook.application` and `ai_playbook.consumer` rows (the latter was implicitly required but never documented). Existing §5 "Hooks and existing code" renumbered to §6; §6 "Break-glass" to §7. Additive.
- **`docs/concepts/env-vars.md`** §Per-consumer virtual keys — new "How to add a new consumer" 7-step subsection (provider key generation → SOPS encryption → k8s sync → LiteLLM wiring → table registration → budget cap script → smoke test).
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

- **`docs/rules/migration-slot-reservation.rule.md`** (v1.0.0) — universal contract for **reserving monotonic / append-only namespace slots** across parallel slices (DB migrations, gotcha IDs, ADR numbers, seed entity IDs). Subsumes + generalises `release-management.md` §6.4.1/§6.4.2. Closes the **6-consecutive migration-slot-collision pattern** in consumer-e Wave 2-3 (R1/R2/R5/R3/T2/O2 all picked slot `0007`/`0008` independently). Validated by consumer-c-legacy m2-data-model + cost-rollup parallel m2 races.
- **`docs/concepts/protocol-fake-deferred-install.md`** (v1.0.0) — canonical **Protocol + InTreeFake + DeferredProductionInstall** pattern for isolating heavy / security-sensitive vendor SDKs. Cross-validated by 6+ consumer-e Wave 3 slices (R5/T2/R3/O2 + 2 more) + consumer-c-legacy m2-recipes-core service IoC + consumer-d ADR-018/-028 sidecar isolation. Defines the four artefacts (Protocol / fake / deferred-install row / production adapter) + cross-language guidance (Python / TypeScript-NestJS / Elixir-behaviour).
- **`docs/rules/cross-slice-additive-extension.rule.md`** (v1.0.0) — three additive shapes (nullable / `NOT NULL DEFAULT <sentinel>` / JSONB) for parallel slices extending shared entities. Drawn from 4+ consumer-e R-series slices (`dedupe_key`, `audit_trail_id`, `client_order_id`) + consumer-c-legacy m2-data-model array/jsonb columns. Codifies migration-chain discipline + read-side discipline.
- **`docs/rules/hitl-approval-pattern.rule.md`** (v1.0.0) — runtime **HITL gating for state-mutating actions** in single-operator AI systems. Cross-validated by **3 projects** (consumer-e P1 Telegram approval-channels + consumer-d ADR-028 WABA-MCP rollout gating + consumer-b operator-gated deploys). Defines the five Protocol artefacts (mutation request DTO / channel Protocol / HMAC correlation / decision persistence / TTL+escalation ladder) + a canonical 3-tier channel ladder + cross-project mutation taxonomy.

#### Tier-2 specs (MED-severity recurring patterns)

- **`docs/concepts/dependency-injection-patterns.md`** (v1.0.0) — provider deduplication (NestJS `@Global()` rule + Python `app.dependency_overrides` + Phoenix `Application.put_env` equivalents) + **seam-then-consume DI tokens** for cross-slice extension. Cross-validated by consumer-c-legacy m2-mcp-write-capabilities (`payload_before:null` bug from `@Global()` re-declaration) + m2-cost-rollup-and-audit (`INVENTORY_COST_RESOLVER` token rebinding) + consumer-d ADR-028 (action-class dispatcher dict). Includes the **class-level cache reset autouse fixture** pattern for test isolation.
- **`docs/concepts/database-numeric-boundaries.md`** (v1.0.0) — **money/decimal column boundary rule** (explicit coercion at ORM, never per-call). Surfaced by consumer-c-legacy m2-cost-rollup numeric-string-multiplication bug (`"1000NaN"` shipped to BI ingest). Per-stack recipes for TypeORM / Prisma / SQLAlchemy / Ecto. Generalises the AGENTS.md "no float for money" universal rule.
- **`docs/concepts/multi-layer-defense-single-operator.md`** (v1.0.0) — canonical **5-layer defense pattern** (L1 Identity / L2 Ingress / L3 Network / L4 State-RBAC / L5 Ergonomic) for single-operator AI systems. Cross-validated by consumer-d ADRs 017/018/019/020/024 + consumer-b `MERGE-ORDERS-SECURITY-AUDIT.md` zero-permission plugin fork. Decision matrix for when each layer is warranted.

#### Spec extensions (added sections to existing canonical specs)

- **`docs/concepts/release-management.md` §4.5.4**: codifies that **auto-generated bump / chore-archive PRs MUST pre-populate the §4.5 AI-reviewer signoff block**. Closes the v0.10.3 CHANGELOG gap surfaced 2026-05-06 by 5 failed bump PRs + 3 failed chore-archive PRs in consumer-e (PRs #90/#92/#94 all required manual body-edit roundtrips).
- **`docs/concepts/release-management.md` §6.6.1**: canonical **subagent prompt template** + mandatory verification commands contract for intra-slice parallelism. Cross-validated by consumer-c-legacy Wave 1.7-1.9 (3 subagent slices, 0 boundary violations, ~22 min/slice saved). Template at `templates/subagent-prompt.md.tmpl`.
- **`docs/concepts/release-management.md` §6.7**: **post-merge OpenSpec archive automation**. Closes the second v0.10.3 CHANGELOG gap (28h archive drift in consumer-e Wave 2 PRs #68+#69). Workflow template fires on `slice/*` PR squash-merge to main; opens `chore/archive-<id>` PR with §4.5-marker-populated body and auto-merge enabled.
- **`docs/concepts/event-and-data-patterns.md` §9**: async event-emission ordering — `tap()` vs `mergeMap+emitAsync` for read-after-write coherence + cascade self-emission guard (one-line ID equality check). Cross-stack equivalents for NestJS RxJS / Phoenix LiveView / FastAPI / Express. Cross-validated by consumer-c-legacy m2-mcp-write-capabilities + m2-cost-rollup race conditions.
- **`docs/concepts/runbook-bmad-openspec.md` §3.7.2**: **proposal-only-first** for tech-seam slices (new tech stack, architectural seams, cross-cutting infrastructure). Cross-validated by consumer-c-legacy m2-ui-foundation + consumer-e api-foundation-rfc7807. Defers design.md/tasks.md/apply until Gate D approval lands; saves rework when design is rescinded mid-apply.
- **`skills/openspec-apply-change/SKILL.md` §4b**: **preflight re-grep** of cited identifiers (class names, file paths, migration slot numbers, ADR numbers) on `main` before apply. Catches state divergence between propose and apply (proposals written days earlier may cite renamed/removed identifiers). Refuses to proceed if ≥3 identifiers drifted; warns + asks if 1-2.
- **`docs/runbooks/release.md` §10**: mandatory **first-run smoke test** for every new script / workflow / skill against ONE real consumer before rc → stable promotion. Closes the v0.10.x cascade pattern (3 hotfixes within 5 days because tests stubbed boundaries that hid environmental constraints — API limits, locale encoding, missing markers).

#### New templates

- **`templates/new-project/.github/workflows/propagate-archive.yml.tmpl`** — GH Actions workflow implementing release-management.md §6.7. Self-contained; consumers copy in + ensure `allow_auto_merge=true` is set.
- **`templates/subagent-prompt.md.tmpl`** — five-section subagent prompt template (Scope / Owns / Reads / Verification commands / Report format) per release-management.md §6.6.1.
- **`templates/k8s/serviceaccount-namespace-scoped.yaml.tmpl`** — L4 RBAC starter; default-deny + verify-by-attempted-denial pattern per multi-layer-defense-single-operator.md.
- **`templates/k8s/networkpolicy-egress-allowlist.yaml.tmpl`** — L3 egress control; DNS-aware variant for Cilium/Calico CNIs.

#### New runbooks

- **`docs/runbooks/cascade-failure-template.md`** (v1.0.0) — template runbook for **service-dependency cascade failures**. 5-section structure (symptom list / precondition check / impact map / recovery sequence / postmortem trigger). Cross-validated by consumer-d `runbook-litellm-down-cascade.md` (LiteLLM → Hindsight → Hermes → Paperclip cascade) + consumer-b gotchas.

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

- **`docs/concepts/project-board-sync.md`** — new normative spec (v1.0.0) codifying a 7-layer defense-in-depth contract for GitHub Project board sync during AI-driven OpenSpec work. L1 built-in workflows, L2 custom Actions workflow, L3 required status check (`project-board-synced`), L4 state-machine validator (gh-aw ProjectOps pattern), L5 OTLP agent telemetry, L6 companion script `--enforce-board` flag, L7 archive skill Step 0 verification. Five truly-independent layers (server-side + telemetry) plus two tool-level reinforcers. Authored after consumer-e Wave 2 retro surfaced silent board drift (slices merged with `Status=Backlog`, no audit trail). Research-grounded justifications cite OWASP AI Security Guide 2026, GitHub gh-aw ProjectOps pattern, EU AI Act forward-looking compliance, and the LLM-structured-outputs syntax-vs-semantics distinction.
- **`docs/concepts/agent-telemetry.md`** — new normative spec (v1.0.0) codifying the Claude Code OTLP exporter → Langfuse ingestion pattern. Four-environment-variable configuration, resource attributes for slice/wave tagging, OpenTelemetry GenAI semantic conventions mapping, "reuse over reinvent" default for projects with existing Langfuse instances (or Langfuse Cloud free tier as minimum-viable for greenfield consumers). Anti-patterns: standing up a custom OTel collector, inventing custom JSONL audit logs, logging traces to the project's `data/` directory, disabling telemetry "for performance".
- **`docs/concepts/event-and-data-patterns.md`** — new normative spec (v1.0.0) codifying 7 stack-agnostic patterns surfaced by consumer-c-legacy Wave 1.7-1.9 + consumer-e Wave 1-2: (1) hybrid translation pattern for cross-cutting concern extraction without forcing N upstream emitters to migrate, (2) two-name pattern (bus channel name preserves module ownership; persisted name is module-agnostic), (3) same-transaction migration with backfill, (4) `hasTable`/`hasColumn` guards on backfill SELECTs, (5) open-enum text columns + CHECK over native enums, (6) stateless proxy + stateful caller, (7) failure-collapse-to-null. Each pattern has a "when it applies", "when NOT", failure-mode-prevented, and reference implementation citation.
- **`docs/concepts/cross-language-tooling.md`** — new normative spec (v1.0.0) codifying the `tools/<name>/` peer-subdirectory convention for non-primary-language tools (Python services in TS monorepos, MCP servers in Python monorepos). Each tool has its own complete toolchain (`pyproject.toml`, ruff/mypy/pytest, Dockerfile multi-stage, `.env.example`, separate CI workflow with path filter). Anti-patterns: faking Python as a TS workspace, mixing primary-language code into `tools/`, reaching across language boundaries via filesystem. Reference implementations: consumer-c-legacy `tools/rag-proxy/` (Wave 1.8) and planned consumer-e `tools/openbb-sidecar/` (R4 slice).
- **`docs/runbooks/windows-dev-environment.md`** — new operational runbook (v1.0.0) capturing Windows-specific dev-loop gotchas: (1) `python -m venv` doesn't include pip on Windows Store Python without `--upgrade-deps`, (2) `pip install --user` is silent + glacially slow on Windows Store Python, (3) Jest workers crash with `spawn UNKNOWN errno -4094` on Windows + Node 24+ (fix: `--runInBand`), (4) `git worktree remove --force` fails "Device or resource busy" on Windows when IDE / file watcher / AV holds handles. Linux CI is unaffected; this runbook is for Windows developer pain only.
- **`templates/new-project/.github/workflows/project-status-slice-progress.yml.tmpl`** — L2 server-side workflow per project-board-sync.md. On `push` to `slice/**` populates Branch field + Base SHA + Status=In Progress on the matching project item via GraphQL; on PR opened sets Status=Review. Idempotent. Reuses existing `PROJECT_AUTOMATION_TOKEN` secret + `PROJECT_OWNER`/`PROJECT_NUMBER` vars from the existing `project-status.yml` template (which it complements, not replaces — that one handles Wave-N Blocked → Todo transitions).
- **`templates/new-project/.github/workflows/project-board-synced-check.yml.tmpl`** — L3 required status check per project-board-sync.md. Asserts (a) Status ∈ {In Progress, Review}, (b) Branch field matches PR head ref, (c) Base SHA field populated. Designed to be added to required-status-checks list in branch protection so the merge button physically blocks until board is synced. Actionable error messages name `opsx_apply_companion.py` as the fix path.
- **`templates/new-project/.github/workflows/project-state-machine.yml.tmpl`** — L4 state-machine validator per project-board-sync.md. v1 ships as periodic auditor (every 15min cron) flagging items with `Status=Done` but no merged PR. v2 will switch to native `project_v2_item.edited` webhook events once GitHub exposes them at the workflow level. Honors `break-glass` label exception per `docs/rules/break-glass.rule.md`.
- **`scripts/verify_board_state.py`** — L7 helper script per project-board-sync.md. CLI tool that queries the GH Project board via GraphQL and exits non-zero when the matching item's Status doesn't match `--expected-status`. Stable exit-code contract: `0` match, `1` mismatch, `2` item-not-found, `3` GraphQL/network error. Designed for invocation by skills (e.g. archive Step 0) where the AI's verdict is bound to a tool exit code rather than the AI's text claim (per verification-before-completion.md §4.1.2).
- **`tests/test_verify_board_state.py`** — pytest coverage for `verify_board_state.py`. 11 tests covering all 4 exit codes + CLI argument parsing. The GraphQL transport (`subprocess.run` boundary) is mocked.

### Changed

- **`scripts/opsx_apply_companion.py`** — added `--enforce-board` flag (L6 per project-board-sync.md). When set, after the existing Branch/Base SHA write, the script delegates to `verify_board_state.py` with `--expected-status='In Progress'` and propagates the exit code. Default off for backwards compatibility; new opt-in for consumers on ai-playbook v0.10.0+. Telemetry event `opsx_apply_companion.board_enforce_failed` emitted on mismatch.
- **`skills/openspec-archive-change/SKILL.md`** — added Step 0 invoking `scripts/verify_board_state.py --expected-status=Done` BEFORE any archive work. Refuses archive on non-zero exit. Cites the exit code (per `verification-before-completion.md` §4.1.2 tool-exit-code-over-text rule). Backwards-compatible: emits warning + continues if script not present (consumers on ai-playbook < v0.10.0).

### Changed

- **`docs/rules/verification-before-completion.rule.md` §4.1** — added §4.1.1 "Broadest-scope rule" (run lint/typecheck at the broadest scope CI uses, not the slice subdirectory; retro-proven by consumer-e Wave 2 P1 where 6 mypy errors in test files were invisible at the contexts/<slice>/ scope but immediately surfaced at apps/api/ scope) and §4.1.2 "Tool-exit-code-over-text rule" (verdict messages cite the tool's exit code, not paraphrase the tool's output; LLM structured outputs guarantee syntax not semantics, so AI text claims about tool results are not proof — only non-AI-controlled process exit codes are).
- **`docs/concepts/release-management.md` §4.4** — added §4.4.1 "Gitleaks scans full PR commit history" (squash + force-push to clear history when leak is fixed in a later commit but earlier commit's leak still triggers the scanner) and §4.4.2 "Markdown style guide: avoid `KEY=<placeholder>` syntax" (shell-syntax placeholder fires gitleaks generic-api-key matcher; use bullet lists or inline narrative instead). Both retro-proven on consumer-c-legacy PR #89 (`m2-wrap-up`).
- **`docs/concepts/release-management.md` §6.4** — added §6.4.1 "Append-only doc files: numbering ranges per slice" (gotchas.md, CHANGELOG.md, append-only ADR indexes require explicit numeric range per slice; recommended convention: foundation 1-29, Wave 2 bounded contexts 30-79 in 10-blocks, Wave 3 adapters 80-199 in 20-blocks). Added §6.4.2 "Migration revision strings: verbose-form from scaffold" (alembic/sqlx/prisma migrations MUST use `<NNNN>_<topic>` from scaffold; latent chain breakage retro from consumer-e Wave 2 R1/T1 mismatch).
- **`docs/concepts/release-management.md` §6.6** — refined "When it does NOT apply" guidance for intra-slice parallelism: explicitly NOT applied to slices with cross-BC verification gates (cost ↔ allergens ↔ labels ↔ audit; trading → risk → kill-switch). The serial verification path beats subagent recombination + cross-BC test orchestration overhead. Validated on consumer-c-legacy Wave 1.9 + consumer-e K1.
- **`docs/concepts/release-management.md`** — added §9.5 "Project board sync contract" cross-referencing the new `project-board-sync.md` spec; updated §10 cross-references.
- **`docs/concepts/runbook-bmad-openspec.md` §3** — added §3.7.1 "Design-mock HTML for dense designs" (optional review aid for slices spanning ≥3 bounded contexts; visual mock with arch-flow + schema cards + sample API + Gate D recap, using project's design-system palette per `ux-track.md`). Validated on consumer-c-legacy Wave 1.9 where the mock surfaced a column-name mismatch pre-implementation.
- **`docs/concepts/runbook-bmad-openspec.md` §4** — added §4.1 "Forward-authored retros" (recommended pattern: author retro DURING slice's implementation, not after merge; squash SHA + merge date filled in post-merge during the archive step; reduces after-merge cognitive drop-off; validated across consumer-c-legacy Wave 1.7-1.9 + consumer-e Wave 2).
- **`scripts/notify.py`** — warn/error path now prefers the consumer-side durable queue (Phase 5 Change B `add-durable-notification-queue`) when `CONSUMER_D_NOTIFICATIONS_QUEUE_ENABLED=1` AND a `notifications.queue` package is importable; falls through to the legacy synchronous SMTP path otherwise. The two transports are mutually exclusive per emission. Other consumers (consumer-b, consumer-c-legacy, consumer-e, livekit) continue with SMTP unchanged.
- **`scripts/prompt_injection_filter.py`** layer-2 migrated from direct `anthropic` SDK to `scripts._llm.call("safety_judge", consumer="INJECTION", ...)` per Change C P5.4 follow-up. The opt-in env var `ANTHROPIC_API_KEY_INJECTION` is preserved as a budget gate; actual provider key resolution now happens at the LiteLLM proxy via the `safety_judge` task class. Drift detector confirms 0 in-tree direct-SDK callers remain.
- **`scripts/verify_llm_routing.py`** — added Windows-safe UTF-8 stdio reconfigure so the success sigil (`✓`) prints under cp1252.
- **`docs/concepts/notification-queue.md`** — extended with §8 Durable queue layer (Phase 5 Change B): activation gate, SQLite schema, async worker model, backoff schedule, channel routing, MCP outbox tool, observability events, restart-survival contract. The legacy JSONL+SMTP layers (§3-§7) are unchanged.
- **`docs/concepts/enforcement-status.md`** — `notification-queue.md` row flipped 🟡 partial → ✅ wired with the Change B activation details.

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

- **`docs/concepts/development-flow.md`** (new) — single LLM-agnostic canonical entry point for "how do I make a change in any playbook-consuming project?". 4-level hierarchy + 3 axes of parallelism (Wave-N / Intra-slice / Worktrees) + lifecycle + LLM-agnostic pointer table + industrialisation surface + 8 anti-patterns. Decisions D1.1–D1.5.
- **`docs/concepts/merge-policy.md`** (new) — squash vs merge-commit decision rules (D2.1–D2.4). Default merge-commit; squash bounded to trivial single-intent PRs.
- **`docs/rules/conflict-resolution-policy.rule.md`** (new) — 4-tier conflict taxonomy + 5-line escalation threshold + Wave-N coordinator role + intra-slice partitioning gate (D3.1–D3.6).
- **`skills/dev-flow/SKILL.md`** (new) — orchestrator skill: `/dev-flow start <description>` scaffolds OpenSpec change + branch + worktree (when ≥3 concurrent) + auto-tick git hook; `/dev-flow ship` validates + pushes + opens PR + monitors CI. Decisions D1.1–D1.6 + 3 anti-patterns.
- **LLM-agnostic pointers wired** from `templates/new-project/AGENTS.md.tmpl` §2 (every NEW consumer inherits) + `docs/runbooks/INDEX.md` + `docs/index.md` + `docs/tutorials/01-start-here.md` + playbook root `AGENTS.md`. NOT in `~/.claude/CLAUDE.md` per LLM-agnostic principle (per repo `README.md`: "CLI-specific routers are thin pointers").
- **`docs/concepts/release-management.md`** v1.2.0 → v1.3.0 — new §0 entry-point pointer to `development-flow.md`; scopes what release-management.md adds beyond it.

#### CI gates + git hook (Followup #4 closed)

- **`.github/workflows/branch-name-validator.yml`** (new) — enforces `<type>/<change-id>` branch names (types: feat/fix/chore/docs/refactor/test/release) + verifies `openspec/changes/<change-id>/` exists. Sticky PR comments on violation. Hard gate. Exempts dependabot, GitHub-auto-revert, release-prep, and `chore/*` branches.
- **`.github/workflows/check-tasks-checkboxes.yml`** (new, Followup #4 OPT 2) — soft enforcement: scans `tasks.md` of the affected change-id, posts sticky PR comment with checked/total/pct + first 10 unchecked items.
- **`scripts/auto_tick_tasks.py`** + **`templates/git-hooks/prepare-commit-msg`** (new, Followup #4 OPT 1) — git hook auto-ticks `- [ ]` boxes from conventional-commit subjects (`groups N-M`, `§N.M`, `tasks N,M,O`). Idempotent. Depth-aware scope tracking. Soft contract: never blocks commits.
- **`.github/workflows/pr-merge-style.yml`** (new) — advisor recommending squash vs merge-commit per `merge-policy.md` decision rules. Soft (informational comment).

#### Schema cross-ref enforcement (warn-only window)

- **`docs/rules/bootstrap-directive.rule.md`** v1.1.0 → v1.2.0 — adds Development-flow cross-ref requirement: every consumer's AGENTS.md §2 Dispatcher index MUST contain a row pointing to `.ai-playbook/docs/concepts/development-flow.md`. Phased rollout (Change C pattern): warn-only initially → strict after 30d green builds.
- **`scripts/schema_validate.py`** extended — body-level check for `development-flow.md` link. `--strict-dev-flow-cross-ref` flag promotes warn → error.
- **`scripts/propagate_bump.py`** extended — `ensure_dev_flow_cross_ref()` inserts the row in each consumer's AGENTS.md §2 in the same bump PR as the version bump. Idempotent. Already-present → no-op. (= **Opción 1 migration** from `development-flow.md` §3.3.)

#### Phase 5 bring-forward (PRs #31, #32)

- **PR #32** — `scripts/wt_add.py` post-create install (npm/pnpm/poetry/uv detection, lockfile-based, failure non-fatal); `.gitignore` ignore `notifications.jsonl` + `hindsight-queue.jsonl` (runtime logs).
- **PR #31** — Phase 5 P5.4: `configs/litellm-router.yaml` (11 task classes); `scripts/_llm.py` (canonical helper, `LITELLM_BASE_URL` proxy); `scripts/verify_llm_routing.py` (drift detector, warn-only initially per D3.5); `docs/concepts/model-routing.md` v2.0.0 + per-consumer virtual keys section in `env-vars.md`. Phase 5 P5.6+P5.7: `docs/concepts/incident-response.md` stub → v1.0.0 (8 S1–S4 scenarios + on-call ladder + 7-day post-mortem detector + comm templates + 4 stub recovery runbooks); `docs/concepts/model-migration.md` stub → v1.0.0 (trigger taxonomy + 6-step playbook + canary thresholds); 2 lifecycle_check detectors (`first_paying_client_detected`, `model_retirement_detected`); 2 dry-run simulators; `configs/anthropic-retirement-list.yaml`; new 🟠 wired-pending-trigger symbol in `enforcement-status.md`.

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

- **`skills/openspec-apply-parallel/SKILL.md`** — guided skill that wraps `docs/concepts/release-management.md` §6.6 (intra-slice parallelism). Encodes the gating questions (multi-group? disjoint write-paths? >30 min? pre-allocated migration numbers?), the ownership cross-check, the spawn matrix, the parallel-spawn pattern (single-message multi-Agent calls with `isolation: "worktree"`), the cherry-pick recombination order, and the anti-patterns. Falls back to `/opsx:apply` (sequential) when the gates don't pass. Architectural note: the skill is **declarative** — there is no Python orchestration script. The agent reads the skill + invokes the existing `Agent` tool primitives (worktree mode, gh CLI, git CLI). This matches the state-of-the-art "agent-as-orchestrator" pattern (Anthropic Agent SDK, OpenAI Swarm, LangGraph supervisor); a Python orchestration script would have been an anti-pattern that encloses the LLM's judgment in fixed control flow.
- **`docs/concepts/release-management.md` §6.6 cross-reference** — the section now opens with a pointer at the new skill, so an agent reading the spec discovers the operational entry point immediately.

### Filed (open)

- **Followup 4** in `docs/concepts/v0.9.0-roadmap.md` — `/opsx:apply` skill doesn't enforce `tasks.md` checkbox-update discipline. Surfaced by consumer-e slice 3 archive (merged with 0/55 tasks ticked despite being feature-complete). Three fix options outlined: (1) conventional-commit scope → checkbox auto-tick via `prepare-commit-msg` hook, (2) PR-open warning workflow, (3) `openspec archive --strict` mode. Recommended: ship 1 + 2 in a future v0.9.x patch; defer 3.

### Notes

- This is a doc + skill release. No script changes; no test additions. Cascade behaviour identical to v0.9.1 (auto-bump AGENTS.md `inherits_from` for all 5 consumers via `bump_agents_md_pin`).

## [0.9.1] — 2026-05-01 — close v0.9.0 followups (#1 #2 #3)

Patch release that addresses the 3 followups carried into v0.9.x from the v0.9.0 stable release. Each was a real production gap surfaced during the consumer-e cascade dogfood. Now all three are fixed + covered by tests.

### Fixed

- **Followup #1 — `propagate_bump.py` now bumps `AGENTS.md inherits_from` for every consumer.** Previously only `propagate_skills_bump.py` rewrote frontmatter pins, and only for consumers with `skills_pins:` declared in `consumers.yaml`. livekit (no skills tracking) ended every cascade with stale `inherits_from:` and required a manual fix-PR each time. The `_edit_frontmatter_skills_source` helper has been moved to `scripts/_bumper.py::bump_agents_md_pin` and is now called by BOTH propagation scripts. The same regex matches `inherits_from:` items (with the `github.com/` prefix) and `skills_sources:` items (without) in one pass.
- **Followup #2 — `_bumper.supersede_open_bump_prs()` is now semver-aware.** Previously it used "newer-PR-by-creation-time wins" — when multiple tags pushed close together (rc1 + rc2 cycle 2026-05-01), workflow scheduling determined order, not semver, and v0.8.7's PRs closed the newer v0.9.0-rc2 PRs (recovery required deleting + re-pushing the rc2 tag). The function now parses the head-branch's version (`chore/bump-(playbook|skills-*)-vX.Y.Z[-rc.N]`), compares via tuple key (stable releases sort above their rcs of the same series; older series sort below newer), and only closes an open PR whose parsed version is `<=` the new bump's. Backward-compatible: callers that omit the new `new_branch` argument fall back to chronological mode + log a warning.
- **Followup #3 — `block_manual_spec_edit.py::read_commit_message()` now handles CI mode.** Previously it only read `$PRE_COMMIT_COMMIT_MSG_FILE` (commit-msg stage) and `.git/COMMIT_EDITMSG` (fallback) — but in CI's `pre-commit run --from-ref/--to-ref` mode neither is set, so every archive PR saw "commit message unavailable" and required `--admin` merge to bypass (consumer-e PR #57 was the surfacing case). The function now ALSO runs `git log --format=%B%x00 $FROM..$TO` and concatenates every commit message in the range, so the `openspec-archive:` marker is detected if it appears in ANY commit on the branch.

### Added (operational guard)

- **`docs/runbooks/release.md` Step 3** — pre-tag chronology check codified. Before tagging, verify the previous tag's `propagate-playbook-bump` workflow is `completed success` AND that `git log <prev-tag>..HEAD` is non-empty. The semver-aware supersede in `_bumper.py` is the code-side defence; this runbook step is the operational guard so devs don't rely on script correctness when tagging close together.

### Tests

- **`tests/test_bumper.py`** (new): 16 tests covering `bump_agents_md_pin` (rewrites both blocks; idempotent at-target; comments + indentation preserved; missing file / no-frontmatter detection) AND semver-aware supersede (out-of-order tag push doesn't close newer; v0.9.0 stable closes all prior rcs/series; backward-compat fallback when `new_branch` missing; unparseable open branches skipped) AND `_parse_branch_version` (rc < stable; rc number ordering; series ordering across major/minor/patch).
- **`tests/test_block_manual_spec_edit.py`** (extended): 4 new tests covering CI mode (`PRE_COMMIT_FROM_REF/TO_REF` env vars are read; marker detected in any commit of the range; local stage takes precedence; legacy `.git/COMMIT_EDITMSG` fallback still works).

### Migration

- No consumer migration required. The `bump_agents_md_pin` helper is invoked from `propagate_bump.py` automatically on every future tag push; previously-stale `inherits_from:` lines will self-heal on the next bump.

## [0.9.0] — 2026-05-01 — CodeRabbit fallback STABLE — slice 3 dogfood validated end-to-end

Promotes v0.9.0-rc1 (CodeRabbit fallback 3-layer defense) → stable after the validation milestone (`docs/concepts/v0.9.0-roadmap.md`) completed successfully on consumer-e slice 3 (`persistence-tenant-enforcement`).

### Validation evidence (consumer-e cascade 2026-05-01)

- **PR #52** (`coderabbit-fallback-l2-setup`): bootstrap dogfood. Submodule + L2 workflow installed via `docs/runbooks/onboard-new-project.md` Step 11. CodeRabbit was rate-limited at the moment of PR open (the EXACT scenario the L2 design exists for). L2 fired at 5m11s, classified `rate-limited`, posted the structured checklist as a PR comment when §4.5 was empty/stubbed, and turned `ai-self-review-required` ✅ after the PR body was updated with the 3 schema markers (`Profile:`, `Reviewer:`, `Self-review findings:`). Squash-merged into `main`.
- **PR #55** (`slice/persistence-tenant-enforcement`): L1 in-session §4.5 populated by claude-code-action; CodeRabbit reviewed without rate-limit; L2 skipped silently (status check ✅). 56 tasks / 30 new tests / 95% coverage on `persistence/*` / 154 passed combined / mypy strict clean / pre-commit clean.
- **PR #56** (`chore/ux-scaffolding-draft`): L1 in-session §4.5 populated; CodeRabbit reviewed; L2 skipped silently. Squash-merged.

The 3-layer architecture worked exactly as designed: L0 (CodeRabbit primary) handled the bulk; L1 (worker self-review) covered every PR; L2 (CI safety net) caught the rate-limit case on PR #52 without false positives on the others.

### Changed (since v0.9.0-rc3)

- **`templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`**: add `token: ${{ secrets.CONSUMER_D_GOD_MODE }}` to `actions/checkout@v4` step. Required when the consumer pins `.ai-playbook` (and optionally `.skills-sources/ai-playbook`) as submodules of the PRIVATE `Wizarck/ai-playbook` repo. The default `GITHUB_TOKEN` scope is consumer-repo only; cross-repo submodule clone needs `Contents:R` on the playbook + skills repos. Mirrors `ci.yml`. Caught during PR #52 dogfood; consumer-e's runtime workflow was patched in-PR. Per gotchas #7. Followup tracked from v0.9.0-rc1 closed.

### Added (since v0.9.0-rc3)

- **`docs/concepts/release-management.md` §6.6 Intra-slice parallelism** (originally landed under "Unreleased" between rc3 and stable): orthogonal to wave-level (§6.4). Codifies how a main agent spawns subagents inside one slice when the slice covers multiple disjoint bounded contexts. Pre-conditions (write-path ownership in `tasks.md`, migration-number pre-allocation, shared-file reservation), spawn pattern (`Agent isolation: "worktree"` with ephemeral side-branches `slice/<id>--<group>`), recombination via cherry-pick, anti-patterns (cross-ownership edits, public-branch pushes), and the cost-benefit threshold (~30 min of parallelisable work).
- **`docs/concepts/runbook-bmad-openspec.md` §3.8**: brief pointer to §6.6, distinguishing intra-slice from wave-level parallelism.

### Open followups (carried into v0.9.x)

- **`scripts/propagate_bump.py`**: doesn't bump `AGENTS.md` `inherits_from` field on consumers. Manual fix in livekit PR #36 surfaced this. Filed in `docs/concepts/v0.9.0-roadmap.md`.
- **`scripts/_bumper.py` supersede logic**: uses tag-push chronology, not semver order. Out-of-order tag push superseded newer PRs with older ones during the v0.9.0-rc1/rc2 cycle. Filed in `docs/concepts/v0.9.0-roadmap.md`.
- **`/opsx:apply` skill**: doesn't enforce tasks.md checkbox-update discipline. Slice 3 implementation merged with 0/55 boxes checked despite being feature-complete (verified by tests + coverage). To file as a v0.9.x followup.

## [0.9.0-rc3] — 2026-05-01 — bare-repo + per-branch worktree layout (default for new consumers)

Codifies the directory layout senior-developer practice (Cugerone, Medeski, ChristopherA) recommends for projects that ship in waves of 5–10 concurrent OpenSpec slices. The implicit pre-v0.9.0 default (single working tree at `<repo>/`) saturated in consumer-c-legacy Module 2 (11 concurrent changes); the new layout makes every change-id a peer subdirectory under one parent, sharing one `.bare/` git database.

Existing consumers on the legacy single-tree layout keep working — migration is opt-in via the new runbook §3.

### Added

- **[`docs/concepts/git-worktree-bare-layout.md`](docs/concepts/git-worktree-bare-layout.md)** (v1.0.0): the layout contract — directory shape, naming rules (worktree dir == OpenSpec change-id), invariants I1–I5, rationale (bare+per-branch vs sibling-suffix vs centralised pool), tooling pointers, registry compatibility. Cross-references `dispatcher-chain.md` and `release-management.md`.
- **[`docs/runbooks/git-worktree-bare-setup.md`](docs/runbooks/git-worktree-bare-setup.md)** (v1.0.0): operational runbook covering 4 scenarios — §1 greenfield bootstrap, §2 onboard existing repo, §3 migrate from legacy single-tree, §4 daily flow (add/remove worktrees). §3.5 documents the Windows cwd-lock workaround (rename a project root locked by an open editor session).
- **[`scripts/wt_add.py`](scripts/wt_add.py)** (~280 LOC): one-command worktree creation. Auto-detects default branch via `origin/HEAD`; refuses change-ids without a matching `openspec/changes/<id>/` folder unless `--no-slice-check`; initialises submodules in the new worktree by default. Dry-run mode.

### Changed

- **`docs/concepts/runbook-bmad-openspec.md`**: new §3.7 "On-disk layout for concurrent slices" cross-references the new spec + runbook + script. §3.6 (branch + PR + merge contract) unchanged — the layout sits **under** the existing 1 branch = 1 change = 1 PR rule.
- **`docs/runbooks/INDEX.md`**: new row pointing at `git-worktree-bare-setup.md`.
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
- Process gotcha: when a fix-PR merges to main between the tag-cut and the propagation-finish window, it falls between two semver releases. Mitigation idea for v0.9.x: a pre-tag check in `docs/runbooks/release.md` Step 3 that diffs `git log origin/main..HEAD` and aborts if there are uncommitted-into-tag fixes. Filed as a follow-up; not blocking rc2.

## [0.9.0-rc1] — 2026-05-01 — CodeRabbit fallback (3-layer defense)

Codifies the manual Profile-B fallback the worker AI applies when CodeRabbit is rate-limited or silent. Turns it into a 3-layer defense (L0 mechanical / L1 in-session AI / L2 GH Action safety net) with L1 ↔ L2 coordination via PR-body §4.5 regex check. See [`docs/concepts/v0.9.0-roadmap.md`](docs/concepts/v0.9.0-roadmap.md) for the design rationale (incl. 4 alternatives considered + tradeoff analysis).

### Added

- **L1 — `scripts/check_coderabbit_status.py`** (~80 LOC): polls `gh pr view --comments` for CodeRabbit; classifies into `available` / `rate-limited` / `silent` / `error`. Returns JSON on stdout + exit codes (0/1/2/3). Pure stdlib + `gh` CLI; no API token.
- **L1 — [`docs/runbooks/coderabbit-fallback.md`](docs/runbooks/coderabbit-fallback.md)**: structured guide for the worker AI when L1 fires. 7-category diff inspection (type / async / errors / security / edge cases / public API / spec compliance) + canonical §4.5 schema + 5 anti-patterns + reference run (consumer-e PR #41).
- **L2 — `scripts/post_self_review_checklist.py`** (~280 LOC): reads PR diff + body; if §4.5 is populated (3 markers + non-stub), exits silently and marks status check ✅; if empty/stubbed, posts a structured fallback checklist as a PR comment + marks status check ❌. Markdown bold (`**Profile**:`) is normalised to plain (`Profile:`) before matching.
- **L2 — `templates/new-project/.github/workflows/coderabbit-fallback.yml.tmpl`**: GH Action (`pull_request: [opened, synchronize]`). Sleeps 5 min, runs detection + checklist scripts. Skips dependabot/renovate/github-actions PRs. `secrets.GITHUB_TOKEN` only — no PAT.
- **`scripts/bootstrap_gh_project.py`**: `apply_profile()` now copies the new workflow under both Profile A and Profile B (the L2 status check is informational unless added to required-checks manually). Helper: `write_coderabbit_fallback_workflow()`. Idempotent; "delete to refresh" semantics.
- **Tests**: 46 new tests (20 for `check_coderabbit_status` + 26 for `post_self_review_checklist`) covering happy paths, error paths, edge cases. All green.

### Changed

- **`docs/concepts/release-management.md`**: 3 new subsections under §4.5 — §4.5.1 (L1 worker-AI in-session check, MUST after every PR push), §4.5.2 (L2 CI safety net + ai-self-review-required status check semantics), §4.5.3 (PR-body schema regex contract: 3 mandatory markers + STUB_INDICATORS exclusion list). All additive — existing §4.5 unchanged.
- **`docs/runbooks/release.md`** Step 7: replaces generic "wait for CodeRabbit" with explicit `check_coderabbit_status.py --pr ... --wait 300` invocation + Profile B fallback path; clarifies how L1 ↔ L2 interact on bump PRs. Step 8 mentions that bootstrap re-run now propagates the L2 workflow.
- **`docs/runbooks/onboard-new-project.md`** Step 11: adds `coderabbit-fallback.yml` to the manual `cp` list with note that `bootstrap_gh_project.py` copies it automatically (v0.9.0+).

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

Extends `docs/concepts/ux-track.md` con tier 1 adoptions de [google-labs-code/design.md](https://github.com/google-labs-code/design.md) (Apache-2.0, alpha, 10.5k stars). DESIGN.md becomes hybrid format: machine-readable YAML frontmatter tokens + human-readable markdown rationale.

### Added

- **`docs/concepts/ux-track.md` §11 — DESIGN.md format spec** (NEW section, 175 lines). Subsections:
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

- **`docs/concepts/ux-track.md` §10 OKLCH-canonical rule** — added "Dual representation" paragraph cross-referencing §11.7. The CSS surfaces declare OKLCH canonical; YAML frontmatter declares hex computed equivalents. OKLCH remains source-of-truth; hex is one-way derivation snapshot. Tooling consumers MUST NOT round-trip hex → OKLCH.

- **`docs/concepts/ux-track.md` §11..§19 renumbered to §12..§20** (per-journey docs format → §12, Components catalogue → §13, ...). Internal §-references updated atomically.

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

- **`docs/runbooks/release.md` v1.1.0**: adds rc-first mode for breaking
  releases; adds Step 7 "AI-reviewer signoff per consumer" and Step 8
  "post-merge bootstrap re-run with `--profile auto`"; adds Quick-
  reference flow diagram for the post-v0.8.x release sequence;
  documents supersede behavior in Step 6.

- **`docs/runbooks/onboard-new-project.md` v1.1.0**: adds Profile A/B
  decision matrix as a "decisión previa"; adds Step 7 "Bootstrap GH
  Project + Profile A/B enforcement"; adds Step 8 "Install CodeRabbit
  GH App" (Profile A only); adds Step 9 "Configure CONSUMER_D_GOD_MODE
  secret" for private-submodule CI; adds Step 11 "Copy auto-transition
  + dep-check workflow templates"; refreshes cross-references with new
  scripts + templates.

- **`docs/runbooks/propagate-bump-troubleshooting.md` v1.1.0**: adds
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

- **`docs/concepts/release-management.md` v1.2.0**:
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

- **`docs/concepts/release-management.md` v1.1.0** (PR #13):
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
- **`docs/concepts/release-management.md` §5.4** new subsection covering the
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

- **`docs/concepts/release-management.md`** v1.0.0 — defines the universal contract for how OpenSpec changes ship: 1 branch = 1 change = 1 PR (tasks tracked as PR checklist, never per-task branches), Status field schema with five canonical options (`Todo`, `Blocked`, `In Progress`, `Review`, `Done`), recommended `Risk` + `P&L impact` custom fields, CI-green-required-for-Review transition, dependency-driven merge order (Wave N before N+1), bootstrap-via-script (§7), migration path for existing consumers (§8), anti-patterns (§9). Complements `issue-tracking.md` v1.0.0 (which already automates ticket↔proposal sync) on the source-control side.
- **`scripts/bootstrap_gh_project.py`** — one-command setup for a consumer's GH Project board: looks up project, adds canonical Status options idempotently (preserves existing names; flags case-only divergence as a soft warning), adds recommended custom fields (`Risk`, `P&L impact`), and (with `--slicing-file`) creates one draft project item per change row from `docs/openspec-slice.md` with initial Status set per dep graph. Stdlib-only (subprocess + json + urllib not used; just `gh api graphql`). Idempotent.

### Updated — runbook v1.1.0

- **`docs/concepts/runbook-bmad-openspec.md` §3.6** — new section, "Branch, PR + merge contract", points at `release-management.md` for the normative source-control contract. One-paragraph summary in the runbook for skim-readers; full detail in the spec.
- **`docs/concepts/runbook-bmad-openspec.md` §5** — Gate F row now mentions "CI green on slice branch" as prerequisite (was implicit before).
- **`docs/concepts/runbook-bmad-openspec.md` §6** — cross-refs add `release-management.md` + `issue-tracking.md`.

### Validated against

- **consumer-e (Wizarck/consumer-e)** — bootstrap of GH Project #2 successful in dry-run mode (3 status options already aligned, 2 added: `Blocked`, `Review`; both recommended custom fields already present; 20 slice rows parsed; 20 draft items would be created). Real run pending v0.8.0-rc1 merge to playbook main + consumer-e bump.

### Roadmap

- v0.8.0 stable promotion: after consumer-e Wave 0 (slices 1-3) lands, retro confirms the contract works under load. Items 1-10 from `docs/concepts/v0.8.0-roadmap.md` are still tracked separately; this RC is **scoped only** to release management.
- Optional follow-ups (not blocking v0.8.0 stable):
  - GH Action template `.github/workflows/project-status.yml` for auto Status transitions (commit-passing-CI → Review; squash-merge → Done; downstream-deps-merged → Blocked-to-Todo). Doc placeholder in spec §6.3; implementation deferred.
  - Optional hard dependency-check workflow `.github/workflows/dep-check.yml` per spec §6.2.

## [0.7.1] — 2026-04-29 — apply-fix contract (Phase 5 bring-forward)

Adds the `apply-fix-contract.md` spec — the canonical contract any workflow MUST honor when mutating prod state via human-in-the-loop approval. Lifts the propose-only ceiling that previously kept all `langgraph-aiops/workflows/*.py` write paths blocked behind `NotImplementedError("APPLY_FIX mode deferred to T29")`. Sibling to `break-glass.md`; different audiences (CLI gate overrides vs workflow mutation contracts).

### Added

- **`docs/rules/apply-fix-contract.rule.md`** v1.0.0 — two-tier permission model (autonomous tier for `watchdogs.py`-class auto-mutators, HITL-gated tier for everything else), envelope shape (`command_preview`, `idempotency_key`, `reversal_hint`, `risk`, `mode`, `max_approval_age_seconds`), exact-match invariant (bytes-of-action MUST equal approved bytes), idempotency contract (workflows requesting `mode="apply"` MUST supply a precheck callable), identity binding rule (env-bound approvers; rejection logged not silently dropped), risk-tier rule (`risk=high` always HITL even on cron), Python helper API (`request_approval`, `verify_apply_safety`, `record_apply_outcome`), structured logging contract (rows to `incidents.jsonl` with `request_id` correlation).

### Stale references retired (in consumers)

- The strings `"T29"` and `"break-glass.md §propose-only ceiling"` no longer appear in any new code authored against v0.7.1+. The `§propose-only ceiling` section never existed in `break-glass.md`; the citation was a forward-reference to a milestone that was never scheduled. Consumers updating to v0.7.1 should also update their own `langgraph-aiops/workflows/hitl.py` and `langgraph-aiops/consumer-d_ops/tools.py` to drop the `NotImplementedError("APPLY_FIX mode deferred to T29")` guards and reference `apply-fix-contract.md` instead. consumer-d lands this companion change in its own commit (Change A Phase 1).

### Notes

- v0.7.1 is **additive** — no existing spec is modified, no contract is broken. v0.7.0 consumers can adopt at their own pace.
- The companion code refactor (replacing the `NotImplementedError` guards in `hitl.py` and `tools.py`) lives in consumer-d, not in this repo. The v0.7.1 bump in consumers via `propagate-playbook-bump.yml` opens the playbook-pin PR; the consumer-d code refactor is a separate consumer-d commit gated by the new pin.
- Phase 5 background: the `apply-fix-contract.md` spec, the consumer-d code refactor, and the upcoming HITL channel adapters (Telegram + WhatsApp via wa-mcp + Hermes), durable notification queue, LiteLLM enforcement, and incident-response/model-migration spec completion are tracked in `consumer-d/docs/openspec-slice-phase5.md` as 4 OpenSpec changes (one of which — `add-hitl-channels-and-apply-fix` — authored this v0.7.1 spec).

## [0.7.0] — 2026-04-28 — alignment + bridges + audit incorporation

Major hardening of the BMAD↔OpenSpec hybrid flow. v0.7.0 closes the seam between Phase 2 (BMAD discovery + design) and Phase 3 (OpenSpec implementation), incorporates two patterns from external skill audits, adds a soft-warn lint for SKILL.md description quality, and records a roadmap of items deferred to v0.8.0. Additive against v0.6.x; existing consumers may migrate at their own pace.

### Added — Phase 2 → Phase 3 bridge

- **`docs/concepts/bmad-openspec-bridge.md`** v1.0.0 — defines the canonical slicing artefact (`docs/openspec-slice.md`) that BMAD writes at Gate C and `openspec-propose` reads at the start of Phase 3. Resolves the v0.6.x drift where the Phase 2 → 3 handoff was implicit. Also settles the `docs/` (canonical) vs `_bmad-output/planning-artifacts/` (workflow trail) path-canon split with explicit rules.
- **`templates/openspec-slice.md.template`** — copyable starting point for the slicing artefact. Schema includes change-ID table (with bounded context, FRs, journeys, components, dependencies) plus per-change scope notes (copy-paste-quality prose, no `<TBD>` placeholders).

### Added — Cross-cutting discipline specs (lifted from external audits)

- **`docs/rules/output-completeness.rule.md`** v1.0.0 — anti-skeleton-output rules. Bans `// TODO`, "for brevity", placeholder skeletons, ellipses-as-substitute, and self-narration. Defines the deferral protocol (the only legitimate exit) and the PAUSED check-in pattern. Pattern adopted from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)'s `output-skill`; adapted for the hybrid flow.
- **`docs/rules/verification-before-completion.rule.md`** v1.0.0 — iron law: no claim of completion without fresh verification output in the same message. Defines what "fresh verification" means (after the work, observable output, specific to the claim) and the synthesis-claim exception for non-code artefacts. Pattern adopted from [obra/superpowers](https://github.com/obra/superpowers) (MIT, © Jesse Vincent); adapted for the hybrid flow.

### Added — Verdict vocabulary

- **`verdict-contract.md` v1.1.0** — adds 4th canonical verdict literal **`⛔ ARCHITECTURE QUESTIONED`** for the case where repeated rework reveals a structural design issue rather than an implementation gap. Distinct from `❓ CLARIFICATION NEEDED` (spec ambiguity) — `⛔` is when the spec is clear but the design that satisfies it isn't viable. Triggers `blocked-by-architecture` lifecycle state and an architect-level review (human or `bmad-agent-architect`). Punctuation note added: `⚠️ ISSUES FOUND (iter N)` uses a SPACE (not underscore) — caught during the v0.7.0 audit.

### Added — SKILL.md schema + lint

- **`skills-distribution.md` §1** — required SKILL.md sections updated. `## Anti-patterns` and `## Verification` sections are now part of the canonical schema for skills authored or revised under v0.7.0+. Existing skills migrate opportunistically (no flag day); new skills MUST conform. Description-field rule (CSO — "command-style operations") added: descriptions tell the LLM **when** to invoke the skill, not what it does internally.
- **`scripts/check_skill_descriptions.py`** — soft-warn lint that flags descriptions matching summary-verb / workflow-mechanics patterns or missing when-to-use indicators. Default mode is warning-only (exit 0 even with findings); `--strict` exits non-zero for CI use. 14 tests in `tests/test_check_skill_descriptions.py`.

### Updated — runbook

- **`runbook-bmad-openspec.md` §2.4** — slicing now produces the canonical artefact at `docs/openspec-slice.md`; path-canon split made explicit.
- **`runbook-bmad-openspec.md` §3.1** — `/opsx:propose` reads the slicing artefact and supports `--batch` mode for many-change modules. Workers in `/opsx:apply` cite `verification-before-completion.md` for verdict emission and `output-completeness.md` for deliverable shape. `openspec archive` chains a retro write to `retros/<change-id>.md` automatically.

### Roadmap

- **`docs/concepts/v0.8.0-roadmap.md`** v0.1.0 — records design objectives + work items deferred from v0.7.0 to v0.8.0. Highlights:
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
- **`scripts/issue_sync.py`** — replaced the implicit "private repo → Jira fallback" heuristic with a **declarative `tracker_kind` field** read from `consumers.yaml`. The previous flow had two latent failure modes: (a) any consumer name not in `CONSUMER_B_PROJECTS` fell silently to `consumer-a`, regardless of whether a Jira project should exist for it; (b) `gh` CLI unavailability triggered the Jira branch even for GH-only consumers. Both are gone. `decide_surface` now raises `RuntimeError` for any active consumer without a valid `tracker_kind` instead of silently picking a default. The class of drift the v0.6.0 PR caught (tests asserted `consumer-b`, code returned `consumer-a`) cannot recur.
- **`scripts/release_cut.py`** — the Jira-fixVersion path now reads the project key via the new `issue_sync.jira_project_for(consumer_root)` public helper (registry-driven). The private `_jira_project_for(name)` heuristic was removed.

### Added

- **`tracker_kind` field** in `consumers.yaml` schema (`github | jira`, required for active consumers). When `jira`, `jira_project` is also required.
- **`tests/test_consumers_yaml.py`** — schema validation that runs on every CI build. Asserts every active consumer declares `tracker_kind`, every `jira` consumer has `jira_project`, and the status / repo / default_branch fields are present. The committed registry is the test target — drift between code and registry fails CI, not after-the-fact.
- **`AIPLAYBOOK_CONSUMERS_YAML`** environment override for tests / vendored consumers.
- **`issue_sync.jira_project_for(consumer_root)`** public helper for callers that need the Jira project key directly.

### Removed

- `scripts/issue_sync.py` private constants `CONSUMER_B_PROJECTS`, `CONSUMER_A_PROJECTS`, and `_jira_project_for(consumer_name)` function — replaced by the registry lookup.
- `tests/test_issue_sync.py::test_jira_project_for_names` (function deleted).
- `tests/test_issue_sync.py::test_decide_surface_private_falls_back_to_jira` (asserts behaviour that should not exist — there is no silent fallback to Jira).

### Notes

- All 5 active consumers default to `tracker_kind: github` in this release. The registry comment documents how to flip a consumer to Jira (set `tracker_kind: jira` + `jira_project: <KEY>`).
- The propagation loop will open auto-bump PRs across the 5 consumers; the runtime behaviour is identical for all of them (everyone was already on GH path before, so this is a structural cleanup with no behaviour change for current consumers — just defence against future drift).

## [0.6.0] — 2026-04-27 — UX Track v2: three-step order, palette decoupling, OKLCH-canonical, components catalogue

Substantial expansion of the UX Track from v0.5.0's framing into operational rules, based on consumer learnings (consumer-c-legacy Module 2 UX track). Additive against v0.5.0; existing consumers may migrate at their own pace.

### Added

- **`docs/concepts/ux-track.md` v2.0.0** — rewritten and expanded. New sections:
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
- **`docs/concepts/runbook-bmad-openspec.md` §2.3** — expanded UX Track summary inline (the three steps + Phase A/B + OKLCH discipline) so the runbook is self-explanatory without requiring a jump to ux-track.md for the high-level shape.
- **`skills/bmad-create-ux-design/workflow.md`** — rewritten to invoke the three-step order explicitly, point at the templates, and require: parallel agent fan-out at step 3, OKLCH declarations, internal-only citations, WCAG-AA verification block in the audit.

### Changed

- **Gate B verification checklist** in `runbook-bmad-openspec.md` §2 expanded to include: DESIGN.md ↔ ADR data-shape consistency, every PRD journey has a mock or design-intent doc, components catalogue matches journey usage, no engine references leaked into canonical artefacts after scrub.

### Removed

- **`docs/concepts/ux-track.md` §6.1 License compliance** (from v1.0.0). Was scaffolding; replaced with a one-line "consumers must check each engine's licence against their own project's licensing constraints" in the curated-engines table. Engines are referenced, never vendored — licensing remains the consumer's responsibility for their own use case.

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

- `docs/concepts/ux-track.md` (v1.0.0) — full spec for the UX Track: position in
  workflow, artefacts (`docs/ux/DESIGN.md` 9-section format + per-journey
  files + components.md), Storybook-first component-library curation pattern,
  design-review trigger for non-trivial components, QA discipline mirroring
  [parallel-review.md](docs/concepts/parallel-review.md), and curated external-skill
  recommendations.
- Curated third-party skill recommendations (not vendored — distribution per
  RFC-0001): pbakaus/impeccable + Leonxlnx/taste-skill (drop-in),
  nextlevelbuilder/ui-ux-pro-max-skill (adapt), VoltAgent/awesome-design-md
  (inspire-from / format pattern), modstart-lib/skillui (skip).

### Changed

- `docs/concepts/runbook-bmad-openspec.md` — phase map updated to show UX Track in
  parallel with Architecture; new §2.3 cross-references [ux-track.md](docs/concepts/ux-track.md);
  Gate B now waits on both Architecture and UX (HITL summary updated). Headless
  / API-only consumers declare `no-ui-consumer` in `docs/ux/README.md` and skip
  the UX gate.

### Compatibility

- **Backward-compatible** for consumers shipping a UI: their existing UX work
  (if any) needs to be expressed in the new `docs/ux/` layout. Per
  [contributing.md](docs/concepts/contributing.md) §6, deviations from the recommended
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
- `docs/concepts/skills-distribution.md` — formal contract for the new distribution
  surface (canonical layout, pinning model, materialisation algorithm, drift
  detection, propagation, fallback, security, KPIs).
- `docs/runbooks/skills-version-bump.md` — maintainer procedure for cutting a tag
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

- `docs/concepts/skills-registry.md` bumped to v2.0.0: scope clarified to
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
  pass per `docs/runbooks/skills-version-bump.md` smoke recipe.
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
- `docs/runbooks/onboard-new-project.md` — canonical one-page procedure: `gh repo create` → `bootstrap.py --register-in <playbook>` → 3 placeholders in AGENTS.md → 2 commits → done. Covers SOPS path overrides, rollback, and the verification suite.

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

- `docs/concepts/enforcement-status.md` — full matrix of every spec with one of
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
- `docs/rules/bootstrap-directive.rule.md` — rewritten to reflect SessionStart-hook
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
- `docs/runbooks/rotate-secrets.md` §"Fine-grained PAT scope" — explicit GitHub UI fields (token name, description, resource owner, expiration, repos-to-select, exact permission grants).

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
- `docs/runbooks/hindsight-retain.md` — when to retain, how to invoke, sanitisation contract, degraded-mode replay, verify-it-landed.
- `consumer-c-legacy/.claude/settings.json` + `consumer-d/.claude/settings.json` — SessionStart hooks invoking `inject_context.py` with the project bank id (timeout 60 s).
- `consumer-c-legacy/mcp-servers.yaml` (project layer, schema mcp-servers/v1) + rendered `consumer-c-legacy/.mcp.json` + `consumer-c-legacy/.gemini/settings.json` (11 servers from base+project layers; personal layer excluded since consumer-c-legacy is public AGPL).

### Changed

- `scripts/inject_context.py` — recall now goes through `_hindsight.post_recall` against the real API path `/v1/default/banks/{bank_id}/memories/recall` with CF Access headers. Bank id rides in URL, not body. Maps `top_k` → `max_tokens` (~800 tokens per top_k unit). 21 tests pass.
- `docs/concepts/env-vars.md` §HINDSIGHT_* — replaced bearer-only contract with the real auth resolution order: CF Access pair preferred, bearer fallback. Documents the 45 s timeout and queue file.
- `docs/concepts/memory-hierarchy.md` §5 — added the canonical retain CLI invocation as the lead bullet.
- `docs/concepts/session-start-hook.md` — bumped hook timeout from 15 s to 60 s; updated command to use full path + `--bank-id <slug>`.

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
- `docs/concepts/dispatcher-chain.md`, `docs/rules/bootstrap-directive.rule.md`, `docs/tutorials/03-bootstrap-new-project.md` — 3 real v0.1.0 stubs closed to full v1.0.0 content.
- `schemas/schema-agent-contract.json` — JSON Schema file extracted from the spec prose (was "stub pending T06 follow-up"); now the authoritative validation target.
- README.md — full directory map (35 specs, 24 scripts, templates, docs, routers, rfcs, tests) + 4 persona getting-started paths + honest status.

### Changed
- 36 spec/doc Status headers normalized — dropped confusing `Populated in **T14b**` provenance phrases that read like TODOs.
- 13 in-prose "stub" references inside v1.0.0 specs resolved (scripts they pointed at are fully populated).
- `scripts/_break_glass.py` — wires `ai_playbook.override.*` OTel span via `trace_emit.override_attrs` (no-op safe when OTel absent). Removes the stale T07c TODO.
- `scripts/mcp/validate.py` — stale "wire through _break_glass" TODO removed (the wiring already existed).
- `docs/tutorials/02-quickstart.md`, `docs/tutorials/04-quickstart-lessons.md`, `docs/tutorials/01-start-here.md`, `AGENTS.md` — outdated "bootstrap.py is a stub" warnings replaced with real usage.

### Notes
- Deferred-by-design items (not addressed here, not stubs):
  - `docs/concepts/incident-response.md` activates at first paying client.
  - `docs/concepts/model-migration.md` activates at first pinned-model retirement.
  - `docs/concepts/notification-queue.md` full spec is T25+ (Phase 5).
- Consumer pins today: consumer-c-legacy + consumer-d still at v0.1.0. The propagation loop above will open bump-to-v0.2.1 PRs on tag push; humans merge per propose-only HITL convention.

## [0.2.0] — 2026-04-23 — MVP complete (T01–T23)

### Added (Batch 10 — governance + upstream sync, 3 parallel subagents)

**Subagent A — T22a/c/d/e/h/i governance docs + bootstrap (ai-playbook):**
- `docs/concepts/incident-response.md` — deferred IR placeholder; activation triggers named.
- `docs/concepts/role-matrix.md` — 4-role matrix + deferred k8s RBAC mapping.
- `docs/concepts/data-retention.md` — retention table (10+ rows), deletion paths, GDPR-adjacent anonymisation.
- `docs/concepts/post-mortem.md` + `templates/post-mortem.md.tmpl` — S1/SYSTEMIC trigger, 7-day due, required outcomes, 7 anti-patterns.
- `scripts/bootstrap.py` (~534 lines, **full impl replacing stub**) — submodule add + pin, template copy with placeholder substitution, `--personal`, `--dry-run`, `--playbook-path` offline fallback via break-glass.
- `scripts/deprecation_watcher.py` (~446 lines) — scans registry consumers + playbook for v0 schema, env-alias leaks, deprecated MCP IDs, stale lifecycle reports. `--strict`/`--json` modes; reads optional `specs/deprecations.yaml`.
- `tests/test_bootstrap.py` (28 tests; **skip removed**) + `tests/test_deprecation_watcher.py` (18 tests).

**Subagent B — T22f/g/j/k governance ops (ai-playbook):**
- `docs/concepts/slos.md` — 8 SLOs with monthly review cadence + RFC escalation.
- `docs/concepts/rollout-strategy.md` — 5-phase announcement path, 1-minor-cycle OR 90-day deprecation window, emergency security bypass.
- `docs/tutorials/05-curriculum.md` — 4-week dev learning path (Operator / Reviewer / Contributor / Maintainer candidate) with exit criteria.
- `docs/concepts/channels.md` — solo-state + 8-row channels-by-purpose table + team-growth path + anti-patterns.

**Subagent C — T23 upstream sync (ai-playbook + consumer-d):**
- `docs/concepts/upstream-sync.md` + `templates/PATCHES.md.tmpl` + `docs/tutorials/07-fork-inventory.md` (with `TODO: clarify` on 4 upstream URLs).
- `scripts/upstream_sync.py` (~528 lines) — local inspection tool, `list`/`status`/`refresh`/`mark-merged` subcommands. Refresh is propose-only — no auto-merge.
- `tests/test_upstream_sync.py` — 20 tests.
- `consumer-d/langgraph-aiops/workflows/upstream_refresher.py` (~538 lines) — weekly LangGraph workflow; propose-only, gated by `hitl.request_approval`; decision log written to `reports/upstream-refresh/`.
- `consumer-d/tests/test_upstream_refresher.py` — 20 tests.

### Test suite totals (MVP close)

- **ai-playbook: 425 passed, 0 skipped, 0 failures** (359 previous + 66 new from Batch 10A+C; `test_bootstrap.py` finally unskipped).
- **consumer-d: 92 passed** (72 previous + 20 new from upstream_refresher); 2 pre-existing failures in `lib/test_advisor.py` that require live `ANTHROPIC_API_KEY` (unrelated to Batch work).
- **consumer-d-skills: no test suite yet.**

### Open TODOs remaining at v0.2.0

- Upstream URLs for 4 forks (hindsight/hermes/paperclip/lightrag) — Arturo to confirm in `docs/tutorials/07-fork-inventory.md`.
- `Last rebase` timestamp convention in `PATCHES.md` — default ISO-8601; flagged in `docs/concepts/upstream-sync.md`.
- T18 LangGraph workflows (Batch 8B) — NOT deployed; Arturo runs `consumer-d/docs/operations/deploy-t18-workflows.md` (5-step Blindar aiops procedure) to activate on VPS.
- T19 Dashboard (Batch 9A) — deploy helm/consumer-d-stack/ manifest; 5-step runbook.
- `consumer-d-skills` HTTP service — only the API contract is spec'd (Batch 9B `docs/api-contract.md`); the service itself is future work.
- IR runbook (Batch 10A `docs/concepts/incident-response.md`) — deferred until first paying client.
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
- `docs/concepts/skills-registry.md` — purpose, API contract, scope model, caching, fallback, security, cross-refs.
- `docs/concepts/mcp-servers-schema.md` — expanded from 28-line stub to 249-line full spec (3-layer merge, field contract, skills-registry deep dive, validator/render rules, anti-patterns).
- `docs/concepts/env-vars.md` — added `SKILLS_REGISTRY_*` table.
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
- `docs/concepts/auto-managed-sections.md` — marker format, source shapes, merge strategy, anti-patterns.
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
- `docs/tutorials/04-quickstart-lessons.md` fully populated with Windows timings + 4 real friction points. Total wall-clock ~18 min (inside 25–40 min quickstart band).

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
- `docs/tutorials/01-start-here.md` — 1-pager (3-level dispatcher ASCII, first 5 commands, needs→file routing).
- `docs/tutorials/02-quickstart.md` — 8-step honest 25–40 min walkthrough for `acme-shop` with per-step time budget + "what can go wrong" sub-sections.
- `docs/tutorials/04-quickstart-lessons.md` — empty per-OS skeleton ready for T15 dry-run findings.
- `FEEDBACK.md` — formalised: format, triage cadence, 3 good-gripe examples, 3 anti-patterns.
- `docs/concepts/notification-policy.md` — 4 levels, rate limits, channel contract, per-event policy table (14 events).
- `docs/concepts/contributing.md` — 4-role matrix, RFC 7/30/90-day SLAs, code style + test discipline + backwards-compat (full governance lands T22).
- `templates/retro/{post-archive,weekly,monthly}.md.tmpl` — retro templates per cadence.
- `docs/concepts/retrospective-cadence.md` — 3 cadences, template mapping, output layout, automation contract for `lifecycle_check.py`, 4 anti-patterns.

### Test suite totals (Batch 5 close)

- **269 passed, 2 skipped, 0 failures** (205 previous + 64 new for doctor/cost/lifecycle).
- Remaining skip: `test_bootstrap.py` (T14a — bootstrap.py stub, NOT populated this batch; deferred to a future track).

### Open TODOs surfaced

- `cost_report.py` `--period` is a default-window shortcut, not full calendar bucketing — flagged for T19 dashboard consumer to confirm before integrating.



### Added (Batch 4 — project workflows)

**T11 — Runbook BMAD + OpenSpec:**
- `docs/concepts/runbook-bmad-openspec.md` (canonical universal runbook — 6 HITL gates A..F, phase map, BMAD Discovery artefacts + gates, OpenSpec per-artefact sequence, max-2-rework, self-validation 5-gate checklist, lifecycle state diagram, retro cadence summary).

**T12 — Context auto-inject:**
- `scripts/inject_context.py` (full implementation, ~340 lines). POST `<HINDSIGHT_URL>/recall` with `{bank_id, query, top_k}`; normalises entries/results envelopes; auto-resolves `project` + `bank_id` from consumer `AGENTS.md` frontmatter; sanitises output through `secrets_scan.sanitise` before write; writes `<consumer>/.claude/injected-context.md` with per-entry markdown blocks + metadata; `DEGRADED_CONTEXT` banner path on URL errors / timeouts / credentials missing; break-glass honoured with audit-logged override.
- `tests/test_inject_context.py` (21 tests — all pass). Covers AGENTS.md introspection, HTTP normalisation (list + envelope shapes), degraded paths (HTTPError / URLError / malformed JSON), rendering (empty / populated / degraded / error banners), sanitiser integration, CLI paths (missing creds, force-with-reason, dry-run, happy path, bank-id override).
- `docs/concepts/session-start-hook.md` — how to wire it into Claude Code `SessionStart`, Gemini CLI, Cursor, plus dry-run + break-glass docs.

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
- `scripts/_break_glass.py` (NEW) — shared helper per `docs/rules/break-glass.rule.md`. `add_break_glass_flag`, `apply_break_glass`, min reason length 10, logs to `.ai-playbook/overrides.log`.
- `scripts/schema_validate.py` — full AGENTS.md frontmatter validator + `--autofix` (inject defaults, normalise `updated`, slugify `project`, pin `inherits_from`). Honours WILL/WON'T lists from migration-guide.md.
- `scripts/openspec_validate.py` — thin wrapper around `npx @fission-ai/openspec@latest validate`. Cross-platform npx lookup.
- `scripts/verdict_lint.py` — enforces verdict literals + S1-S4 severities on artefacts; `--shape artifact|error|script-cli`; S0 audit-only; never overridable (exit 3 on `--force-with-reason`).
- `scripts/block_manual_spec_edit.py` — pre-commit hook blocking hand-edits to `openspec/specs/*.md` unless commit message carries `openspec-archive:` marker.
- `.pre-commit-config.yaml` — full hook chain (trailing-whitespace, eof-fixer, check-yaml/json, large-files 500KB, gitleaks, schema-validate, mcp-validate, block-manual-spec-edit, verdict-lint).
- `docs/concepts/env-vars.md` — fully enumerated. Resolved the `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` alias TODO (canonical wins; bare alias accepted with doctor.py warning; removal in v2.0.0).
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
- Stable finding_id for max-2-rework — deferred: `verdict_lint.py` currently uses `title` substring matching; formal `finding_id` remains future work (tracked by the heuristic note in `docs/rules/verdict-contract.rule.md` §3).

## [Unreleased] — T02 + Batch 2

### Added (Batch 2 — universal norm specs populated from stubs)
- **`specs/agents-md-v1.schema.json`** (T03a): tightened patterns (`version` semver, `inherits_from` github pins, `project` slug, `owner` email), added `$comment` rationale, `examples[]` with 2 cases.
- **`docs/concepts/migration-guide.md`** (T03b): v0→v1 procedure, warn-only stance at v0.1.x, hard-fail at v2.0, autofix contract, acme-shop worked example (before/after diff), 5 common pitfalls.
- **`docs/concepts/taxonomy.md`** (T03c): 25 entries across runtime/config/process groupings + 5 "hammered distinctions" (tool-vs-skill, hook-vs-script, subagent-vs-agent, personal-add-on-vs-project-dispatcher, dispatcher-vs-router).
- **`docs/concepts/model-routing.md`** (T04a): 9-class task taxonomy, fallback semantics (1-step silent, ≥2-step visible), provider quirks (Anthropic/Gemini/OpenRouter/Ollama), OTel attribute table.
- **`docs/concepts/degradation-modes.md`** (T04b): 5-state enum (HEALTHY/DEGRADED_CAPACITY/_QUALITY/_CONTEXT/OFFLINE), rolling-window triggers, circuit breaker (30s floor, 5min cap), composition rules, T19 dashboard contract.
- **`docs/concepts/prompt-caching.md`** (T04c): 9-tier stable→volatile rule, provider-specific mechanics (`cache_control`+5min TTL, Context Caching API+32k min, OpenAI-compat implicit, Ollama KV warmth), 6 anti-patterns, worked 3-turn example, `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` knob.
- **`docs/concepts/parallel-review.md`** (T05a): 3-layer pattern, 3 canonical prompts (Blind Hunter + Edge Case + Acceptance ≥30 lines each), triage, cost budgets (Sonnet×3 default), discipline rules.
- **`docs/concepts/agentic-failures.md`** (T05b): 12-entry catalog (hallucination, infinite_loop, prompt_injection, goal_drift, over_confidence, context_collapse, tool_selection_error, premature_completion, untracked_state_mutation, plan_mode_escape, credential_exposure, cascade_failure) with signal + detector + OTel attr + example each.
- **`docs/rules/verdict-contract.rule.md`** (T05c): `✅/⚠️/❓` canonical strings, S0-S4 rubric, max-2-rework SYSTEMIC escalation, `blocked-by-spec` lifecycle, 3 worked examples, interaction with break-glass.
- **`docs/concepts/memory-hierarchy.md`** (T06a): 4-tier table (session/project/durable-personal/durable-universal), `bank_id` conventions (including `*-personal` suffix), retrieval thresholds, decay policy, handoff to agent-contract.
- **`docs/concepts/agent-contract.md`** (T06b): formal input/return envelopes, field reference tables, `budget_exhausted` synthesized return, JSON Schema (draft 2020-12) inline, RBAC linkage (deferred to T18).
- **`docs/rules/error-message-standard.rule.md`** (T07a): canonical WHY/WHERE/FIX/OVERRIDE, field contracts, 4 worked examples, exit code table, OTel mapping, linter contract, anti-patterns.
- **`docs/rules/break-glass.rule.md`** (T07b): `--force-with-reason` contract, min reason length (10), OTel attrs, audit trail (local + durable + retro), shared Python helper interface, override-vs-verdict boundary (never waives S1).

### Open TODOs surfaced by subagents
- `--autofix` flag behaviour in migration-guide.md (lands with T09 scripts).
- `AIPLAYBOOK_ANTHROPIC_CACHE_TOKENS_MIN` alias vs bare `ANTHROPIC_CACHE_TOKENS_MIN` (reconcile in env-vars.md during T09).
- Stable `finding_id` for same-finding detection in max-2-rework (heuristic currently; tighten when `verdict_lint.py` lands in T09).

### Added (T02-pre, pre-Batch-2)
- **Projects registry** (`docs/concepts/projects-registry.md`) — per-dev `~/.ai-playbook/projects.yaml` mapping project name → absolute path. Eliminates hardcoded paths from dispatchers.
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
