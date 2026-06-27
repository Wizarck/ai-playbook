# ponytail-dashboard-panel

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

The Ponytail feature (code-minimalism mode) ships skills, a toggle, and a
per-turn reinforcement hook, but its impact was invisible on the telemetry
dashboard — unlike its twin Caveman, which has a cost-saved panel. A reader
could not tell whether YAGNI discipline was actually happening. Separately, the
dashboard's cost-methodology link pointed at a path that did not resolve in a
consumer checkout, and the config UI rendered a "Mode" control for *every*
feature — including Graphify, which has no intensity modes and whose bundle
sub-schema forbids a `mode` key (so enabling Graphify exported an invalid
bundle).

## What

- **Ponytail discipline panel** — the code-minimalism twin of the Caveman panel.
  Honest by construction: counts real `ponytail:` markers in the consumer tree
  (no LLM self-report, no fabricated dollar figure).
  - rung-1 (stock): `scripts/ponytail/stats.py` counts markers tree-wide with
    ponytail-debt's exact regex; skips the vendored playbook checkout so the
    count is the consumer's own.
  - rung-2 option A (flow): `markers_added_since()` counts markers added within
    the dashboard window via git; omitted (never faked to `0`) when git can't
    answer.
  - `ponytail_state` + `panels.ponytail` are **additive on `dashboard-data/v1`**
    (optional, renderer guards absence — no schema-version bump). on/off/missing
    branching mirrors Caveman.
- **Methodology link fix** — corrects the dashboard's cost-methodology link to a
  valid relative path and adds the `#cost-methodology` anchor in
  `caveman-mode.md`.
- **Config-UI Mode gating** — render the Mode `<select>`, default state, and
  export `mode` only for features that declare `modes`. Graphify et al. no
  longer show an empty Mode dropdown or emit a schema-invalid `mode`. Adds a
  schema-invariant regression test (inventory `modes` ⇔ bundle-schema `mode`).
- **Rules-inventory fixup** — regenerate `config-ui/rules-inventory.json` (+ its
  `.js` sidecar) so the committed inventory includes `confirm-before-termination`
  (added in #137 without an inventory refresh, leaving `check-rule-schemas` red
  on `main`). Unblocks CI for this and any subsequent PR.

## Rung-2 deferral (documented, not built)

The considered-vs-built *ratio* and any token-cost extrapolation stay deferred
behind a named-buyer + emission-eval trigger (a BMAD party-mode critique judged
the self-reported denominator a vanity metric). Rung-2 here is the observable
*flow* count only.
