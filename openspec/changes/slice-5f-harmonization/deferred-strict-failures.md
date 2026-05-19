# Deferred strict-mode failures — slice-5f-harmonization

When sub-slice 5.F flipped `scripts/validate_pairing.py` and `scripts/check_link_integrity.py` to strict-by-default, 59 hardrule-not-found drift errors surfaced. Of those, 24 unique rule slugs declare a `paired_hardrule:` that names a `scripts/rules/<slug>.rule.py` file not yet on disk. The implementations ship in a later slice (Slice 6 telemetry or Slice 7 polish) — they are deliberately deferred, not forgotten.

The deferral surface is the file `scripts/rules/deferred-hardrules.txt`: one slug per line, `#` comments allowed. The strict validator downgrades the "not found" check to a no-op for listed slugs. This register documents WHY each is deferred and which slice expects to land the hardrule.

Removing a slug from the txt file is the merge gate: once the hardrule script exists, the slug disappears from the allowlist and the validator switches from "deferred" to "validated".

## Always-loaded rules — Slice 6 candidate

The six D16 invariants name a paired hardrule for symmetry with the 4-signal contract (D3), but the rubrics are LLM-judgement-shaped (verdict literal emit, completeness, verification, error shape, skill enforcement, bootstrap order). A Python hardrule for these is more telemetry-friendly than determinism-friendly: log-the-fire is the value, not block-on-violation. Authored in Slice 6 alongside `scripts/telemetry/rule_event_logger.py`.

| Slug | Target slice | Rationale |
|---|---|---|
| `verdict-contract` | 6 | Verdict literal grep; PostToolUse on `Edit`/`Write` checking for emitted `✅`/`❌`/`❓` shape. |
| `output-completeness` | 6 | Detects truncation patterns in tool-output writes (`...` mid-sentence, "tbd", "stub"). |
| `verification-before-completion` | 6 | Pairs with verdict-contract — fires when `✅ APPROVED` lands without a verification token in the same turn. |
| `error-message-standard` | 6 | Regex check on canonical block message shape (WHY/WHERE/FIX/OVERRIDE quadrant). |
| `apply-skill-enforcement` | 6 | Detects edits to `openspec/changes/<slice>/tasks.md` without an active apply-skill session marker. |
| `bootstrap-directive` | 6 | Detects session start without AGENTS.md read; pairs with `gemini-session-start` for Gemini-specific shape. |

## Workflow / contract rules — Slice 6 candidate

These bind PR-time invariants (PR body schema, ticket references, AI-reviewer signoff). L1 hardrules are deterministic regex / json-schema checks against PR-time payloads emitted by the harness.

| Slug | Target slice | Rationale |
|---|---|---|
| `ai-reviewer-signoff` | 6 | Grep `## 4.5 AI-reviewer signoff` markers in PR body. |
| `auto-merge-discipline` | 6 | PostToolUse on `gh pr merge --auto` — refuses if §4.5 block absent. |
| `auto-pr-stream-closure` | 6 | Filter on `gh pr list` results matching the propagate-bump branch pattern. |
| `delegated-shipping-prompt` | 6 | JSON-schema validate on subagent spawn envelopes. |
| `doc-drift-enforcement` | 6 | Already wired via the dedicated `.github/workflows/doc-drift-enforcement.rule.yml`; the L1 hardrule mirrors the workflow logic for local pre-commit fire. |
| `github-project-board-schema` | 6 | Validate Status field enumeration via `gh project field-list`. |
| `pr-tracker-reference` | 6 | Regex `(Closes #\d+|[A-Z]+-\d+)` in PR title or body. |
| `subagent-envelope-schema` | 6 | JSON-schema validate on Task-tool spawn payloads. |

## Migrations / data-shape rules — Slice 7 candidate

These guard repo-side artefacts (Alembic filenames, migration slot reservations, failure-catalog rows). Hardrule = grep on `alembic/versions/`, `docs/openspec-slice.md`, `docs/concepts/agentic-failures.md`.

| Slug | Target slice | Rationale |
|---|---|---|
| `alembic-migration-naming` | 7 | Pre-commit check on `alembic/versions/*.py` filenames matching the `<NNNN>_<topic>` form. |
| `cross-slice-additive-extension` | 7 | Detects additive-extension violations (slot reuse) by parsing the openspec-slice ledger. |
| `migration-slot-reservation` | 7 | Pairs with `cross-slice-additive-extension` — confirms slot claim before the migration filename lands. |
| `agentic-failure-catalog-schema` | 7 | Validates `docs/concepts/agentic-failures.md` table rows against the schema in `schemas/`. |

## Notification rules — Slice 7 candidate

The notification trio (level, secrets, channel adapter) sits over `scripts/notifications/`. Hardrules are import-shape checks on adapters + payload-shape validators.

| Slug | Target slice | Rationale |
|---|---|---|
| `notification-channel-adapter` | 7 | Import-shape: every `scripts/notifications/<name>.py` must export `send(payload)` + `name = "<name>"`. |
| `notification-level-declared` | 7 | Required field check on every `notify.py` call site. |
| `notification-no-secrets` | 7 | Runs `secrets_scan.py` against the rendered notification payload before transport. |

## Apply / break-glass rules — Slice 7 candidate

Apply-phase contracts + the global break-glass audit trail. L1 hardrules ride existing scaffolding (`scripts/openspec_apply_*.py`).

| Slug | Target slice | Rationale |
|---|---|---|
| `apply-fix-contract` | 7 | Detects "fix" commits during apply phase that exit the slice scope. |
| `break-glass` | 7 | Validates `AIPLAYBOOK_*_SKIP=1` env-var presence + `.ai-playbook-state/break-glass-audit.jsonl` append on every bypass. |
| `hitl-approval-pattern` | 7 | PR-body grep for the HITL approval marker on gates that require human-in-the-loop. |

## Net counts

- Total `docs/rules/*.rule.md` files: 38
- Enforced (paired hardrule on disk): 10 (the 9 Slice 5.E + 1 Slice 1)
- Advisory (`paired_hardrule: null`): 5 (4 from Slice 5.A + 1 from Slice 5.E)
- Deferred (named hardrule, not on disk): 24

Closing the deferred set is the implementation goal of Slices 6 + 7. The plan's v0.20.0 target depends on the deferred count reaching 0; the strict-mode validator is the merge gate for that count.

## How to retire a deferral

1. Author `scripts/rules/<slug>.rule.py` per the standard scaffold (validate + apply + CLI).
2. Author `tests/test_<slug>.py` (≥3 cases).
3. Add the hardrule slug to `.github/workflows/check-rule-schemas.rule.yml` paired set (or wire its own workflow if it warrants a dedicated job).
4. Remove the slug from `scripts/rules/deferred-hardrules.txt`.
5. Run `python -m scripts.validate_pairing` — exit 0.
6. Move the slug from "Hardrule deferred" to "Enforced" in `AGENTS.md` §9.
