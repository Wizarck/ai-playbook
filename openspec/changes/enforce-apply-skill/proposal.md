# proposal — `enforce-apply-skill`

> **Status**: draft (slice/`enforce-apply-skill`).
> **Wave**: ai-playbook v0.14.0 candidate (additive MINOR).
> **Authored**: 2026-05-15.

## Problem

The OpenSpec workflow exposes a native apply skill (`openspec-apply-change`) that:
- Reads the change folder's artefacts (proposal/design/specs/tasks),
- Walks `tasks.md` in TDD order,
- Enforces `output-completeness.md` (no skeletons) and `verification-before-completion.md` (verdict only with verification output).

But **nothing stops an agent from bypassing the skill** and performing the implementation directly via `Edit`/`Write` on the slice's `write_paths`. Concrete instances observed in `Geeplo`'s Revalid v1.0 epic execution (PRs #1-#4, 2026-05-14): four slices implemented with manual edits, no skill invocation. Symptoms:

- TDD ordering not respected (tests appended at end vs. red-first).
- Self-validation gates (§3.4 of [runbook-bmad-openspec.md](../../../specs/runbook-bmad-openspec.md)) skipped silently.
- Citation-drift preflight (§4b of the skill, v0.11.0) bypassed → stale identifier references slipped into iter-1 commits.
- No audit signal that "the apply phase was actually orchestrated by the skill" — retros cannot distinguish skill-orchestrated work from manual work.

Per [enforcement-status.md](../../../specs/enforcement-status.md), [runbook-bmad-openspec.md](../../../specs/runbook-bmad-openspec.md) is 🟡 partial: `openspec` CLI wired, verdict linter wired, but the apply-phase orchestration gate is on convention only.

## Proposed change

Three-layer enforcement (L1 doc + L2 skill marker + L3 blocking hook), shipped together as a single MINOR.

| Layer | Surface | Mechanism |
|---|---|---|
| **L1 — doc rule** | [`specs/runbook-bmad-openspec.md`](../../../specs/runbook-bmad-openspec.md) §3.1 (new §3.1.1 subsection) | Explicit: "Apply phase MUST be initiated through `openspec-apply-change` skill. Manual `Edit`/`Write` against any path under a change's declared `write_paths` during apply phase is `goal_drift` per [`agentic-failures.md`](../../../specs/agentic-failures.md) §2.X." Adds a row to [`specs/agentic-failures.md`](../../../specs/agentic-failures.md). |
| **L2 — skill marker** | `skills/openspec-apply-change/SKILL.md` (new step 0) + new helper [`scripts/openspec_apply_marker.py`](../../../scripts/openspec_apply_marker.py) | Skill step 0: invoke `python scripts/openspec_apply_marker.py start --change-id <id> --session-id <claude_session_id>`. Marker is `openspec/changes/<id>/.apply_log.jsonl` (JSONL append-only; committed; one record per apply session start/stop). |
| **L3 — blocking hook** | `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` + `templates/new-project/.claude/settings.json.tmpl` (registers hook) | PreToolUse hook on `Edit`/`Write`. Parses the tool's `file_path` arg; if path matches a `write_paths` entry of any change in `applied`/`applying` lifecycle state AND the matching `.apply_log.jsonl` has no `started` record for current session → exit non-zero with the canonical break-glass message (per [`error-message-standard.md`](../../../specs/error-message-standard.md)). |

### Spec deliverables

- **New spec**: [`specs/apply-skill-enforcement.md`](../../../specs/apply-skill-enforcement.md) — defines marker format (JSONL schema), hook contract (which paths are gated, which are not), break-glass clause (per [`break-glass.md`](../../../specs/break-glass.md)), interaction with `verification-before-completion.md` (a verdict cannot be `✅ APPROVED` without a matching skill-marker record).
- **Updated spec**: [`specs/runbook-bmad-openspec.md`](../../../specs/runbook-bmad-openspec.md) §3.1.1 (new) — points at the new spec for the contract.
- **Updated spec**: [`specs/agentic-failures.md`](../../../specs/agentic-failures.md) — new row in §2 taxonomy: `2.X apply_phase_bypass`.
- **Updated spec**: [`specs/enforcement-status.md`](../../../specs/enforcement-status.md) — new row for `apply-skill-enforcement.md` at status ✅ wired (or 🟡 partial if hook lands template-only without a real consumer adopting on day 1).

### Code deliverables

| Path | Action | Description |
|---|---|---|
| `scripts/openspec_apply_marker.py` | NEW | Helper: `start`/`stop`/`is_active`/`session_started` subcommands. JSONL append. Path resolution honours `openspec.root` config; falls back to `./openspec`. Idempotent on duplicate `start` calls within same session_id. |
| `tests/test_openspec_apply_marker.py` | NEW | 6+ tests: happy start/stop, idempotent start, malformed JSONL recovery, multi-session interleave, missing change folder error shape. |
| `skills/openspec-apply-change/SKILL.md` | EDIT | Insert new step 0 ("Write apply-session start marker") before existing step 1 ("Select the change"). Update version frontmatter `1.0` → `1.1`. |
| `templates/new-project/.claude/hooks/openspec-apply-enforce.py.tmpl` | NEW | Per-project hook copy. Reads `$CLAUDE_PROJECT_DIR/openspec/changes/*/`. Tasks.md write_paths extraction is line-based (`* `backend/path/to/file.py``). Bash-of-Python via `python3` shebang; Windows-compatible via `py -3` fallback. |
| `templates/new-project/.claude/settings.json.tmpl` | EDIT | Add `hooks.PreToolUse[Edit\|Write]` entry pointing at the new hook script. |
| `scripts/render_hook_dispatcher.py` (or equivalent) | OPTIONAL | If the playbook already has a hook dispatcher, register through it. If not, this PR introduces direct settings.json registration only. |

### Versioning

- Bump `VERSION`: `0.13.3` → `0.14.0` (additive MINOR per [`rollout-strategy.md`](../../../specs/rollout-strategy.md): new opt-in hook template, new helper script, new spec; no consumer breaking changes).
- CHANGELOG entry under `[0.14.0]` section.

## Consumer adoption (downstream, in a follow-up)

After this slice merges and v0.14.0 is cut, each consumer (`geeplo`, `eligia-core`, `openTrattOS`, `palafito-b2b`) adopts in its own PR:
1. Bump `.ai-playbook` submodule.
2. Copy `.claude/hooks/openspec-apply-enforce.py` from template to project.
3. Update `.claude/settings.json` to register the hook.
4. Update `AGENTS.md` to point at the new spec.
5. If the project uses a custom schema (geeplo-team), declare `apply.handler: openspec-apply-change` in `openspec/schemas/<name>/schema.yaml`.

Out of scope here; tracked separately.

## Decisions

- **D1 Marker committed, not gitignored.** Reason: CI workflows (and humans on retros) need to read the marker to verify the apply phase was skill-orchestrated. Gitignored markers cannot serve audit. Trade-off: every apply session creates 1-2 lines of churn in the slice's git history — acceptable noise for the audit signal gained.
- **D2 Hook is a per-project template, not a global one in `~/.claude`.** Reason: hooks need to know the project's `openspec/` root and the slice's `write_paths` — only per-project context can resolve those. Global hook would have to walk every projects-registry entry on every Edit; quadratic in active projects.
- **D3 `write_paths` parsing is line-based, not AST.** Reason: `tasks.md` follows a documented convention (one path per bullet under the **Owns (write_paths)** heading). AST parsing of Markdown is overkill and the convention already enforces uniformity in existing slices.
- **D4 Break-glass clause: hook honours `AIPLAYBOOK_APPLY_ENFORCE_OVERRIDE=<reason>` env per [`break-glass.md`](../../../specs/break-glass.md).** Reason: legitimate manual edits exist (post-review fixes that touch the same files; emergency hotfix). Override creates an `override` JSONL record adjacent to the marker; counted in the monthly retro.
- **D5 Skill marker writes BEFORE first context-file read.** Reason: marker existence proves the skill orchestrated the session, even if implementation later aborts. Detected aborts (no `stop` record) surface in retros as `apply_phase_aborted`.
- **D6 Hook bypasses paths NOT under any active change's `write_paths`.** Reason: implementation often touches shared infra (test fixtures, _shared/models.py) that's append-only-with-marker per existing slice convention. The hook validates *only* the path is in a write_paths entry. Cross-cutting infra files have their own append-only enforcement (out of scope here).

## Validation

- L1: Adding the rule text to `runbook-bmad-openspec.md` + the new row to `enforcement-status.md` doesn't break `validate_specs.py` (which runs in CI).
- L2: Skill update keeps the existing 5 numbered steps; new step 0 is additive.
- L3: Hook template, when copied + adopted in a consumer, blocks a synthetic `Edit` on a write_paths file when no marker exists (manual test case in `tests/test_apply_enforce_hook_template.py`).

## Acceptance

- `pytest tests/test_openspec_apply_marker.py` passes (≥6 tests).
- `pytest tests/test_apply_enforce_hook_template.py` passes (template rendering + dry-run hook execution).
- Manual dogfooding: this very change's apply phase uses the skill, writes a marker to `openspec/changes/enforce-apply-skill/.apply_log.jsonl`, and the marker is committed in the apply commits.
- A synthetic consumer test (in `tests/integration/test_consumer_apply_enforce.py` or `runbooks/`-driven manual cases) confirms hook activation in a fresh `init` template.
- CHANGELOG entry under `[0.14.0]` covers L1+L2+L3 with file-level breakdown.

## Refs

- [runbook-bmad-openspec.md](../../../specs/runbook-bmad-openspec.md) §3.1 §3.4
- [agentic-failures.md](../../../specs/agentic-failures.md) (`goal_drift`, `over_confidence`)
- [verification-before-completion.md](../../../specs/verification-before-completion.md)
- [output-completeness.md](../../../specs/output-completeness.md)
- [verdict-contract.md](../../../specs/verdict-contract.md)
- [break-glass.md](../../../specs/break-glass.md)
- [error-message-standard.md](../../../specs/error-message-standard.md)
- [enforcement-status.md](../../../specs/enforcement-status.md)
- [rollout-strategy.md](../../../specs/rollout-strategy.md) (consumer propagation)
- Precedent: `verify_llm_routing.py` + pre-commit wiring (v0.13.0) — same shape, different surface
- Precedent: `verdict_lint.py` + `block_manual_spec_edit.py` — adjacent enforcement scripts
