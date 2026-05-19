# v0191-cleanup-telemetry — wire telemetry + retroactive v0.18.0 tag + archive cleanup + mkdocs nav

## Why

The v0.19.0 pull-model migration closed the largest pending architectural gap, but the v0.18.x audit (see CHANGELOG v0.18.3 "Known gaps") left four secondary items unresolved:

1. **`v0.18.0` tag never created** — Slice 4 shipped at SHA `d612350` with `VERSION=0.18.0`, but the tag was missed at merge time. Local + remote tag listings jumped from `v0.17.1` to `v0.18.1`.
2. **Telemetry logger unwired** — `scripts/telemetry/rule_event_logger.py` shipped in v0.18.2 (Slice 6) with a full schema and a fail-safe `log_event()` API, but no `scripts/rules/*.rule.py` script imports it. Telemetry collection is a no-op for every rule.
3. **OpenSpec changes never archived** — 20 directories under `openspec/changes/` represent already-shipped slices (v0.15.0 -> v0.19.0). `openspec/changes/archive/` does not exist. The audit gap surfaces as noise in `openspec list` and obscures actually-active proposals.
4. **mkdocs nav gaps** — `mkdocs.yml` references only a subset of `docs/{runbooks,tutorials}/` files; the rest are discoverable only via search. Not a blocker but contributes to a "polish incomplete" feel.

This slice closes all four mechanically. None is BREAKING.

## What Changes

- **Retroactive tag `v0.18.0`** at SHA `d612350` (Slice 4 merge SHA where VERSION first read `0.18.0`). Annotated tag message documents the retroactive nature.
- **`scripts/rules/_telemetry.py` (new helper)** — exposes `cli_emit(slug, main_fn, argv=None)` that times a rule script's `main()` call, maps the exit code to a `rule-event/v1` verdict (`0=allow`, `1=block`, `>=2=warn`), and forwards to `scripts.telemetry.rule_event_logger.log_event`. Fail-safe: logger exceptions never alter the rule's rc.
- **29 rule scripts re-wired** — every `scripts/rules/<slug>.rule.py`'s `__main__` block calls `cli_emit("<slug>", main)`.
- **`tests/test_rules_telemetry.py` (new)** — 9 tests covering verdict mapping, rc passthrough, JSONL write, fail-safe behaviour, argv handling.
- **20 openspec changes moved to `openspec/changes/archive/`** — every shipped slice.
- **`mkdocs.yml` nav completeness** — every doc under `docs/{rules,concepts,runbooks,tutorials}/` appears under the corresponding nav section.

## Impact

- **Non-breaking.** Rule scripts' CLI contracts unchanged.
- **Telemetry is now ACTIVE** at the CLI invocation surface. Every invocation appends a JSONL row to `<consumer>/.ai-playbook-state/rule-events.jsonl`.
- **`openspec list`** no longer surfaces 20 stale entries.
- **`mkdocs build --strict`** still passes; navigation now complete.

## Versioning

`VERSION` bumps 0.19.0 -> **0.19.1**. Second fix iteration in the v0.19.x stream; v0.20.0 remains gated on explicit user OK.
