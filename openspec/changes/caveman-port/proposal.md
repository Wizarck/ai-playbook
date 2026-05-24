# caveman-port

> **Status**: SCRATCH (gitignored — `openspec/` dropped from playbook in PR #79).
> Canonical contract lives in the PR description (#88). This file is iteration scratch and exists to satisfy the `branch-name-validator` workflow.

## Why

Output tokens cost real money on every model response; input tokens cost real money on every session start (memory files re-read each time). Two upstream measurements set the bar:

- JuliusBrussee/caveman (MIT): rewriting agent output in compressed "caveman style" delivers ~65–75% output-token reduction with full technical accuracy preserved.
- Same project's `caveman-compress`: rewriting memory files (CLAUDE.md, AGENTS.md, project notes) in the same style delivers ~46% input-token reduction per session, every session, forever.

Net effect: a meaningful per-session cost cut, with no model-quality regression and (per a March 2026 paper on brevity constraints) sometimes a measurable accuracy *improvement* on certain benchmarks. The ai-playbook is the right home because: (a) it already centralises skills, hooks, materialise, MCP render — all the substrates the feature needs; (b) the playbook itself benefits as the first dogfood subject (every project that submodules it ships with the option to compress).

## What

A self-contained `scripts/caveman/` Python package + a tree of `skills/caveman*/` LLM-facing skills + one paired `docs/rules/caveman-reinforce.rule.md` hardrule. The **single source of truth** for state is `<project>/.ai-playbook/caveman.json`, validated by a new `schemas/schema-caveman-toggle-v1.json`. Every other side-effect (AGENTS.md ruleset block, per-turn reinforcement hook, MCP server wrapping, statusline suffix, stats) is **derived** from that single file by `scripts/caveman/cli.py`. A future UI is a thin subprocess wrapper around the same CLI.

Per-project state by design — a developer can have caveman ON for one project (e.g. long-form architecture work) and OFF for another (e.g. customer-facing API surface where verbose is safer). No global default.

## Scope (this PR, one stacked-PR bundle)

### Phase A — Skills + cavecrew subagents
- `skills/caveman/SKILL.md`, `skills/caveman-{compress,commit,review,help}/SKILL.md` (5 skills).
- `skills/caveman/agents/cavecrew-{investigator,builder,reviewer}.md` (3 subagents).

### Phase B — Toggle engine
- `schemas/schema-caveman-toggle-v1.json` — state contract.
- `scripts/caveman/{__init__,__main__,toggle,backup,cli}.py` — read/write + CLI skeleton.
- 47 tests.

### Phase C — Materialise (AGENTS.md inject/strip)
- `scripts/caveman/materialise.py` — uses existing `scripts/auto_managed.py` marker convention.
- CLI wires materialise into `on`/`off`. 20 tests.

### Phase D — Reinforce hook (UserPromptSubmit)
- `docs/rules/caveman-reinforce.rule.md` — advisory rule, `triggers: [UserPromptSubmit]`.
- `scripts/rules/caveman-reinforce.rule.py` — stdlib-only, silent-fail.
- Template wiring in `templates/new-project/.claude/settings.json.tmpl`.
- 10 tests.

### Phase E — Compress with byte-preservation contract
- `scripts/caveman/compress.py` — extracts contract, calls LLM, validates, retries.
- CLI subcommand `compress`. 19 tests.

### Phase F — MCP shrink
- `scripts/caveman/mcp_shrink.py` — wraps stdio entries in `.mcp.json` and `.gemini/settings.json`.
- Post-render hook in `scripts/mcp/render.py`. 19 tests.

### Phase G — 3-arm eval harness scaffold
- `tests/evals/caveman/` — baseline / terse / caveman. Snapshots run in prod.
- 7 tests.

### Phase H — Docs
- `docs/operations/caveman-architecture.md` — UI integration contract (primary deliverable).
- `specs/caveman-toggle.md`, `docs/runbooks/caveman-toggle.md`, `docs/concepts/caveman-mode.md`.
- AGENTS.md §2 dispatcher pointers.

### Phase I — Follow-up
- stats + rollback CLI subcommands (no longer stubs).
- `--project` arg-position bug fix.
- claude-settings interop pinning tests.

## Why not split

Per the upstream caveman project's atomic shape: skills + hooks + materialise + MCP shrink are designed to compose. Splitting would mean intermediate states where, e.g., the materialise step exists without the hook reinforcement, or the toggle file exists without the side-effect orchestration. Each commit (A→I) is atomic and gated on its own tests, but the bundle is reviewed as one feature.

## Decisions (locked at planning, see `~/.claude/plans/snappy-orbiting-peach.md`)

| ID | Decision |
|---|---|
| D1 | Toggle state per-project only at `<project>/.ai-playbook/caveman.json`; no global default. |
| D2 | Activation = both layers — marker-fenced AGENTS.md block + per-turn UserPromptSubmit hook. |
| D3 | MCP shrink wraps ALL stdio servers with `caveman-shrink` (`npx`), backed up first. |
| D4 | Every reversible mutation gets a backup at `.ai-playbook/backups/<area>/<file>.<ts>.bak`. |
| D5 | Honest-eval discipline: snapshot delta = `caveman vs terse`, NOT `caveman vs baseline`. |
| D6 | Voice convention: caveman speak in LLM-facing SKILL.md only; all human-facing docs stay normal. |
| D7 | NOT ported: wenyan modes, stdout-injection trick, multi-agent installer (Cursor/Windsurf/etc). |
| D8 | UI is a thin subprocess wrapper around the same CLI — no separate API surface. |

## Out of scope (explicit non-goals)

- Wenyan (classical Chinese) modes — upstream gimmick.
- The original SessionStart stdout-injection trick — opaque, replaced with auditable AGENTS.md materialise.
- Multi-agent installer fan-out (Cursor, Windsurf, Cline, Copilot, 30+ others) — playbook-scoped first.
- Eval snapshots run in CI — runs in prod where LiteLLM proxy lives; harness ready for it.
- Compress dogfood on every memory file — done one-off on AGENTS.md (this PR), CLAUDE.md / BRAIN.md / ELIGIA.md (outside this repo).

## Verification footprint

- 160 caveman + claude-settings tests pass locally + in CI.
- `check_skill_descriptions.py`: clean on all 5 new skills (CSO discipline).
- `check_link_integrity.py`: OK (138 files scanned).
- `ai_playbook_check.py --check`: 31 rules ok (including new `caveman-reinforce`); 6 drifts ALL PRE-EXISTING (verified against `origin/main`); 0 errors.
- UI subprocess smoke from outside the playbook: returns 0, JSON parses, shape matches the documented contract.

## Risks

| Risk | Mitigation |
|---|---|
| `caveman-shrink` npm package not installed → wrapped MCP commands fail | `is_shrink_available()` probe + CLI warning. `mcp-restore` reverses cleanly. |
| Compress LLM call drops a code block / heading / URL | Byte-preservation contract + up-to-2 retries with targeted patch + restore-from-backup on final failure. |
| AGENTS.md gets two caveman blocks via concurrent edits | `materialise.py` refuses with `ValueError: N caveman blocks; expected 1`. |
| Per-project state pollution from test runs | Bug found in Phase I (`--project` arg-pos); fixed + pinning tests added. Playbook state cleaned. |
| Future schema bump (v1 → v2) | Migration path documented in `specs/caveman-toggle.md`; `scripts/caveman/migrations/` reserved. |

## Test plan

1. Each new Python module ships ≥3 unit tests covering happy path, schema/contract violations, idempotency.
2. CLI integration tests cover every subcommand × `--json` shape × project arg position.
3. End-to-end smoke: `caveman on --components response_style,mcp_shrink` → confirm AGENTS.md block present + `.mcp.json` wrapped + backups exist; `caveman off` → confirm AGENTS.md block stripped + `.mcp.json` restored.
4. CI gates: `ruff`, `pytest 3.11`, `pytest 3.12`, `check-rule-schemas`, `validate-pairing`, `check-link-integrity`, `check-doc-language`, `branch-name-validator`.
