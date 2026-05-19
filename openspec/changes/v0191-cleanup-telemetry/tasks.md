# v0191-cleanup-telemetry — Tasks

## Group 1 — Retroactive tag

- [x] 1.1 Identify the SHA where VERSION first read 0.18.0 (`d612350`)
- [x] 1.2 `git tag -a v0.18.0 d612350 -m "..."` + push

## Group 2 — Telemetry wiring

- [x] 2.1 Create `scripts/rules/_telemetry.py` with `cli_emit(slug, main_fn, argv=None)` + `verdict_from_rc(rc)` helpers
- [x] 2.2 Wire all 29 `scripts/rules/<slug>.rule.py` `__main__` blocks to call `cli_emit`
- [x] 2.3 Add `tests/test_rules_telemetry.py` (9 tests)
- [x] 2.4 `python -m pytest tests/test_rules_telemetry.py -q` -> 9 passed

## Group 3 — OpenSpec archive

- [x] 3.1 `mkdir openspec/changes/archive`
- [x] 3.2 `git mv` each of the 20 shipped slice directories into archive/
- [x] 3.3 Confirm `openspec list` no longer surfaces the archived entries

## Group 4 — Mkdocs nav

- [ ] 4.1 Generate the complete list of docs under each of `docs/{rules,concepts,runbooks,tutorials}/`
- [ ] 4.2 Compare to current `mkdocs.yml` nav; identify gaps
- [ ] 4.3 Add entries for each gap under the matching nav section
- [ ] 4.4 `python -m mkdocs build --strict` -> success

## Group 5 — Meta + release

- [ ] 5.1 `VERSION`: 0.19.0 -> 0.19.1
- [ ] 5.2 `CHANGELOG.md`: prepend v0.19.1 entry
- [ ] 5.3 Run full local CI
- [ ] 5.4 Open PR; merge after CI green
- [ ] 5.5 Tag v0.19.1
