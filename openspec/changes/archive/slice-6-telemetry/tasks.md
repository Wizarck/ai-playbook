# Tasks — slice-6-telemetry

## 1. Event schema + package skeleton

- [x] 1.1 Create `schemas/schema-rule-event-v1.json` with required + optional fields.
- [x] 1.2 Create `scripts/telemetry/__init__.py` (package marker + re-exports).
- [x] 1.3 Create `scripts/telemetry/anonymize.py` (hash_session_id + scrub_event).

## 2. Rule-event logger

- [x] 2.1 Create `scripts/telemetry/rule_event_logger.py` with `log_event(...)` + path resolution via `AI_PLAYBOOK_STATE_DIR`.
- [x] 2.2 Wire `scripts/hook_dispatcher.py` `dispatch()` to invoke `log_event` per matched rule.
- [x] 2.3 Update `tests/test_hook_latency.py` with `<5ms` event-emission overhead assertion.

## 3. Telemetry report (absorbs 5 CLIs)

- [x] 3.1 Create `scripts/telemetry/report.py` skeleton with CLI (`weekly` / `monthly` / `custom`).
- [x] 3.2 Implement `_compute_obey_rate()` per rule × LLM × window.
- [x] 3.3 Implement `_compute_cost_per_rule()` using `configs/pricing.yaml` (absorb `cost_report.py`).
- [x] 3.4 Implement `_compute_cost_per_session()` aggregated by `session_id_hash`.
- [x] 3.5 Implement `_compute_spend_over_time()` per-day bucket.
- [x] 3.6 Implement `_check_retirement_window()` (absorb `lifecycle_check.py` model-retirement code).
- [x] 3.7 Implement `_check_budget_breach()` (absorb `budget_disable_check.py`).
- [x] 3.8 Implement `_check_openspec_staleness()` (absorb `deprecation_watcher.py` stale logic + `lifecycle_check.py` openspec walker).
- [x] 3.9 Implement `_check_break_glass_usage()` (count escape-hatch events).
- [x] 3.10 Implement `_simulate_model_migration()` (absorb `simulate_model_migration.py`).
- [x] 3.11 Stub `_check_memory_decay()` (full implementation deferred to Slice 7).
- [x] 3.12 Render markdown + JSON outputs.
- [x] 3.13 Graceful zero-data handling (empty log returns valid empty report, exit 0).

## 4. Delete the 5 standalone CLIs

- [x] 4.1 `git rm scripts/cost_report.py tests/test_cost_report.py`.
- [x] 4.2 `git rm scripts/lifecycle_check.py tests/test_lifecycle_check.py`.
- [x] 4.3 `git rm scripts/budget_disable_check.py`.
- [x] 4.4 `git rm scripts/deprecation_watcher.py tests/test_deprecation_watcher.py`.
- [x] 4.5 `git rm scripts/simulate_model_migration.py`.
- [x] 4.6 Sweep `docs/`, `openspec/`, `runbooks/`, `templates/` for references to the deleted CLIs; replace with `python -m scripts.telemetry.report`.

## 5. Tests

- [x] 5.1 `tests/test_telemetry.py` — ≥15 cases (pricing, cost compute, anonymize, end-to-end report).
- [x] 5.2 `tests/test_telemetry_privacy.py` — ≥5 cases enforcing no PII leakage.
- [x] 5.3 One `tests/test_<slug>_rule.py` per implemented hardrule — ≥5 cases each.

## 6. Documentation

- [x] 6.1 Author `docs/concepts/telemetry-design.md` (canonical concept format).
- [x] 6.2 Author `docs/runbooks/run-telemetry-report.md` (canonical runbook format).
- [x] 6.3 Update `docs/concepts/INDEX.md` + `docs/runbooks/INDEX.md`.

## 7. Implement 14 deferred hardrules

- [x] 7.1 `scripts/rules/verdict-contract.rule.py` (always-loaded).
- [x] 7.2 `scripts/rules/output-completeness.rule.py` (always-loaded).
- [x] 7.3 `scripts/rules/verification-before-completion.rule.py` (always-loaded).
- [x] 7.4 `scripts/rules/error-message-standard.rule.py` (always-loaded).
- [x] 7.5 `scripts/rules/apply-skill-enforcement.rule.py` (always-loaded).
- [x] 7.6 `scripts/rules/bootstrap-directive.rule.py` (always-loaded).
- [x] 7.7 `scripts/rules/ai-reviewer-signoff.rule.py` (workflow).
- [x] 7.8 `scripts/rules/auto-merge-discipline.rule.py` (workflow).
- [x] 7.9 `scripts/rules/auto-pr-stream-closure.rule.py` (workflow).
- [x] 7.10 `scripts/rules/delegated-shipping-prompt.rule.py` (workflow).
- [x] 7.11 `scripts/rules/doc-drift-enforcement.rule.py` (workflow).
- [x] 7.12 `scripts/rules/github-project-board-schema.rule.py` (workflow).
- [x] 7.13 `scripts/rules/pr-tracker-reference.rule.py` (workflow).
- [x] 7.14 `scripts/rules/subagent-envelope-schema.rule.py` (workflow).
- [x] 7.15 Remove the 14 slugs from `scripts/rules/deferred-hardrules.txt`.

## 8. Mkdocs Telemetry page

- [x] 8.1 Create `docs/telemetry.md` (initial placeholder rendering).
- [x] 8.2 Wire `mkdocs.yml` nav entry.

## 9. Release prep

- [x] 9.1 Bump `VERSION` 0.18.1 → 0.18.2.
- [x] 9.2 Append `CHANGELOG.md` v0.18.2 entry.

## 10. Validate

- [x] 10.1 `pytest tests/` — green.
- [x] 10.2 `python -m scripts.telemetry.report monthly` — exit 0 on empty log.
- [x] 10.3 `python -m scripts.telemetry.report weekly --json` — valid JSON.
- [x] 10.4 `python scripts/validate_pairing.py` — exit 0 (strict).
- [x] 10.5 `python scripts/cleanup_zombies.py validate` — exit 0.
- [x] 10.6 `python scripts/check_link_integrity.py docs/` — exit 0.
- [x] 10.7 `python scripts/check_doc_language.py docs/` — exit 0.
- [x] 10.8 `python scripts/check_agents_md_size.py` — exit 0.
