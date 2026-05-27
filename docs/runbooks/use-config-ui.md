---
schema: runbook/v1
slug: use-config-ui
title: Use the ai-playbook config UI
summary: |
  Step-by-step: build a config bundle in the HTML UI, apply it to a consumer
  via bootstrap or apply_config, verify the toggles took effect, source the
  env file in your shell init.
last_validated: "2026-05-25"
---

# Use the ai-playbook config UI

## When to read this

- You want to disable a rule for a hotfix window without touching `.claude/settings.json`.
- You want to flip `bash_inspection` off temporarily without remembering the exact env var name.
- You want to enable caveman in a specific mode + component set without memorising the CLI flags.
- You want to toggle a global flag (e.g. LLM routing strict mode) per-consumer.

Skip this runbook if you only need a one-shot override (use the rule's `break_glass` env var directly in the shell that runs the command).

## 0. Vocabulary refresher

- **Bundle**: a JSON file with schema `ai-playbook-config/v1` — both the **output** of the HTML UI and the **input** of `apply_config`. The applied copy is also the UI's source-of-truth on next open.
- **State files** on the consumer (all gitignored):
  - `.ai-playbook/applied-config.json` — the last bundle persisted by `apply_config`. Canonical source of truth for "what's live in this consumer". The UI reads it on open via a sibling JS sidecar (next bullet).
  - `.ai-playbook/applied-config.js` — auto-generated sidecar that assigns `window.APPLIED_CONFIG = <same JSON>`. Loaded by the UI via `<script src>` because browsers block `fetch()` from `file://`. Regenerated on every `apply_config` run.
  - `.ai-playbook/rules-toggle.json` — sparse rules overrides materialised by `apply_config`.
  - `.ai-playbook/caveman.json` — written by caveman's CLI; the bundle declares intent, not state.
  - `.ai-playbook/feature-flags.env` — marker-bracketed env block for advanced sub-toggles + global flags.
  - `.ai-playbook/rules-toggle-audit.jsonl` — append-only audit log of every apply.

## 1. Open the UI (double-click works)

The UI lives at `<consumer>/.ai-playbook/tools/config-ui/index.html` (delivered via the playbook git submodule). **Double-click the HTML file** from your file explorer — it opens in your default browser.

On open, the UI reads the consumer's current applied state:

- **First-time** (never ran `apply_config`): you see the all-ON baseline from `defaults.json`.
- **Returning** (sidecar present): you see whatever the last `apply_config` invocation persisted — the SAME state your rules / caveman / global flags are running with right now.

There is no "open the file separately, then go to localhost" choreography. Plain `file://` works because the sidecar is loaded via `<script src>`, which browsers permit even when `fetch()` is blocked.

**Fallback for the inventories**: the three inventory JSONs (`rules-inventory.json`, `features-inventory.json`, `global-flags-inventory.json`, `defaults.json`) ARE loaded via `fetch()`. Some browsers (newer Chrome, strict Firefox) block this from `file://`. If you see an error banner:

```
cd <consumer>/.ai-playbook/tools/config-ui && python -m http.server
# then visit http://localhost:8000/
```

The applied-state sidecar always works because of the `<script src>` mechanism.

## 2. Configure (seven tabs)

### Tab `Rules` (~50 entries)

Each row is one rule. The master checkbox is the binary on/off. Click `advanced ▾` to expand:

- Three checkboxes for L1 / L2 / L3 (layers the rule doesn't have are greyed).
- Any `bash_inspection`-style sub-toggle the rule declares (today only `apply-skill-enforcement` has one).
- A reason textarea — **required** if you disable a rule that has a `break_glass` env var declared (it's the persistent-disable equivalent of the shell-level override).

Filters in the topbar narrow the list by `Only modified`, `Has advanced`, `Has break-glass`, or a substring of slug / description / status.

### Tab `Features` (today: caveman)

Caveman has:
- A master `Enabled` checkbox.
- A `Mode` dropdown (`lite` / `full` / `ultra`).
- 6 component checkboxes. Tooltip + descriptions list side effects (AGENTS.md materialisation, `.mcp.json` wrapping). Side-effecting features get a red banner when enabled.

### Tab `Global flags`

Today's catalogue is a single flag (`llm_routing_strict`). Each row shows its env-var projection live (`AIPLAYBOOK_LLM_ROUTING_STRICT=1` when on, unset when off). Future flags land here as the inventory grows.

### Tab `Skills`

Per-skill enforcement opt-out (negative list). Each row is a skill discovered in `skills/`; default = enforced (materialised). Uncheck a row to add it to `.ai-playbook-state/skills-enforce.json` `disabled` array. Toolbar: search by slug/description, `Only disabled` filter, Enable-all / Disable-all bulk buttons, live `X/Y enforced (Z disabled)` summary.

### Tab `MCPs`

Same shape as Skills, scoped to MCP servers discovered in the base + project YAML layers. Uncheck a server to strip it from the rendered `.mcp.json` / `.gemini/settings.json`.

### Tab `Files` *(v0.19.7+)*

Read-only inspector of every managed file (AGENTS.md, .gitignore, .pre-commit-config.yaml, .coderabbit.yaml, .claude/settings.local.json, mcp-servers.project.yaml). The sidecar `<consumer>/.ai-playbook-state/files-state.js` (rebuilt automatically by `apply_config`; also regenerable manually with `python -m scripts.build_files_state`) feeds:

- **Left rail** — one row per file with badges: `<N>C` canonical block count, `<N>X` custom segment count, and a `<N> drift` chip when any block content diverges from the SHA in `applied-config.json`'s manifest.
- **Right inspector** — per-section preview with badges (canonical / drifted / custom), block id + SHA info, and (v2 / v3) curate controls:
  - File-level **Take playbook** / **Keep mine** buttons (set the default action for every block in the file).
  - Per-block radio buttons override the default for individual sections.
- **Restore from `.bak` dropdown** — surfaces every backup recorded in `<consumer>/.ai-playbook-state/backups/index.json`. Restore itself is CLI-only (`mv <file>.<ts>.bak <file>`); the UI shows the timestamps only — belt-and-suspenders against accidental destructive UI actions.

If the sidecar is missing (no apply has run yet on this consumer), the tab shows a "Regenerate state" hint with the exact command. The Files tab does NOT mutate disk by itself; everything is staged in the bundle until you click **Export bundle** and run `apply_config`. Concept doc: [`docs/concepts/bundle-managed-files.md`](../concepts/bundle-managed-files.md).

### Tab `Preview JSON`

Live render of the sparse bundle that `Export` will produce. Useful for review before downloading.

## 3. Export

Click `Export bundle`. Two paths, depending on your browser:

### Modern Chromium (Chrome 86+, Edge 86+) — direct save

The browser opens a `Save as` dialog. **The first time**, navigate to `<consumer>/.ai-playbook/` and save the file as `applied-config.json` (the filename is pre-filled). After this first save, the UI stores the `FileSystemFileHandle` in IndexedDB. **Subsequent exports** write to the same path without re-prompting — one click → file is on disk.

If the saved file is later moved or deleted and the handle goes stale, the next export silently re-prompts so you can pick the new location.

### Firefox / Safari — download fallback

The browser downloads `applied-config.json` to your usual Downloads folder. You'll move it into place from the Next Steps panel (see below).

### Validation

If you disabled a rule with `break_glass` and forgot the reason (or it's <10 chars), the export is blocked with a red banner listing each problem. Nothing is written until you fix it.

## 4. Apply — the Next Steps panel

Right after a successful export, a green panel appears below the topbar with:

1. **(Fallback browsers only)** A `Move-Item`/`mv` command to shift the file from `~/Downloads/` into `<consumer>/.ai-playbook/`.
2. **`python -m scripts.apply_config`** in two flavours (PowerShell + POSIX). Each has a one-click Copy button.
3. **A paste-able Claude Code prompt** that asks Claude to run the apply + verify the three state files were touched. Useful when you keep an open Claude Code session in this project — paste it into the chat instead of switching to a terminal.

Pick whichever is convenient. Both forms boil down to the same invocation. Run it from the **consumer root**:

```
python -m scripts.apply_config .ai-playbook/applied-config.json
```

The script prints a Markdown report by section (rules / caveman / global_flags / applied-bundle), each with `✅` or `❌` + detail. Errors in one section never block the others — re-run after fixing the issue.

After apply, `applied-config.js` is regenerated. **Re-open the HTML** to confirm the UI now shows the new applied state (look for the green banner saying "Loaded applied state from ...").

### At bootstrap time (alternative for fresh projects)

```
python -m scripts.bootstrap myproj --from-config /path/to/applied-config.json
```

The bundle is applied after the base bootstrap flow (after caveman default-on; the bundle wins on caveman state). The `.gitignore` of the new consumer gets the marker-bracketed entries automatically (`applied-config.json`, `applied-config.js`, `rules-toggle.json`, audit log, env file).

## 5. Source the env file in your shell

`feature-flags.env` is **not** auto-sourced. You must wire it into your shell init. Recommended via direnv:

```bash
# .envrc at the consumer root (also gitignored)
set -a; source .ai-playbook/feature-flags.env; set +a
```

Or in bashrc / fish init scoped to that project:

```bash
if [ -f "$HOME/projects/myproj/.ai-playbook/feature-flags.env" ]; then
  set -a; source "$HOME/projects/myproj/.ai-playbook/feature-flags.env"; set +a
fi
```

Verify with:

```bash
echo $AIPLAYBOOK_BASH_INSPECTION
echo $AIPLAYBOOK_LLM_ROUTING_STRICT
```

## 6. Verify the toggle took effect

### Rule toggle (L1)

```bash
python -m scripts.rules_toggle status --slug apply-skill-enforcement --layer L1
# Expected: "apply-skill-enforcement @ L1: OFF" (or ON)
```

Or do a smoke fire of the hook with a payload that normally blocks:

```bash
# In a consumer with an active OpenSpec change declaring be/foo.py as a write_path:
echo '{"tool_name":"Edit","tool_input":{"file_path":"be/foo.py"},"cwd":"'"$PWD"'","session_id":"t"}' \
  | python .claude/hooks/openspec-apply-enforce.py
# Expected when L1 OFF: exit 0 (was exit 2 before the toggle)
```

Telemetry confirms the short-circuit. Check `.ai-playbook-state/rule-events.jsonl` (or wherever `AI_PLAYBOOK_STATE_DIR` points) for an event with `verdict=warn`, `block_class=rule_disabled`, `toggle_layer=L1`.

### Caveman

```bash
python -m scripts.caveman status
# Expected: matches what you toggled (enabled, mode, components).
```

`AGENTS.md` should contain (or not) the block bounded by:

```
<!-- BEGIN auto-managed: caveman/ruleset:<mode> -->
...
<!-- END auto-managed -->
```

### Global flag

```bash
env | grep AIPLAYBOOK_LLM_ROUTING_STRICT
# Expected: AIPLAYBOOK_LLM_ROUTING_STRICT=1 (after sourcing — see step 5)
```

## 7. View the audit log

```bash
tail -5 .ai-playbook/rules-toggle-audit.jsonl | python -m json.tool
```

Every `apply_config` invocation appends one line per section (rules / caveman / global_flags) with `ts`, `actor`, `action`, `ok`, `detail`, `bundle`. Each `rules_toggle on/off` call also appends a line with `prev_state` + `new_state` + `reason`.

## 8. Restore the defaults

In the UI: click `Reset to defaults` then `Export`. Apply the resulting bundle.

Or per-section by CLI:

```bash
python -m scripts.rules_toggle on apply-skill-enforcement   # clears the rule override
python -m scripts.caveman off                                # disables caveman
# For global flags, edit feature-flags.env directly or re-apply a bundle with global_flags={} or false.
```

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| UI says "Failed to load inventories (file:// CORS?)" | Browser blocks `fetch()` from `file://`. | `cd tools/config-ui && python -m http.server` then visit http://localhost:8000/. |
| `Export` is blocked with "Cannot export — fix these issues first" | You disabled a break-glass rule without a reason ≥10 chars. | Expand the rule's advanced panel and fill the reason field. |
| Save dialog appears every time (Chromium) | You dismissed the dialog on the first export, so no handle was stored. Or you cleared site data / extended IndexedDB privacy mode is on. | Save normally on the next dialog; the handle persists from then on. |
| Save dialog appears again after a few exports (Chromium) | The previously chosen file was moved/renamed/deleted, so the stored handle went stale. The UI clears it silently. | Save to the same path again; the new handle replaces the stale one. |
| Browser asks for permission on every save (Chromium) | Site permissions reset on each browser session. | In the Chrome address bar, grant "Edit files on your device" permission persistently for this file:// origin. |
| Caveman section in the report shows `❌ caveman CLI exit 1` | The consumer is missing `AGENTS.md` (caveman needs it for materialisation) or has multiple caveman blocks. | Fix the consumer state per the caveman CLI's error message, then re-run `apply_config`. |
| Env vars don't appear in shell | `feature-flags.env` not sourced. | Add the `set -a; source ...` line to your shell init (see step 5). |
| `git status` shows `.ai-playbook/rules-toggle.json` as untracked | Bootstrap didn't patch `.gitignore` (or you predate the bootstrap version that did). | Add the three lines (toggle, audit, feature-flags.env) under `# ai-playbook integration` in the consumer's `.gitignore`. |

## Dashboard tab

The **Dashboard** tab is a per-consumer-repo telemetry surface inside this same HTML UI. It reads a pre-computed sidecar (`<consumer>/.ai-playbook/dashboard-data.js`) produced by `scripts/telemetry/build_dashboard_data.py` and renders hero + five panels. Same `file://` double-click entry as the rest of the UI; same SRI-pinned `<script>` tag for Chart.js; no install, no build, no server.

### Panels

- **Hero — Incidents prevented (7d).** Count of rule-event/v2 events with `verdict="block"` and no break-glass override. Warnings excluded. Sub-count below: **Prompt-injection blocks (OWASP LLM01)** — events where `escape_hatch` is set or `bash_pattern_kind` is set.
- **Secondary stats.** Obey-rate %, Caveman cost saved $ (with pricing-version timestamp), health emoji (🟢 ≥95%, 🟡 ≥85%, 🔴 <85%).
- **Obey-rate trend.** Per-day sparkline across the window.
- **Rule × LLM agreement matrix.** Per-rule obey-rate per LLM (Claude, Gemini, Cursor). Cells highlight drift in two senses: cross-LLM disagreement above threshold or per-LLM time-over-time delta above threshold.
- **Honesty meter.** Per-LLM agreement between the LLM's own `self_check` claim and the hook's `verdict`. Distinctive metric — SaaS observability tools cannot compute it because they do not run hooks.
- **Top friction rules.** Rules with the most break-glass overrides in the window, with top override reasons.
- **Caveman impact.** Activation rate, mode, components on/off, tokens delta, cost saved. Renders an explainer instead of charts when caveman is off or missing.

### Refresh

- **Automatic (default).** Every `python -m scripts.apply_config <bundle>` run regenerates the sidecar via a post-hook. The dashboard is at least as fresh as the last config change.
- **Manual.** The **Refresh** button on the Dashboard tab copies the aggregator command to the clipboard:

  ```text
  python -m scripts.telemetry.build_dashboard_data
  ```

  Run it from the consumer root, then reload the tab. Browsers cannot shell out from `file://`; the button copies-not-runs by design.

- **Opt-in cron.** Add the command to your operating system's scheduler if you want unattended refresh. Disabled by default.

### Empty state

First 100 events in this consumer show the pedagogical empty state instead of panels. The threshold is shipped in the sidecar (`empty_state_threshold`), tunable per consumer if needed.

### Privacy

The dashboard reads only the existing rule-event/v2 fields. Target paths render only in glob form (e.g., `*.env`); individual file paths never appear. Raw Bash commands are not in the source data at all. Session IDs in any per-developer breakdown are sha256-hashed. See [telemetry-design.md](../concepts/telemetry-design.md) for the full privacy contract.

### When charts don't appear

Chart.js loads from a SRI-pinned CDN (`cdn.jsdelivr.net`). If the CDN is unreachable, the integrity check fails, or your network blocks it (air-gapped, corporate proxy), the tab shows a `chart library failed to load` banner and renders the numeric values without charts. A native-SVG fallback rendering path is documented and ships in a later release.

## See also

- [ai-playbook-config.md](../concepts/ai-playbook-config.md) — concept doc with the architecture diagrams.
- [enforcement-layers.md](../concepts/enforcement-layers.md) — what L1 / L2 / L3 mean.
- [caveman-toggle.md](caveman-toggle.md) — caveman-specific operator runbook.
- [upgrade-to-bash-enforcement.md](upgrade-to-bash-enforcement.md) — v0.20.0 migration notes.
- [telemetry-dashboard.md](../concepts/telemetry-dashboard.md) — full Dashboard tab concept doc.
