# caveman-ponytail-default-ultra

> **Status**: SCRATCH. Canonical contract = PR description. Satisfies the
> branch-name-validator. `openspec/changes/` gitignored — force-added.

## Why

Caveman and Ponytail already ship **default-ON at bootstrap with all components
enabled**, but at intensity `full`. The owner wants the strongest setting to be
the out-of-the-box default: maximum prose compression (Caveman) and maximum
code-minimalism / YAGNI discipline (Ponytail). The only dial not already at
maximum was the intensity **mode** — this change flips its default `full → ultra`.

## What

Default intensity for both features becomes `ultra` everywhere a mode is
defaulted (existing explicit settings are untouched — a state file or bundle
that names a mode still wins):

- **Bootstrap** — `_synthesize_defaults_bundle` enables caveman + ponytail at
  `"mode": "ultra"`.
- **Toggles** — `caveman/toggle.default_state()` and `ponytail/toggle.DEFAULT_MODE`
  → `ultra` (the OFF-state placeholder + the `on`-without-`--mode` default).
- **CLIs** — `caveman on --mode` default → `ultra` (ponytail's already reads
  `DEFAULT_MODE`).
- **apply_config** — the `intent.get("mode", …)` fallback for caveman/ponytail
  sections that omit a mode → `ultra`.
- **Config UI** — `features-inventory.json` `default_mode` → `ultra` (+ sidecar);
  the dashboard panel's mode-display fallback → `ultra`.
- **Docs** — caveman/ponytail toggle runbooks and `skills/ponytail/SKILL.md`
  now state `ultra` as the default.

Tests updated: every assertion that pinned the *default* (no explicit `--mode`)
to `full` now expects `ultra`; tests that pass `--mode full` explicitly are
unchanged.

## Out of scope

- **`caveman compress`** (the manual doc-compression command) keeps its `--mode`
  default at `full` — it is a separate, explicit tool, not the activation
  intensity, and `ultra` compression is often too lossy as a blind default.
- **The playbook's own dogfood state** (`.ai-playbook/ponytail.json` + the
  `ruleset:full` block in this repo's `AGENTS.md`) stays at `full` — an explicit
  choice, separable from the default. Re-materialising it to `ultra` is an
  offered follow-up, not bundled here.
