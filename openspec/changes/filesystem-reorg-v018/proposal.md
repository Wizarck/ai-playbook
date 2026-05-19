## Why

The ai-playbook root mixes scripts, contracts, reference docs, runbooks, tutorials, and per-slice specs under generic folder names (`scripts/`, `specs/`, `docs/`, `runbooks/`) — words that downstream consumers (`geeplo`, `eligia-core`, `palafito-b2b`, ...) also use for their own per-project versions. The collision makes path origin unreadable at a glance and forces grep/IDE jumps to disambiguate.

Slice 3.5 (v0.17.1) already audited the root and committed the per-file ledger at `docs/concepts/root-folder-audit.md`. The remaining structural debt — rules vs concepts mixed inside `specs/`, tutorials mixed with concepts under `docs/`, `runbooks/` at root instead of under `docs/`, paired L1 hooks not visibly paired with their L2 docs — is the scope of this slice.

This slice is the **filesystem reorganisation**: a Diátaxis-inspired layout (`docs/{rules,concepts,runbooks,tutorials}`), a top-level `schemas/` (industry-standard placement: K8s, JSON Schema Store), and the paired-enforcement tooling (`validate_pairing.py`, `check_doc_language.py`, `check_link_integrity.py`, `check_agents_md_size.py`, `hook_dispatcher.py`, `materialise_cursor_rules.py`, `gen_indexes.py`, `check_deprecated_rules.py`, and the `validate_pairing_oracle.sh` parallel oracle).

**No content rewrite happens here.** Every move is via `git mv` so blame/log are preserved. Cross-references are updated by a one-shot script (`scripts/migrate_paths_v0.18.py`) which is then deleted in the same PR — the CHANGELOG entry IS the historical record. Content rewrites land in Slice 5 (v0.18.1+).

## What Changes

- **4.A — git mv only** (~135 files moved, history preserved):
  - `scripts/<paired>.py` → `scripts/rules/<slug>.rule.py` (paired L1 hooks)
  - `specs/<rule>.md` → `docs/rules/<slug>.rule.md` (normative reference)
  - `specs/<reference>.md` → `docs/concepts/<slug>.md` (conceptual reference)
  - `docs/<tutorial>.md` → `docs/tutorials/<slug>.md` (numbered: 01-*, 02-*)
  - `runbooks/<recipe>.md` → `docs/runbooks/<slug>.md`
  - `specs/*.schema.json` → `schemas/schema-*.json`
  - `.github/workflows/<gate>.yml` → `.github/workflows/<slug>.rule.yml` (paired)
  - Operational YAMLs (`specs/zombies-manifest.yaml`, `specs/co-edit-pairs.yaml`) stay in `specs/` — they are NOT rule or concept docs.

- **4.B — cross-reference rewrites** via throwaway `scripts/migrate_paths_v0.18.py`. Updates markdown links, Python imports, YAML path strings, JSON refs. Script is deleted at the end of 4.B (CHANGELOG entry is the historical record).

- **4.C — config + new tooling**:
  - Update `pyproject.toml`, `.pre-commit-config.yaml`, `.pre-commit-hooks.yaml`
  - Add 9 new tooling scripts (validators, generators, dispatcher)
  - Add 2 new disjoint schemas (`schema-rule-v1.json` + `schema-concept-v1.json`)
  - Add placeholder docs under `docs/concepts/` + `docs/tutorials/` (content rewrite in Slice 5)
  - Add 4 new tests (pairing validator drift fixtures, hook latency SLA, doc language, link integrity)
  - Extend `specs/zombies-manifest.yaml` with v4 entries for the path migrations
  - Bump VERSION 0.17.1 → 0.18.0
  - Append CHANGELOG v0.18.0 BREAKING entry with full migration table

## Impact

- **Consumers**: 5 own consumer repos (geeplo, eligia-core, palafito-b2b, nexandro, iguanatrader) will have `inherits_from:` paths in their AGENTS.md break; zombies-manifest v4 entries cover the auto-migration on the next playbook bump.
- **Tests**: existing test suite continues to pass (paths updated mechanically); 4 new test files add ~50 new test cases.
- **CI**: 5 new aggregated workflows (`validate-pairing.rule.yml`, `check-doc-language.rule.yml`, `check-link-integrity.rule.yml`, `check-agents-md-size.rule.yml`, `check-rule-schemas.rule.yml`).
- **Reviewability**: split into 3 sub-phases within one PR (4.A pure renames, 4.B mechanical link rewrite, 4.C content additions). Each phase has logical commit groups.

## Versioning

v0.18.0 starts the v0.18.x sequence for Slices 4-7 (per user direction 2026-05-19; v0.19.x reserved for post-review fixes; v0.20.0 is the final visible milestone).
