# Fix plan — config-ui bugs surfaced by Playwright sweep

Two real bugs, both fixable in `config-ui/app.js` only. No other files affected. Total surface: ~15 LOC.

## Bug 1 (blocker) — `init()` dies on any inventory fetch failure

### What happens

[config-ui/app.js:29-35](config-ui/app.js#L29-L35):

```js
const [rulesInv, featuresInv, globalFlagsInv, skillsInv, mcpsInv, defaultsJson] = await Promise.all([
  fetch("rules-inventory.json").then(r => r.json()),                                                  // no catch
  fetch("features-inventory.json").then(r => r.json()),                                               // no catch
  fetch("global-flags-inventory.json").then(r => r.json()),                                           // no catch
  fetch("skills-inventory.json").then(r => r.json()).catch(() => ({ skills: [] })),                   // catch
  fetch("mcps-inventory.json").then(r => r.json()).catch(() => ({ servers: [] })),                    // catch
  fetch("defaults.json").then(r => r.json()),                                                         // no catch
]);
```

When the page is opened via `file://`, modern browsers block `fetch()` against local files. The first rejection collapses `Promise.all`, the `try` block throws, `wireEvents()` + `renderAll()` never run, and every tab is dead. Same failure mode if any inventory file is missing or malformed.

### Fix

Add a `.catch(() => fallback)` to each of the 4 unprotected fetches, and track the offline count so the banner gives a useful explanation instead of "Failed to fetch".

```js
let offlineCount = 0;
const onFail = (fallback) => () => { offlineCount++; return fallback; };

const [rulesInv, featuresInv, globalFlagsInv, skillsInv, mcpsInv, defaultsJson] = await Promise.all([
  fetch("rules-inventory.json").then(r => r.json()).catch(onFail({ rules: [] })),
  fetch("features-inventory.json").then(r => r.json()).catch(onFail({ features: {} })),
  fetch("global-flags-inventory.json").then(r => r.json()).catch(onFail({ flags: [] })),
  fetch("skills-inventory.json").then(r => r.json()).catch(onFail({ skills: [] })),
  fetch("mcps-inventory.json").then(r => r.json()).catch(onFail({ servers: [] })),
  fetch("defaults.json").then(r => r.json()).catch(onFail({ schema: "ai-playbook-config/v1" })),
]);
```

Then, after the init block succeeds, replace the catastrophic banner ([config-ui/app.js:80-83](config-ui/app.js#L80-L83)) with a contextual one:

```js
if (offlineCount > 0) {
  banner(
    "info",
    `Offline mode: ${offlineCount} inventory file(s) could not be loaded ` +
    `(likely file:// CORS). The UI is running on reduced data. For full ` +
    `functionality, run \`python -m http.server\` from this directory.`
  );
}
```

The outer `try/catch` stays as a safety net for any unforeseen exception, but the common case (file:// fetch denial) no longer hits it.

### Why this works

- `inv.rules = rulesInv.rules || []` and siblings at [config-ui/app.js:37-41](config-ui/app.js#L37-L41) already handle empty/missing structure defensively. The fallbacks above produce shapes that satisfy those `|| []` / `|| {}` chains.
- `defaults.json` fallback is the schema literal alone — when no defaults are available, the merge logic at [config-ui/app.js:51-74](config-ui/app.js#L51-L74) seeds empty `skills_enforce`/`mcps_enforce` containers and uses `APPLIED_CONFIG` if present. The UI is usable for Preview JSON / Dashboard even with no inventory data.
- The Playwright sweep's 5 Scenario A blockers all collapse to a single "offline mode" info banner — confirmed by re-running [config-ui/.test/sweep.mjs](config-ui/.test/sweep.mjs) after the fix.

## Bug 2 (broken) — `#skills-summary` and `#mcps-summary` go stale after individual toggles

### What happens

[config-ui/app.js:390-395](config-ui/app.js#L390-L395) (`toggleSkillEnforced`) updates `state.skills_enforce.disabled` and calls `updateCounters()` (which updates the tab BADGE count) but does NOT update the `#skills-summary` text. That text is written only inside `renderSkillsEnforce()` at [config-ui/app.js:433-436](config-ui/app.js#L433-L436), and the individual-toggle change handler at [config-ui/app.js:425-429](config-ui/app.js#L425-L429) does NOT call `renderSkillsEnforce()` (deliberately, to avoid re-rendering the whole list).

Same bug, same pattern, at [config-ui/app.js:439-444](config-ui/app.js#L439-L444) + [config-ui/app.js:480-484](config-ui/app.js#L480-L484) for MCPs.

The Enable-all / Disable-all buttons at [config-ui/app.js:107](config-ui/app.js#L107) and [config-ui/app.js:109-113](config-ui/app.js#L109-L113) DO call `renderSkillsEnforce()`, so they update the summary correctly. Only individual toggles are broken.

### Fix

Extract a lightweight summary updater and call it from both the toggle handler and the renderer:

```js
function updateSkillsSummary() {
  const summary = $("#skills-summary");
  if (!summary) return;
  const disabledSize = (state.skills_enforce.disabled || []).length;
  summary.textContent =
    `${inv.skills.length - disabledSize}/${inv.skills.length} enforced (${disabledSize} disabled)`;
}

function toggleSkillEnforced(slug, enforced) {
  const set = new Set(state.skills_enforce.disabled || []);
  if (enforced) set.delete(slug); else set.add(slug);
  state.skills_enforce.disabled = [...set].sort();
  updateCounters();
  updateSkillsSummary();   // <-- NEW
}
```

Inside `renderSkillsEnforce()` (L397-437), replace the inline summary block at L433-436 with a single call to `updateSkillsSummary()` — keeps the logic in one place.

Mirror the same change for MCPs (`updateMcpsSummary`, called from `toggleMcpEnforced` + inside `renderMcpsEnforce`).

### Why not just re-render?

Adding `renderSkillsEnforce()` to the toggle handler would work but:
- re-creates every list item → loses scroll position + any input focus mid-edit
- wastes work on the other ~77 unchanged rows
- defeats the explicit design at L427-428 that only mutates the toggled row's class and (if filtered) removes it

The summary updater approach is local, O(1), and matches the intent of the existing handler.

## Files touched

- `config-ui/app.js` only. Both bugs.
- No HTML/CSS changes. No schema or test changes.
- Existing test `tests/test_config_ui_smoke.py` covers presence + sidecar src; doesn't reach into init() error handling. **Add 2 small smoke checks**:
  - `assert "offlineCount" in app_js` (Bug 1 fix shipped)
  - `assert "updateSkillsSummary" in app_js` (Bug 2 fix shipped)

## Verification

1. `pytest tests/test_config_ui_smoke.py` — passes (existing + 2 new assertions).
2. Re-run `node config-ui/.test/sweep.mjs` — expect:
   - Scenario A: 5 blockers → 0 blockers + 1 "info" finding for the offline banner (or just zero findings if we don't auto-log info).
   - Scenario B: 1 broken (`B-skills-summary`) → 0 findings.
3. Manual: open `file://...config-ui/index.html` → see info banner, Preview JSON tab renders schema literal, no tab is catastrophically empty.
4. Manual: open under http server, toggle one skill checkbox individually → `#skills-summary` text changes immediately.

## Out of scope

- Same root-cause analysis for the rules/features tabs (they DO call `renderRules`/`renderFeatures` on toggle, so they self-update). No work needed there.
- Sidecar-load resilience improvements (`applied-config.js` / `files-state.js` / `dashboard-data.js` already have `onerror` flags). Working as designed.

## Estimated diff

~15 LOC across one file. Single commit: `fix(config-ui): degrade init() gracefully + fix enforce-summary staleness`.
