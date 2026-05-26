/* ai-playbook config UI — vanilla JS, no build, no framework.
 *
 * Loads three inventories + a defaults bundle from the same directory, lets
 * the user toggle rules / caveman / global flags, and exports a sparse
 * ai-playbook-config/v1 bundle JSON that scripts/apply_config.py consumes.
 *
 * file:// note: modern browsers block fetch() from file:// in many cases.
 * The footer hint documents `python -m http.server` as the workaround.
 */
(function () {
  "use strict";

  // ------- State -------
  let inv = { rules: [], features: {}, globalFlags: [] };
  let defaults = null;       // the full defaults bundle
  let state = null;          // current working state (cloned from defaults at init)
  let activeTab = "rules";
  let rulesFilter = { search: "", modified: false, hasAdvanced: false, hasBreakGlass: false };
  let expandedSlugs = new Set();

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ------- Init -------
  async function init() {
    try {
      const [rulesInv, featuresInv, globalFlagsInv, defaultsJson] = await Promise.all([
        fetch("rules-inventory.json").then(r => r.json()),
        fetch("features-inventory.json").then(r => r.json()),
        fetch("global-flags-inventory.json").then(r => r.json()),
        fetch("defaults.json").then(r => r.json()),
      ]);
      inv.rules = rulesInv.rules || [];
      inv.features = featuresInv.features || {};
      inv.globalFlags = globalFlagsInv.flags || [];
      defaults = defaultsJson;
      // Initial state precedence:
      //   1) window.APPLIED_CONFIG injected by ../../applied-config.js (the
      //      last bundle persisted by scripts/apply_config.py). This is the
      //      "current applied state" view that lets the UI render what's
      //      actually live in this consumer.
      //   2) defaults.json (no apply yet, or sidecar missing).
      // The two are merged: defaults provides the structural skeleton, and
      // APPLIED_CONFIG overlays any sparse modifications.
      const baseline = deepClone(defaults);
      const appliedConfig = (typeof window !== "undefined" ? window.APPLIED_CONFIG : null);
      if (appliedConfig && appliedConfig.schema === "ai-playbook-config/v1") {
        if (appliedConfig.rules) baseline.rules = deepClone(appliedConfig.rules);
        if (appliedConfig.features) {
          baseline.features = baseline.features || {};
          Object.entries(appliedConfig.features).forEach(([k, f]) => {
            baseline.features[k] = deepClone(f);
          });
        }
        if (appliedConfig.global_flags) baseline.global_flags = deepClone(appliedConfig.global_flags);
        banner("success", `Loaded applied state from ${appliedConfig.generated_at || "previous apply"} (generated_by: ${appliedConfig.generated_by || "unknown"}).`);
      } else if (window.APPLIED_CONFIG_MISSING) {
        // Sidecar absent → first-time use. No banner; defaults are fine.
      }
      state = baseline;
      wireEvents();
      renderAll();
      updateCounters();
    } catch (err) {
      banner(
        "error",
        "Failed to load inventories (file:// CORS?). Run `python -m http.server` from this directory. Details: " + err.message
      );
    }
  }

  function deepClone(x) { return JSON.parse(JSON.stringify(x)); }

  // ------- Event wiring -------
  function wireEvents() {
    $$(".tab").forEach(t => t.addEventListener("click", () => showTab(t.dataset.tab)));
    $("#btn-import").addEventListener("click", () => $("#file-import").click());
    $("#file-import").addEventListener("change", onImportFile);
    $("#btn-export").addEventListener("click", onExport);
    $("#btn-reset").addEventListener("click", onReset);
    $("#rules-search").addEventListener("input", (e) => { rulesFilter.search = e.target.value.toLowerCase(); renderRules(); });
    $("#filter-modified").addEventListener("change", (e) => { rulesFilter.modified = e.target.checked; renderRules(); });
    $("#filter-has-advanced").addEventListener("change", (e) => { rulesFilter.hasAdvanced = e.target.checked; renderRules(); });
    $("#filter-break-glass").addEventListener("change", (e) => { rulesFilter.hasBreakGlass = e.target.checked; renderRules(); });
    wireNextSteps();
  }

  function wireNextSteps() {
    const dismiss = $("#ns-dismiss");
    if (dismiss) dismiss.addEventListener("click", () => { $("#next-steps").hidden = true; });
    $$("[data-copy]").forEach(btn => btn.addEventListener("click", () => onCopy(btn)));
  }

  async function onCopy(btn) {
    const target = $("#" + btn.dataset.copy);
    if (!target) return;
    const text = target.textContent;
    const restore = () => { btn.textContent = "Copy"; };
    const done = () => { btn.textContent = "Copied ✓"; setTimeout(restore, 1500); };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        done();
        return;
      }
      throw new Error("clipboard API unavailable");
    } catch (e) {
      // Fallback: select + execCommand
      try {
        const range = document.createRange();
        range.selectNodeContents(target);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand("copy");
        sel.removeAllRanges();
        done();
      } catch (_) {
        banner("error", "Could not copy. Select the text manually.");
      }
    }
  }

  function showTab(name) {
    activeTab = name;
    $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
    $$(".panel").forEach(p => {
      const id = p.id.replace("panel-", "");
      p.hidden = id !== name;
      p.classList.toggle("active", id === name);
    });
    if (name === "preview") renderPreview();
    if (name === "dashboard" && typeof window.DashboardRender === "object" && window.DashboardRender !== null) {
      try { window.DashboardRender.mount("#dashboard-root"); }
      catch (err) { console.error("dashboard mount failed:", err); }
    }
  }

  // ------- Render -------
  function renderAll() {
    renderRules();
    renderFeatures();
    renderGlobalFlags();
  }

  function renderRules() {
    const list = $("#rules-list");
    list.innerHTML = "";
    const items = inv.rules.filter(rule => {
      const override = state.rules[rule.slug];
      const modified = !!override;
      const hasAdv = !!(rule.advanced && rule.advanced.length);
      const hasBG = !!rule.break_glass_env;
      if (rulesFilter.modified && !modified) return false;
      if (rulesFilter.hasAdvanced && !hasAdv) return false;
      if (rulesFilter.hasBreakGlass && !hasBG) return false;
      if (rulesFilter.search) {
        const hay = (rule.slug + " " + (rule.description || "") + " " + (rule.status || "")).toLowerCase();
        if (!hay.includes(rulesFilter.search)) return false;
      }
      return true;
    });
    items.forEach(rule => list.appendChild(renderRuleRow(rule)));
  }

  function renderRuleRow(rule) {
    const override = state.rules[rule.slug];
    const enabled = override ? override.enabled !== false : true;
    const layers = (override && override.layers) || {};
    const advancedVals = (override && override.advanced) || {};
    const reason = (override && override.reason) || "";
    const expanded = expandedSlugs.has(rule.slug);

    const li = document.createElement("li");
    li.className = "rule";
    if (override) li.classList.add("modified");
    if (!enabled) li.classList.add("disabled");
    if (expanded) li.classList.add("expanded");

    const layerBadge = (L) => {
      if (L === "L1" && !rule.has_l1) return `<span class="badge layer">—</span>`;
      if (L === "L3" && !rule.has_l3) return `<span class="badge layer">—</span>`;
      const present = layers[L] !== undefined ? layers[L] : enabled;
      return `<span class="badge layer ${present ? "on" : "off"}">${L}${present ? "✓" : "✗"}</span>`;
    };

    li.innerHTML = `
      <div class="rule-header">
        <label class="master">
          <input type="checkbox" data-master="${rule.slug}" ${enabled ? "checked" : ""} />
        </label>
        <span class="slug">${escapeHtml(rule.slug)}</span>
        <div class="badges">
          <span class="badge ${rule.status}">${escapeHtml(rule.status)}</span>
          ${layerBadge("L1")}
          <span class="badge layer">L2</span>
          ${layerBadge("L3")}
          ${rule.break_glass_env ? `<span class="badge bg" title="${escapeHtml(rule.break_glass_env)}">break-glass</span>` : ""}
        </div>
        <button class="rule-toggle-advanced" data-toggle-adv="${rule.slug}">${expanded ? "hide ▴" : "advanced ▾"}</button>
      </div>
      <div class="rule-meta">${escapeHtml(rule.description || "")}</div>
      <div class="rule-advanced">
        <h4>Layers</h4>
        <div class="layer-row">
          <label><input type="checkbox" data-layer="${rule.slug}:L1" ${rule.has_l1 ? "" : "disabled"} ${layerValue(layers, "L1", enabled, rule.has_l1) ? "checked" : ""} /> L1 (hook + rule.py)</label>
          <label><input type="checkbox" data-layer="${rule.slug}:L2" ${layerValue(layers, "L2", enabled, true) ? "checked" : ""} /> L2 (markdown)</label>
          <label><input type="checkbox" data-layer="${rule.slug}:L3" ${rule.has_l3 ? "" : "disabled"} ${layerValue(layers, "L3", enabled, rule.has_l3) ? "checked" : ""} /> L3 (workflow)</label>
        </div>
        ${rule.advanced && rule.advanced.length ? `
        <h4>Advanced sub-toggles</h4>
        ${rule.advanced.map(adv => `
          <div class="adv-row">
            <label><input type="checkbox" data-adv="${rule.slug}:${adv.key}" ${advancedValue(advancedVals, adv) ? "checked" : ""} /> ${escapeHtml(adv.label)}</label>
            <div class="desc">${escapeHtml(adv.description)} <code>env: ${escapeHtml(adv.env_var)}</code></div>
          </div>
        `).join("")}
        ` : ""}
        ${rule.break_glass_env ? `
        <h4>Reason (required for break-glass rules)</h4>
        <div class="reason-row">
          <textarea data-reason="${rule.slug}" placeholder="Explain why this rule (or layer) is disabled. Minimum 10 characters.">${escapeHtml(reason)}</textarea>
          <div class="reason-warn" data-reason-warn="${rule.slug}" ${reason.length >= 10 || enabled ? "hidden" : ""}>⚠ Persistent disable requires a reason of at least 10 characters.</div>
        </div>` : ""}
      </div>
    `;

    li.querySelector(`[data-master="${rule.slug}"]`).addEventListener("change", (e) => onMasterToggle(rule, e.target.checked));
    li.querySelector(`[data-toggle-adv="${rule.slug}"]`).addEventListener("click", () => toggleExpanded(rule.slug));
    li.querySelectorAll("[data-layer]").forEach(cb => cb.addEventListener("change", (e) => onLayerToggle(rule, e.target.dataset.layer.split(":")[1], e.target.checked)));
    li.querySelectorAll("[data-adv]").forEach(cb => cb.addEventListener("change", (e) => onAdvancedToggle(rule, e.target.dataset.adv.split(":")[1], e.target.checked)));
    const reasonEl = li.querySelector(`[data-reason="${rule.slug}"]`);
    if (reasonEl) reasonEl.addEventListener("input", (e) => onReasonChange(rule, e.target.value));

    return li;
  }

  function layerValue(layers, L, enabled, has) {
    if (!has) return false;
    if (layers[L] !== undefined) return layers[L];
    return enabled;
  }
  function advancedValue(advancedVals, adv) {
    if (advancedVals[adv.key] !== undefined) return advancedVals[adv.key];
    return adv.default;
  }

  function renderFeatures() {
    const wrap = $("#features-list");
    wrap.innerHTML = "";
    Object.entries(inv.features).forEach(([key, def]) => {
      const stateF = (state.features && state.features[key]) || {};
      const enabled = !!stateF.enabled;
      const mode = stateF.mode || def.default_mode || "full";
      const components = stateF.components || {};
      const div = document.createElement("div");
      div.className = "feature";
      div.innerHTML = `
        <h2>${escapeHtml(def.label)}</h2>
        <div class="desc">${escapeHtml(def.description)}</div>
        ${anyHasSideEffects(def) ? `<div class="side-effects">⚠ Enabling this feature modifies files in the consumer (AGENTS.md, .mcp.json). All mutations are backed up under .ai-playbook/backups/ first.</div>` : ""}
        <div class="row">
          <label><input type="checkbox" data-feature-enabled="${key}" ${enabled ? "checked" : ""} /> Enabled</label>
          <label>Mode:
            <select data-feature-mode="${key}" ${enabled ? "" : "disabled"}>
              ${(def.modes || []).map(m => `<option value="${m}" ${m === mode ? "selected" : ""}>${m}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="component-list">
          ${(def.components || []).map(c => `
            <div class="component">
              <label>
                <input type="checkbox" data-feature-component="${key}:${c.key}" ${components[c.key] ? "checked" : ""} ${enabled ? "" : "disabled"} />
                <strong>${escapeHtml(c.label)}</strong>
              </label>
              <div class="desc">${escapeHtml(c.description)}${c.side_effects && c.side_effects.length ? ` <em>(side effects: ${c.side_effects.map(escapeHtml).join(", ")})</em>` : ""}</div>
            </div>
          `).join("")}
        </div>
      `;
      div.querySelector(`[data-feature-enabled="${key}"]`).addEventListener("change", (e) => onFeatureEnabled(key, e.target.checked));
      div.querySelector(`[data-feature-mode="${key}"]`).addEventListener("change", (e) => onFeatureMode(key, e.target.value));
      div.querySelectorAll(`[data-feature-component]`).forEach(cb => cb.addEventListener("change", (e) => {
        const [k, comp] = e.target.dataset.featureComponent.split(":");
        onFeatureComponent(k, comp, e.target.checked);
      }));
      wrap.appendChild(div);
    });
  }

  function anyHasSideEffects(featureDef) {
    return (featureDef.components || []).some(c => c.side_effects && c.side_effects.length);
  }

  function renderGlobalFlags() {
    const wrap = $("#global-list");
    wrap.innerHTML = "";
    inv.globalFlags.forEach(flag => {
      const val = (state.global_flags && state.global_flags[flag.key] !== undefined)
        ? state.global_flags[flag.key]
        : flag.default;
      const div = document.createElement("div");
      div.className = "global-flag";
      div.innerHTML = `
        <label><input type="checkbox" data-flag="${flag.key}" ${val ? "checked" : ""} /> <strong>${escapeHtml(flag.label)}</strong></label>
        <div class="desc">${escapeHtml(flag.description)}</div>
        <div class="env">→ <code>${escapeHtml(flag.env_var)}=${escapeHtml(val ? flag.value_on : (flag.value_off || "(unset)"))}</code></div>
      `;
      div.querySelector(`[data-flag="${flag.key}"]`).addEventListener("change", (e) => onGlobalFlag(flag.key, e.target.checked));
      wrap.appendChild(div);
    });
  }

  function renderPreview() {
    $("#preview-json").textContent = JSON.stringify(toExportBundle(), null, 2);
  }

  // ------- Handlers -------
  function ensureRuleEntry(slug) {
    if (!state.rules[slug]) state.rules[slug] = { enabled: true };
    return state.rules[slug];
  }

  function dropRuleIfClean(slug) {
    const e = state.rules[slug];
    if (!e) return;
    const layersClean = !e.layers || (["L1","L2","L3"].every(L => e.layers[L] === undefined || e.layers[L] === true));
    const advClean = !e.advanced || Object.values(e.advanced).every(v => {
      // "clean" means equal to inventory default for that adv key
      return v === true;  // best-effort; precise check requires inventory lookup
    });
    if (e.enabled !== false && layersClean && advClean && !e.reason) {
      delete state.rules[slug];
    }
  }

  function onMasterToggle(rule, checked) {
    const e = ensureRuleEntry(rule.slug);
    e.enabled = checked;
    if (checked) {
      // Re-enabling: clear disabled_at and reason (unless user kept it).
      delete e.disabled_at;
    } else {
      e.disabled_at = new Date().toISOString();
    }
    dropRuleIfClean(rule.slug);
    refreshRule(rule.slug);
  }

  function onLayerToggle(rule, layer, checked) {
    const e = ensureRuleEntry(rule.slug);
    e.layers = e.layers || {};
    e.layers[layer] = checked;
    // Clean up the layers object: drop entries that match enabled.
    const eff = e.enabled !== false;
    if (e.layers[layer] === eff) delete e.layers[layer];
    if (Object.keys(e.layers).length === 0) delete e.layers;
    dropRuleIfClean(rule.slug);
    refreshRule(rule.slug);
  }

  function onAdvancedToggle(rule, key, checked) {
    const e = ensureRuleEntry(rule.slug);
    e.advanced = e.advanced || {};
    e.advanced[key] = checked;
    // Drop adv entry if it matches inventory default.
    const adv = (rule.advanced || []).find(a => a.key === key);
    if (adv && checked === adv.default) delete e.advanced[key];
    if (Object.keys(e.advanced).length === 0) delete e.advanced;
    dropRuleIfClean(rule.slug);
    refreshRule(rule.slug);
  }

  function onReasonChange(rule, text) {
    const e = ensureRuleEntry(rule.slug);
    const trimmed = text.trim();
    if (trimmed) e.reason = trimmed; else delete e.reason;
    dropRuleIfClean(rule.slug);
    // Update reason warning visibility in place.
    const warn = document.querySelector(`[data-reason-warn="${rule.slug}"]`);
    if (warn) warn.hidden = (e.enabled !== false) || (trimmed.length >= 10);
    updateCounters();
  }

  function toggleExpanded(slug) {
    if (expandedSlugs.has(slug)) expandedSlugs.delete(slug); else expandedSlugs.add(slug);
    refreshRule(slug);
  }

  function refreshRule(slug) {
    const rule = inv.rules.find(r => r.slug === slug);
    if (!rule) return;
    const list = $("#rules-list");
    const existing = list.querySelector(`[data-master="${slug}"]`);
    if (!existing) return;
    const li = existing.closest(".rule");
    const newRow = renderRuleRow(rule);
    li.replaceWith(newRow);
    updateCounters();
  }

  function ensureFeature(key) {
    state.features = state.features || {};
    if (!state.features[key]) {
      const def = inv.features[key];
      state.features[key] = {
        enabled: false,
        mode: def.default_mode || "full",
        components: Object.fromEntries((def.components || []).map(c => [c.key, c.default])),
      };
    }
    return state.features[key];
  }

  function onFeatureEnabled(key, checked) {
    const f = ensureFeature(key);
    f.enabled = checked;
    renderFeatures();
    updateCounters();
  }
  function onFeatureMode(key, mode) {
    ensureFeature(key).mode = mode;
    updateCounters();
  }
  function onFeatureComponent(key, comp, checked) {
    ensureFeature(key).components[comp] = checked;
    updateCounters();
  }

  function onGlobalFlag(key, checked) {
    state.global_flags = state.global_flags || {};
    const def = inv.globalFlags.find(f => f.key === key);
    if (def && checked === def.default) {
      delete state.global_flags[key];
    } else {
      state.global_flags[key] = checked;
    }
    renderGlobalFlags();
    updateCounters();
  }

  // ------- Counters -------
  function updateCounters() {
    const rulesModified = Object.keys(state.rules || {}).length;
    $("#tab-count-rules").textContent = rulesModified ? `${rulesModified}/${inv.rules.length}` : `${inv.rules.length}`;
    const featuresModified = Object.values(state.features || {}).filter(f => f && f.enabled).length;
    $("#tab-count-features").textContent = `${featuresModified}/${Object.keys(inv.features).length}`;
    const flagsModified = Object.values(state.global_flags || {}).filter(v => v === true).length;
    $("#tab-count-global").textContent = `${flagsModified}/${inv.globalFlags.length}`;
  }

  // ------- Export / Import / Reset -------
  function toExportBundle() {
    // Sparse: only include sections that differ from defaults.
    const bundle = {
      schema: "ai-playbook-config/v1",
      generated_at: new Date().toISOString(),
      generated_by: "config-ui",
    };
    if (Object.keys(state.rules || {}).length > 0) {
      bundle.rules = deepClone(state.rules);
    }
    if (state.features && Object.keys(state.features).length > 0) {
      // Only include features explicitly touched (enabled true OR any non-default field).
      const featOut = {};
      Object.entries(state.features).forEach(([k, f]) => {
        if (!f) return;
        const def = inv.features[k];
        if (!def) return;
        const enabledNonDefault = !!f.enabled;  // default is false
        const modeNonDefault = f.mode && f.mode !== (def.default_mode || "full");
        const compsNonDefault = (def.components || []).some(c => f.components && f.components[c.key] !== c.default);
        if (enabledNonDefault || modeNonDefault || compsNonDefault) {
          featOut[k] = {
            enabled: !!f.enabled,
            mode: f.mode || def.default_mode || "full",
            components: { ...Object.fromEntries((def.components || []).map(c => [c.key, c.default])), ...f.components },
          };
        }
      });
      if (Object.keys(featOut).length > 0) bundle.features = featOut;
    }
    if (state.global_flags && Object.keys(state.global_flags).length > 0) {
      bundle.global_flags = deepClone(state.global_flags);
    }
    return bundle;
  }

  async function onExport() {
    // Block export if any disabled-with-break-glass rule has missing/short reason.
    const errors = [];
    Object.entries(state.rules || {}).forEach(([slug, e]) => {
      const inv_rule = inv.rules.find(r => r.slug === slug);
      if (!inv_rule || !inv_rule.break_glass_env) return;
      if (e.enabled !== false) return;
      const reason = (e.reason || "").trim();
      if (reason.length < 10) errors.push(`${slug} requires reason >=10 chars (currently ${reason.length})`);
    });
    if (errors.length > 0) {
      banner("error", "Cannot export — fix these issues first:\n• " + errors.join("\n• "));
      return;
    }
    const bundle = toExportBundle();
    const result = await pickAndSaveBundle(bundle);
    if (!result.ok) {
      if (result.reason !== "cancelled") banner("error", `Export failed: ${result.reason}`);
      return;
    }
    showNextSteps(result);
  }

  // ---- File System Access API + IndexedDB handle persistence ----
  //
  // Modern Chromium browsers expose showSaveFilePicker, which lets the user
  // pick the destination once and (after we store the FileSystemFileHandle in
  // IndexedDB) write subsequent exports without a dialog. This is the closest
  // we can get to "write directly into <consumer>/.ai-playbook/" from a
  // file:// HTML, because the browser sandbox forbids JS from writing to
  // arbitrary disk paths without an explicit user gesture.
  //
  // Firefox + Safari (no API): we fall back to a plain anchor-triggered
  // download. The Next Steps panel then includes a `mv`/`Move-Item` row so
  // the user can shift the file from ~/Downloads/ into place.
  const HANDLE_DB_NAME = "ai-playbook-config-ui";
  const HANDLE_STORE = "handles";
  const HANDLE_KEY = "applied-config-handle";

  function openHandleDb() {
    return new Promise((resolve, reject) => {
      if (!("indexedDB" in window)) { reject(new Error("indexedDB unavailable")); return; }
      const req = indexedDB.open(HANDLE_DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(HANDLE_STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function getStoredHandle() {
    try {
      const db = await openHandleDb();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(HANDLE_STORE, "readonly");
        const req = tx.objectStore(HANDLE_STORE).get(HANDLE_KEY);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error);
      });
    } catch (_) { return null; }
  }

  async function storeHandle(handle) {
    try {
      const db = await openHandleDb();
      await new Promise((resolve, reject) => {
        const tx = db.transaction(HANDLE_STORE, "readwrite");
        tx.objectStore(HANDLE_STORE).put(handle, HANDLE_KEY);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    } catch (_) { /* ignore — handle persistence is best-effort */ }
  }

  async function clearStoredHandle() {
    try {
      const db = await openHandleDb();
      await new Promise((resolve, reject) => {
        const tx = db.transaction(HANDLE_STORE, "readwrite");
        tx.objectStore(HANDLE_STORE).delete(HANDLE_KEY);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    } catch (_) { /* ignore */ }
  }

  async function verifyPermission(handle, mode) {
    const opts = { mode: mode || "readwrite" };
    try {
      if ((await handle.queryPermission(opts)) === "granted") return true;
      if ((await handle.requestPermission(opts)) === "granted") return true;
    } catch (_) { /* fall through */ }
    return false;
  }

  async function pickAndSaveBundle(bundle) {
    const text = JSON.stringify(bundle, null, 2) + "\n";

    if ("showSaveFilePicker" in window) {
      // Try the stored handle first (silent path: no dialog after the
      // initial setup).
      let handle = await getStoredHandle();
      let reused = false;
      if (handle) {
        if (await verifyPermission(handle, "readwrite")) {
          reused = true;
        } else {
          await clearStoredHandle();
          handle = null;
        }
      }
      if (!handle) {
        try {
          handle = await window.showSaveFilePicker({
            suggestedName: "applied-config.json",
            types: [{
              description: "ai-playbook config bundle",
              accept: { "application/json": [".json"] },
            }],
          });
          await storeHandle(handle);
        } catch (err) {
          if (err && err.name === "AbortError") return { ok: false, reason: "cancelled" };
          return { ok: false, reason: err.message || "save dialog failed" };
        }
      }
      try {
        const writable = await handle.createWritable();
        await writable.write(text);
        await writable.close();
        return { ok: true, mode: "direct", path: handle.name || "applied-config.json", reused };
      } catch (err) {
        // Stored handle may be stale (file deleted, drive unmounted). Clear
        // and let the user re-prompt on the next click.
        if (reused) await clearStoredHandle();
        return { ok: false, reason: err.message || "write failed" };
      }
    }

    // Fallback: download via anchor (Firefox / Safari / older browsers).
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "applied-config.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return { ok: true, mode: "download" };
  }

  function showNextSteps(result) {
    const aside = $("#next-steps");
    const info = $("#ns-saved-info");
    const moveBlock = $("#ns-move");
    if (!aside || !info || !moveBlock) return;
    if (result.mode === "direct") {
      info.textContent = result.reused
        ? `Saved directly to ${result.path} (reused the previously chosen location).`
        : `Saved directly to ${result.path}. Next exports will write to the same path without prompting.`;
      moveBlock.hidden = true;
    } else {
      info.textContent = "Saved to your browser's Downloads folder as applied-config.json. This browser doesn't support direct file writes from file://, so move it into place first.";
      moveBlock.hidden = false;
    }
    aside.hidden = false;
    aside.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function onImportFile(e) {
    const file = e.target.files[0];
    e.target.value = "";  // reset so re-importing the same file works
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        if (data.schema !== "ai-playbook-config/v1") {
          banner("error", `Wrong schema: expected ai-playbook-config/v1, got ${data.schema || "(missing)"}`);
          return;
        }
        // Merge into current state.
        state = deepClone(defaults);
        if (data.rules) state.rules = deepClone(data.rules);
        if (data.features) {
          state.features = state.features || {};
          Object.entries(data.features).forEach(([k, f]) => { state.features[k] = deepClone(f); });
        }
        if (data.global_flags) state.global_flags = deepClone(data.global_flags);
        renderAll();
        updateCounters();
        banner("success", `Imported ${file.name}. Review the tabs, then click Export to round-trip.`);
      } catch (err) {
        banner("error", `Failed to parse JSON: ${err.message}`);
      }
    };
    reader.readAsText(file);
  }

  function onReset() {
    if (!confirm("Reset all toggles to defaults? Unsaved changes will be lost.")) return;
    state = deepClone(defaults);
    expandedSlugs.clear();
    renderAll();
    updateCounters();
    banner("success", "Reset to defaults.");
  }

  // ------- UI helpers -------
  function banner(kind, msg) {
    const el = $("#banner");
    el.className = "banner " + kind;
    el.textContent = msg;
    el.hidden = false;
    if (kind === "success") setTimeout(() => { el.hidden = true; }, 4000);
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ------- Boot -------
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
