# Tasks — root-folder-audit (v0.17.1)

## 1. Audit ledger

- [x] 1.1 Enumerate every visible file at repo root (`ls c:/Projects/ai-playbook/`).
- [x] 1.2 Enumerate every `.github/workflows/*.yml`.
- [x] 1.3 Write `docs/concepts/root-folder-audit.md` with the per-file decision table.

## 2. DELETE decisions

- [x] 2.1 `git rm FEEDBACK.md`.
- [x] 2.2 Remove physical `ai_playbook.egg-info/` directory (untracked; `.gitignore` glob `*.egg-info/` already covers it — confirm).
- [x] 2.3 `git rm .github/workflows/issue-sync.yml`.

## 3. MOVE decisions

- [x] 3.1 `git mv mcp-servers-base.yaml templates/rendered/mcp-servers-base.yaml.tmpl`.
- [x] 3.2 Update path constants in `scripts/mcp/validate.py` (root-detection sentinel + `load_layers`) and `scripts/init_org.py` (bootstrap walker sentinel).
- [x] 3.3 Update test fixtures in `tests/test_mcp_validate.py`, `tests/test_mcp_render.py`, `tests/test_init_org.py`.
- [x] 3.4 Update error-message strings in `scripts/mcp/render.py` + `scripts/mcp/validate.py`.
- [x] 3.5 `git mv pricing.yaml configs/pricing.yaml`.
- [x] 3.6 Update `_DEFAULT_PRICING_PATH` in `scripts/cost_report.py`.
- [x] 3.7 Update error-message string in `scripts/cost_report.py` (`Populate <playbook>/pricing.yaml` → `configs/pricing.yaml`).

## 4. README + AGENTS housekeeping

- [x] 4.1 Update README.md directory map (drop `FEEDBACK.md` row, update `mcp-servers-base.yaml` row, add `pricing.yaml` row under `configs/`).
- [x] 4.2 Replace `FEEDBACK.md` references in `scripts/mcp/render.py` + `scripts/mcp/validate.py` error-message `fix:` strings (replacement: open a GH issue).
- [x] 4.3 Leave docs/specs prose references to FEEDBACK.md for slice 5 to rewrite (out of scope here).

## 5. Zombies-manifest v3

- [x] 5.1 Bump `manifest_version` from `2026-05-19.2` → `2026-05-19.3`.
- [x] 5.2 Add entry `feedback-md-removed` (Tier 1).
- [x] 5.3 Add entry `mcp-servers-base-relocated` (Tier 3 advisory — path move).
- [x] 5.4 Add entry `pricing-yaml-relocated` (Tier 3 advisory — path move).
- [x] 5.5 Add entry `ai-playbook-egg-info-orphan` (Tier 1 safe-delete).
- [x] 5.6 Add entry `issue-sync-workflow-removed` (Tier 1 safe-delete in any consumer that copied it).

## 6. Release

- [x] 6.1 `VERSION` → `0.17.1`.
- [x] 6.2 CHANGELOG entry under `## [0.17.1]` summarising KEEP/DELETE/MOVE; cite `docs/concepts/root-folder-audit.md`.

## 7. Validation

- [x] 7.1 `pytest tests/` — green (baseline 3 skipped).
- [x] 7.2 `python scripts/rules/cleanup-zombies.rule.py validate` — exit 0.
- [x] 7.3 `python scripts/cost_report.py --help` — no error.
- [x] 7.4 `python -m scripts.mcp.render --help` — no error.
- [x] 7.5 `pip install -e .` — succeeds.
- [x] 7.6 `pre-commit run --all-files` — green (or document pre-existing skips).
- [x] 7.7 `ls c:/Projects/ai-playbook/` — root file count ≤12.

## 8. PR

- [x] 8.1 Commit in 3-5 conventional chunks.
- [x] 8.2 Push `feat/root-folder-audit` to origin.
- [x] 8.3 Open PR via `gh pr create` with Summary, Audit ledger link, Decisions applied, Test plan, File-ownership note.
