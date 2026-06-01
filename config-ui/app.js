/* ai-playbook config UI — vanilla JS, no build, no framework.
 *
 * Loads the inventories + a defaults bundle from the same directory, lets the
 * user toggle rules / caveman / global flags, and exports a sparse
 * ai-playbook-config/v1 bundle JSON that scripts/apply_config.py consumes.
 *
 * file:// note: modern browsers block fetch() from file:// (CORS) but permit
 * <script src>. So each inventory ships a `.js` sidecar (built by
 * scripts/build_ui_sidecars.py) that sets a window global; init() prefers that
 * global and only falls back to fetch() when served over http(s) — making the
 * UI a true double-click HTML with no local server required.
 */
(function () {
  "use strict";

  // ------- State -------
  let inv = { rules: [], features: {}, globalFlags: [], skills: [], mcps: [] };
  let defaults = null;       // the full defaults bundle
  let state = null;          // current working state (cloned from defaults at init)
  let activeTab = "rules";
  let rulesFilter = { search: "", modified: false, hasAdvanced: false, hasBreakGlass: false };
  let skillsFilter = { search: "", onlyDisabled: false };
  let mcpsFilter = { search: "", onlyDisabled: false };
  let expandedSlugs = new Set();

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ------- Init -------
  async function init() {
    // Per-fetch fallbacks so a single failure (file:// CORS, missing file,
    // malformed JSON) never collapses Promise.all and kills the entire UI.
    // offlineCount drives a contextual "offline mode" banner after init.
    let offlineCount = 0;
    const onFail = (fallback) => () => { offlineCount++; return fallback; };
    // Prefer an inventory injected as a window global by its <name>.js sidecar
    // (works under file://); fall back to fetch() of the .json over http(s) or
    // when the sidecar is absent. offlineCount only increments when BOTH the
    // global and the fetch fail — so the offline banner stays quiet when the
    // sidecars are present (the common double-click case).
    const loadInv = (globalName, url, fallback) => {
      const g = (typeof window !== "undefined") ? window[globalName] : undefined;
      if (g !== undefined && g !== null) return Promise.resolve(g);
      return fetch(url).then(r => r.json()).catch(onFail(fallback));
    };
    try {
      const [rulesInv, featuresInv, globalFlagsInv, skillsInv, mcpsInv, defaultsJson] = await Promise.all([
        loadInv("RULES_INVENTORY", "rules-inventory.json", { rules: [] }),
        loadInv("FEATURES_INVENTORY", "features-inventory.json", { features: {} }),
        loadInv("GLOBAL_FLAGS_INVENTORY", "global-flags-inventory.json", { flags: [] }),
        loadInv("SKILLS_INVENTORY", "skills-inventory.json", { skills: [] }),
        loadInv("MCPS_INVENTORY", "mcps-inventory.json", { servers: [] }),
        loadInv("DEFAULTS", "defaults.json", { schema: "ai-playbook-config/v1" }),
      ]);
      inv.rules = rulesInv.rules || [];
      inv.features = featuresInv.features || {};
      inv.globalFlags = globalFlagsInv.flags || [];
      inv.skills = skillsInv.skills || [];
      inv.mcps = mcpsInv.servers || [];
      defaults = defaultsJson;
      // Initial state precedence:
      //   1) window.APPLIED_CONFIG injected by ../applied-config.js (the
      //      last bundle persisted by scripts/apply_config.py). This is the
      //      "current applied state" view that lets the UI render what's
      //      actually live in this consumer.
      //   2) defaults.json (no apply yet, or sidecar missing).
      // The two are merged: defaults provides the structural skeleton, and
      // APPLIED_CONFIG overlays any sparse modifications.
      const baseline = deepClone(defaults);
      // Seed enforce-state containers in case defaults.json doesn't carry them.
      baseline.skills_enforce = baseline.skills_enforce || { disabled: [] };
      baseline.mcps_enforce = baseline.mcps_enforce || { disabled: [] };
      baseline.settings = _normalizeSettings(baseline.settings);
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
        if (appliedConfig.skills_enforce && Array.isArray(appliedConfig.skills_enforce.disabled)) {
          baseline.skills_enforce = { disabled: [...appliedConfig.skills_enforce.disabled] };
        }
        if (appliedConfig.mcps_enforce && Array.isArray(appliedConfig.mcps_enforce.disabled)) {
          baseline.mcps_enforce = { disabled: [...appliedConfig.mcps_enforce.disabled] };
        }
        if (appliedConfig.settings) {
          baseline.settings = _normalizeSettings(appliedConfig.settings);
        }
        banner("success", `Loaded applied state from ${appliedConfig.generated_at || "previous apply"} (generated_by: ${appliedConfig.generated_by || "unknown"}).`);
      } else if (window.APPLIED_CONFIG_MISSING) {
        // Sidecar absent → first-time use. No banner; defaults are fine.
      }
      state = baseline;
      wireEvents();
      renderAll();
      updateCounters();
      if (offlineCount > 0) {
        // Don't clobber the applied-state success banner if one is already up.
        const bannerEl = $("#banner");
        const hasSuccess = bannerEl && !bannerEl.hidden && bannerEl.classList.contains("success");
        if (!hasSuccess) {
          banner(
            "info",
            `Offline mode: ${offlineCount} inventory file(s) could not be loaded ` +
            "(missing .js sidecar and file:// blocked the .json fetch). The UI is running on reduced data. " +
            "Regenerate the sidecars with `python -m scripts.build_ui_sidecars`, or serve over `python -m http.server`."
          );
        }
      }
    } catch (err) {
      banner("error", "Unexpected init failure. Details: " + err.message);
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

    // Skills tab
    const skillsSearch = $("#skills-search");
    if (skillsSearch) skillsSearch.addEventListener("input", (e) => { skillsFilter.search = e.target.value.toLowerCase(); renderSkillsEnforce(); });
    const skillsFD = $("#skills-filter-disabled");
    if (skillsFD) skillsFD.addEventListener("change", (e) => { skillsFilter.onlyDisabled = e.target.checked; renderSkillsEnforce(); });
    const skillsEnAll = $("#skills-enable-all");
    if (skillsEnAll) skillsEnAll.addEventListener("click", () => { state.skills_enforce.disabled = []; renderSkillsEnforce(); updateCounters(); });
    const skillsDisAll = $("#skills-disable-all");
    if (skillsDisAll) skillsDisAll.addEventListener("click", () => {
      state.skills_enforce.disabled = inv.skills.map(s => s.slug);
      renderSkillsEnforce();
      updateCounters();
    });

    // MCPs tab
    const mcpsSearch = $("#mcps-search");
    if (mcpsSearch) mcpsSearch.addEventListener("input", (e) => { mcpsFilter.search = e.target.value.toLowerCase(); renderMcpsEnforce(); });
    const mcpsFD = $("#mcps-filter-disabled");
    if (mcpsFD) mcpsFD.addEventListener("change", (e) => { mcpsFilter.onlyDisabled = e.target.checked; renderMcpsEnforce(); });
    const mcpsEnAll = $("#mcps-enable-all");
    if (mcpsEnAll) mcpsEnAll.addEventListener("click", () => { state.mcps_enforce.disabled = []; renderMcpsEnforce(); updateCounters(); });
    const mcpsDisAll = $("#mcps-disable-all");
    if (mcpsDisAll) mcpsDisAll.addEventListener("click", () => {
      state.mcps_enforce.disabled = inv.mcps.map(m => m.id);
      renderMcpsEnforce();
      updateCounters();
    });

    // Dispatchers tab — copy the curate dry-run command.
    const curateCopy = $("#dispatchers-curate-copy");
    if (curateCopy) curateCopy.addEventListener("click", () => copyPlainText("python -m scripts.curate --dry-run", curateCopy));

    // Settings tab — add hook / permission / directory.
    const addHook = $("#settings-add-hook");
    if (addHook) addHook.addEventListener("click", () => {
      _ensureSettings().hooks.push({ event: "", matcher: "", command: "", timeout: "", targets: [..._SETTINGS_TARGETS] });
      renderSettings();
    });
    const addPerm = $("#settings-add-perm");
    if (addPerm) addPerm.addEventListener("click", () => { _ensureSettings().permissions_allow.push(""); renderSettings(); });
    const addDir = $("#settings-add-dir");
    if (addDir) addDir.addEventListener("click", () => { _ensureSettings().additional_directories.push(""); renderSettings(); });

    // Config files tab — add gitignore pattern / coderabbit filter.
    const addGi = $("#cf-add-gitignore");
    if (addGi) addGi.addEventListener("click", () => { _ensureConfigFiles().gitignore_extras.patterns.push(""); renderConfigFiles(); });
    const addCr = $("#cf-add-coderabbit");
    if (addCr) addCr.addEventListener("click", () => { _ensureConfigFiles().coderabbit_extras.path_filters.push(""); renderConfigFiles(); });
    const addPc = $("#cf-add-precommit");
    if (addPc) addPc.addEventListener("click", () => { _ensureConfigFiles().pre_commit_extras.hooks.push({ id: "" }); renderPreCommit(); updateConfigFilesCounter(); });
    const addMcp = $("#cf-add-mcpserver");
    if (addMcp) addMcp.addEventListener("click", () => {
      _ensureConfigFiles();
      state.mcp_project_servers_edit.push({ id: "", transport: "stdio", env: { required: [], optional: [] }, capabilities_hint: [] });
      renderMcpProject(); updateConfigFilesCounter();
    });

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
    if (name === "files") renderFiles();
    if (name === "dispatchers") renderDispatchers();
    if (name === "settings") renderSettings();
    if (name === "configfiles") renderConfigFiles();
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
    renderSkillsEnforce();
    renderMcpsEnforce();
    updateFilesCounter();
    updateDispatchersCounter();
    updateSettingsCounter();
    updateConfigFilesCounter();
  }

  // ------- Files tab (read-only inspector v1) -------
  let activeFilePath = null;

  function updateFilesCounter() {
    const el = document.getElementById("tab-count-files");
    if (!el) return;
    const fs = window.FILES_STATE;
    if (!fs || !Array.isArray(fs.files)) { el.textContent = "—"; return; }
    el.textContent = String(fs.files.length);
  }

  function renderFiles() {
    const listEl = document.getElementById("files-list");
    const inspectorEl = document.getElementById("files-inspector");
    const summaryEl = document.getElementById("files-summary");
    const hintBtn = document.getElementById("files-refresh-hint");
    if (!listEl || !inspectorEl) return;

    const fs = window.FILES_STATE;
    if (!fs || !Array.isArray(fs.files)) {
      listEl.innerHTML = "";
      inspectorEl.innerHTML = `
        <p class="files-inspector-empty">
          <strong>No files-state sidecar found.</strong><br>
          Generate it by running, from the consumer root:<br>
          <code class="cmd">python -m scripts.build_files_state</code><br><br>
          Or apply a bundle (which builds it automatically as part of apply_config).
        </p>`;
      if (summaryEl) summaryEl.textContent = "0 files tracked";
      if (hintBtn) hintBtn.disabled = false;
      return;
    }

    if (summaryEl) {
      const totals = fs.files.reduce((acc, f) => {
        acc.canonical += (f.counts && f.counts.canonical) || 0;
        acc.drifted += (f.counts && f.counts.drifted) || 0;
        acc.custom += (f.counts && f.counts.custom) || 0;
        return acc;
      }, { canonical: 0, drifted: 0, custom: 0 });
      summaryEl.textContent =
        `${fs.files.length} files · ${totals.canonical} canonical · ${totals.drifted} drifted · ${totals.custom} custom`;
    }

    // File rail
    listEl.innerHTML = "";
    fs.files.forEach(file => {
      const li = document.createElement("li");
      li.className = "files-list-item";
      li.dataset.relPath = file.rel_path;
      if (file.rel_path === activeFilePath) li.classList.add("active");
      const counts = file.counts || { canonical: 0, drifted: 0, custom: 0 };
      const driftBadge = counts.drifted > 0
        ? `<span class="files-badge drifted">${counts.drifted} drift</span>`
        : "";
      li.innerHTML = `
        <div class="files-list-name">${escapeHtml(file.rel_path)}</div>
        <div class="files-list-meta">
          <span class="files-badge canonical">${counts.canonical}C</span>
          <span class="files-badge custom">${counts.custom}X</span>
          ${driftBadge}
        </div>`;
      li.addEventListener("click", () => {
        activeFilePath = file.rel_path;
        renderFiles();
      });
      listEl.appendChild(li);
    });

    // Inspector
    if (!activeFilePath) {
      inspectorEl.innerHTML = `<p class="files-inspector-empty">Select a file on the left to inspect its sections.</p>`;
      return;
    }
    const file = fs.files.find(f => f.rel_path === activeFilePath);
    if (!file) {
      inspectorEl.innerHTML = `<p class="files-inspector-empty">File not found in current state.</p>`;
      return;
    }
    const backupsForFile = (fs.backups || []).filter(b => b.rel_path === file.rel_path);
    const restoreSelect = backupsForFile.length > 0
      ? `<select id="restore-bak-select">
           ${backupsForFile.map(b => `<option value="${escapeHtml(b.backup_rel_path)}">${escapeHtml(b.timestamp)} (${escapeHtml(b.location)})</option>`).join("")}
         </select>
         <button class="btn small" type="button" id="restore-bak-btn" title="Copy the restore CLI command for the selected backup">Copy restore command</button>`
      : `<span class="files-inspector-hint">No backups recorded for this file yet.</span>`;

    // ---- v2: file-level curate buttons + v3: per-section ----
    const curate = getCurateIntent(file.rel_path);
    const curateButtons = `
      <div class="files-curate-bar">
        <span class="files-curate-label">Curate (next apply):</span>
        <button class="btn small ${curate.default === 'take_playbook' ? 'primary' : 'ghost'}" type="button" data-curate-default="take_playbook">Take playbook</button>
        <button class="btn small ${curate.default === 'keep_mine' ? 'primary' : 'ghost'}" type="button" data-curate-default="keep_mine">Keep mine</button>
        <span class="files-inspector-hint">Per-block overrides available below.</span>
      </div>`;

    const sectionsHtml = (file.sections || []).map((s, idx) => {
      if (s.id === null || s.origin === "custom") {
        return `
          <div class="files-section custom">
            <div class="files-section-header">
              <span class="files-badge custom">custom</span>
              <span class="files-section-id">(consumer)</span>
            </div>
            <pre class="files-section-preview">${escapeHtml(s.preview || "")}</pre>
          </div>`;
      }
      const badgeClass = s.origin === "canonical" ? "canonical" : "drifted";
      const badgeLabel = s.origin === "canonical" ? "canonical" : "drifted";
      const shaInfo = s.actual_sha
        ? `<span class="files-section-sha">sha=${escapeHtml(s.actual_sha)}${s.expected_sha && s.expected_sha !== s.actual_sha ? ` (expected ${escapeHtml(s.expected_sha)})` : ""}</span>`
        : "";
      const blockAction = (curate.blocks && curate.blocks[s.id]) || curate.default || "take_playbook";
      const perBlockControl = `
        <div class="files-section-curate">
          <label><input type="radio" name="curate-${escapeHtml(s.id)}-${idx}" value="take_playbook" data-curate-block="${escapeHtml(s.id)}" ${blockAction === 'take_playbook' ? 'checked' : ''}> Take playbook</label>
          <label><input type="radio" name="curate-${escapeHtml(s.id)}-${idx}" value="keep_mine" data-curate-block="${escapeHtml(s.id)}" ${blockAction === 'keep_mine' ? 'checked' : ''}> Keep mine</label>
        </div>`;
      return `
        <div class="files-section ${badgeClass}">
          <div class="files-section-header">
            <span class="files-badge ${badgeClass}">${badgeLabel}</span>
            <span class="files-section-id">${escapeHtml(s.id || "")}</span>
            ${shaInfo}
          </div>
          <pre class="files-section-preview">${escapeHtml(s.preview || "")}</pre>
          ${perBlockControl}
        </div>`;
    }).join("");
    inspectorEl.innerHTML = `
      <div class="files-inspector-header">
        <h3>${escapeHtml(file.rel_path)}</h3>
        <div class="files-inspector-actions">${restoreSelect}</div>
      </div>
      ${curateButtons}
      <div class="files-sections">
        ${sectionsHtml || `<p class="files-inspector-empty">No sections detected.</p>`}
      </div>
    `;
    wireCurateControls(file.rel_path);
    wireRestoreControl(file.rel_path);
  }

  // Shell-quote a path only when it needs it (keeps the common no-space case clean).
  function _shArg(s) {
    return /[\s"']/.test(s) ? `"${String(s).replace(/"/g, '\\"')}"` : String(s);
  }

  function wireRestoreControl(relPath) {
    const btn = document.getElementById("restore-bak-btn");
    const sel = document.getElementById("restore-bak-select");
    if (!btn || !sel) return;
    btn.addEventListener("click", () => {
      const backupRel = sel.value;
      // Copy the safe (preview) form — no --yes. Running it previews the restore;
      // the user adds --yes to overwrite current content (a blast-radius action).
      const cmd = `python -m scripts.restore ${_shArg(relPath)} --from ${_shArg(backupRel)}`;
      copyPlainText(cmd, btn);
    });
  }

  function getCurateIntent(relPath) {
    if (!state) state = {};
    if (!state.file_curate_intents) state.file_curate_intents = {};
    if (!state.file_curate_intents[relPath]) {
      state.file_curate_intents[relPath] = { default_action: "take_playbook", blocks: {} };
    }
    const entry = state.file_curate_intents[relPath];
    return {
      default: entry.default_action || "take_playbook",
      blocks: entry.blocks || {},
    };
  }

  function setCurateDefault(relPath, action) {
    getCurateIntent(relPath); // ensure exists
    state.file_curate_intents[relPath].default_action = action;
    renderFiles();
  }

  function setCurateBlock(relPath, blockId, action) {
    getCurateIntent(relPath);
    const entry = state.file_curate_intents[relPath];
    entry.blocks = entry.blocks || {};
    if (action === entry.default_action) {
      delete entry.blocks[blockId];
    } else {
      entry.blocks[blockId] = action;
    }
  }

  function wireCurateControls(relPath) {
    document.querySelectorAll("[data-curate-default]").forEach(btn => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        setCurateDefault(relPath, btn.dataset.curateDefault);
      });
    });
    document.querySelectorAll("[data-curate-block]").forEach(radio => {
      radio.addEventListener("change", () => {
        if (radio.checked) {
          setCurateBlock(relPath, radio.dataset.curateBlock, radio.value);
        }
      });
    });
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ------- Dispatchers tab (aggregated .md drift view — read + trigger) -------
  const _SUGGEST_LABEL = {
    absorb_into_agents_md: "→ absorb into AGENTS.md",
    dispatch_to_leaf_doc: "→ dispatch to a leaf doc + pointer",
    move_to_other_dispatch: "→ move to another dispatcher",
  };

  function updateDispatchersCounter() {
    const el = document.getElementById("tab-count-dispatchers");
    if (!el) return;
    const fs = window.FILES_STATE;
    if (!fs || !Array.isArray(fs.dispatcher_drift)) { el.textContent = "—"; return; }
    el.textContent = String(fs.dispatcher_drift.length);
  }

  function renderDispatchers() {
    const listEl = document.getElementById("dispatchers-list");
    const summaryEl = document.getElementById("dispatchers-summary");
    if (!listEl) return;
    const fs = window.FILES_STATE;
    const drift = (fs && Array.isArray(fs.dispatcher_drift)) ? fs.dispatcher_drift : null;
    if (drift === null) {
      listEl.innerHTML = `
        <p class="files-inspector-empty">
          <strong>No files-state sidecar found.</strong><br>
          Generate it from the consumer root:<br>
          <code class="cmd">python -m scripts.build_files_state</code><br>
          (or apply a bundle, which builds it automatically).
        </p>`;
      if (summaryEl) summaryEl.textContent = "—";
      return;
    }
    const totalChunks = drift.reduce((n, d) => n + ((d.chunks && d.chunks.length) || 0), 0);
    if (summaryEl) {
      summaryEl.textContent = drift.length === 0
        ? "All dispatchers pointer-shaped — no curate drift"
        : `${totalChunks} loose-prose chunk(s) across ${drift.length} dispatcher(s)`;
    }
    if (drift.length === 0) {
      listEl.innerHTML = `<p class="files-inspector-empty">✓ No loose prose detected in any dispatcher. Nothing to curate.</p>`;
      return;
    }
    listEl.innerHTML = drift.map(d => {
      const chunks = (d.chunks || []).map(c => `
        <div class="dispatcher-chunk">
          <div class="dispatcher-chunk-head">
            <span class="files-badge drifted">${(c.line_count || 0)} lines</span>
            ${c.heading ? `<span class="dispatcher-chunk-heading">${escapeHtml(c.heading)}</span>` : ""}
            <span class="dispatcher-suggestion">${escapeHtml(_SUGGEST_LABEL[c.suggestion] || c.suggestion || "")}</span>
          </div>
          <pre class="files-section-preview">${escapeHtml(c.preview || "")}</pre>
        </div>`).join("");
      return `
        <div class="dispatcher-card">
          <div class="dispatcher-card-head">
            <span class="dispatcher-file">${escapeHtml(d.rel_path)}</span>
            <span class="files-badge drifted">${(d.chunks || []).length} chunk(s)</span>
          </div>
          ${chunks}
        </div>`;
    }).join("");
  }

  async function copyPlainText(text, btn) {
    const restore = () => { if (btn) btn.textContent = btn.dataset.label || "Copy"; };
    const done = () => { if (btn) { btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = "Copied ✓"; setTimeout(restore, 1500); } };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        done();
        return;
      }
      throw new Error("clipboard API unavailable");
    } catch (_) {
      banner("info", "Copy this command manually: " + text);
    }
  }

  // ------- Settings tab (model-agnostic surface) -------
  const _SETTINGS_TARGETS = ["claude", "gemini", "cursor"];
  // Capability gating (D9/D10): which models actually receive a projected hook
  // today. The surface stays agnostic (targets persist for forward-compat), but
  // the UI only offers scoping among capable models and badges the rest as n/a.
  const _SETTINGS_CAPABILITY = {
    claude: true,
    gemini: false, // D10: Gemini hooks unverified — only mcpServers is projected
    cursor: false, // D9: Cursor has no settings/hooks target
  };
  const _CAP_NOTE = {
    gemini: "Gemini hooks are not projected yet — only mcpServers is rendered. Capability-gated.",
    cursor: "Cursor has no settings/hooks target. Capability-gated.",
  };
  const _SETTINGS_CAPABLE = _SETTINGS_TARGETS.filter(t => _SETTINGS_CAPABILITY[t]);

  function _normalizeSettings(s) {
    s = s || {};
    return {
      hooks: Array.isArray(s.hooks) ? s.hooks.map(h => ({
        event: h.event || "",
        matcher: h.matcher || "",
        command: h.command || "",
        timeout: (typeof h.timeout === "number") ? h.timeout : "",
        // Absent targets ⇒ all models (represented as the full set in the UI).
        targets: Array.isArray(h.targets) && h.targets.length ? [...h.targets] : [..._SETTINGS_TARGETS],
      })) : [],
      permissions_allow: Array.isArray(s.permissions_allow) ? [...s.permissions_allow] : [],
      additional_directories: Array.isArray(s.additional_directories) ? [...s.additional_directories] : [],
    };
  }

  function _ensureSettings() {
    if (!state.settings) state.settings = _normalizeSettings(null);
    return state.settings;
  }

  function updateSettingsCounter() {
    const el = document.getElementById("tab-count-settings");
    if (!el) return;
    const s = _ensureSettings();
    const n = s.hooks.length + s.permissions_allow.length + s.additional_directories.length;
    el.textContent = String(n);
  }

  function renderSettings() {
    const s = _ensureSettings();
    const hooksEl = document.getElementById("settings-hooks-list");
    const permsEl = document.getElementById("settings-perms-list");
    const dirsEl = document.getElementById("settings-dirs-list");
    if (!hooksEl || !permsEl || !dirsEl) return;

    // Hooks
    hooksEl.innerHTML = "";
    s.hooks.forEach((h, i) => {
      const row = document.createElement("div");
      row.className = "settings-hook";
      // Capability-gated target strip. With a single capable model (today:
      // claude) scoping is moot, so the supported model shows as a locked ✓
      // badge and the rest as n/a. When a second model gains hook support the
      // capable badges become interactive toggles automatically.
      const multiCapable = _SETTINGS_CAPABLE.length > 1;
      const chips = _SETTINGS_TARGETS.map(t => {
        if (!_SETTINGS_CAPABILITY[t]) {
          return `<span class="target-chip na" title="${escapeHtml(_CAP_NOTE[t] || "Not supported")}">${t} n/a</span>`;
        }
        if (!multiCapable) {
          return `<span class="target-chip on locked" title="Hooks project to ${escapeHtml(t)} today">${escapeHtml(t)} ✓</span>`;
        }
        return `<button type="button" class="target-chip ${h.targets.includes(t) ? "on" : ""}"
                data-hook-target="${i}:${t}">${escapeHtml(t)}</button>`;
      }).join("");
      row.innerHTML = `
        <div class="settings-hook-fields">
          <input class="settings-input" data-hook="${i}:event" placeholder="event (e.g. PreToolUse)" value="${escapeHtml(h.event)}" />
          <input class="settings-input" data-hook="${i}:matcher" placeholder="matcher (optional)" value="${escapeHtml(h.matcher)}" />
          <input class="settings-input wide" data-hook="${i}:command" placeholder="command" value="${escapeHtml(h.command)}" />
          <input class="settings-input narrow" data-hook="${i}:timeout" type="number" min="1" placeholder="timeout" value="${escapeHtml(h.timeout === "" ? "" : String(h.timeout))}" />
          <button type="button" class="btn small ghost" data-hook-remove="${i}">✕</button>
        </div>
        <div class="settings-targets"><span class="settings-targets-label">applies to:</span>${chips}</div>`;
      hooksEl.appendChild(row);
    });
    if (!s.hooks.length) hooksEl.innerHTML = `<p class="files-inspector-hint">No hooks. The enforce-hook invariant is still ensured by apply_config.</p>`;

    // Permissions + directories share the simple string-list row.
    const renderStrList = (container, arr, kind) => {
      container.innerHTML = "";
      arr.forEach((v, i) => {
        const row = document.createElement("div");
        row.className = "settings-strrow";
        row.innerHTML = `
          <input class="settings-input wide" data-str="${kind}:${i}" value="${escapeHtml(v)}" />
          <button type="button" class="btn small ghost" data-str-remove="${kind}:${i}">✕</button>`;
        container.appendChild(row);
      });
      if (!arr.length) container.innerHTML = `<p class="files-inspector-hint">None.</p>`;
    };
    renderStrList(permsEl, s.permissions_allow, "perm");
    renderStrList(dirsEl, s.additional_directories, "dir");

    _wireSettingsControls();
    updateSettingsCounter();
  }

  function _wireSettingsControls() {
    const s = _ensureSettings();
    // Hook field edits (live, no re-render so focus is kept).
    document.querySelectorAll("[data-hook]").forEach(inp => {
      inp.addEventListener("input", () => {
        const [iStr, field] = inp.dataset.hook.split(":");
        const i = Number(iStr);
        if (!s.hooks[i]) return;
        if (field === "timeout") {
          const n = parseInt(inp.value, 10);
          s.hooks[i].timeout = Number.isFinite(n) ? n : "";
        } else {
          s.hooks[i][field] = inp.value;
        }
        updateSettingsCounter();
      });
    });
    document.querySelectorAll("[data-hook-target]").forEach(btn => {
      btn.addEventListener("click", () => {
        const [iStr, t] = btn.dataset.hookTarget.split(":");
        const i = Number(iStr);
        if (!s.hooks[i]) return;
        const set = new Set(s.hooks[i].targets);
        if (set.has(t)) set.delete(t); else set.add(t);
        // Never allow zero targets (zero would mean "no model" — meaningless);
        // empty resets to all.
        s.hooks[i].targets = set.size ? _SETTINGS_TARGETS.filter(x => set.has(x)) : [..._SETTINGS_TARGETS];
        renderSettings();
      });
    });
    document.querySelectorAll("[data-hook-remove]").forEach(btn => {
      btn.addEventListener("click", () => {
        s.hooks.splice(Number(btn.dataset.hookRemove), 1);
        renderSettings();
      });
    });
    // String-list edits.
    document.querySelectorAll("[data-str]").forEach(inp => {
      inp.addEventListener("input", () => {
        const [kind, iStr] = inp.dataset.str.split(":");
        const arr = kind === "perm" ? s.permissions_allow : s.additional_directories;
        arr[Number(iStr)] = inp.value;
      });
    });
    document.querySelectorAll("[data-str-remove]").forEach(btn => {
      btn.addEventListener("click", () => {
        const [kind, iStr] = btn.dataset.strRemove.split(":");
        const arr = kind === "perm" ? s.permissions_allow : s.additional_directories;
        arr.splice(Number(iStr), 1);
        renderSettings();
      });
    });
  }

  // ------- Config files tab (structured agnostic config) -------
  // MCP project servers round-trip as a map (id → record) in the bundle, but a
  // map is awkward to edit (renaming a key loses focus), so the editing form is
  // a LIST of records each carrying an `id` field. Convert at the boundary.
  function _mcpMapToList(map) {
    if (!map || typeof map !== "object" || Array.isArray(map)) return [];
    return Object.entries(map).map(([id, rec]) => {
      const r = (rec && typeof rec === "object" && !Array.isArray(rec)) ? deepClone(rec) : {};
      r.id = id; // the map key is the canonical id
      if (!r.env || typeof r.env !== "object" || Array.isArray(r.env)) r.env = {};
      if (!Array.isArray(r.env.required)) r.env.required = [];
      if (!Array.isArray(r.env.optional)) r.env.optional = [];
      if (!Array.isArray(r.capabilities_hint)) r.capabilities_hint = [];
      return r;
    });
  }

  function _mcpListToMap(list) {
    const out = {};
    (list || []).forEach(rec => {
      const id = (rec.id || "").trim();
      if (!id) return;
      const r = deepClone(rec);
      delete r.id; // id is the map key, not an inner field
      ["description", "command", "endpoint", "auth", "scope", "transport"].forEach(k => {
        if (typeof r[k] === "string") { const v = r[k].trim(); if (v) r[k] = v; else delete r[k]; }
      });
      const env = {};
      if (r.env && typeof r.env === "object") {
        const req = (r.env.required || []).map(s => (s || "").trim()).filter(Boolean);
        const opt = (r.env.optional || []).map(s => (s || "").trim()).filter(Boolean);
        if (req.length) env.required = req;
        if (opt.length) env.optional = opt;
      }
      if (Object.keys(env).length) r.env = env; else delete r.env;
      const caps = (r.capabilities_hint || []).map(s => (s || "").trim()).filter(Boolean);
      if (caps.length) r.capabilities_hint = caps; else delete r.capabilities_hint;
      out[id] = r;
    });
    return out;
  }

  // Clean one pre-commit hook for export: trim scalars, drop empties, normalise
  // the pass_filenames tri-state, prune empty lists — but preserve unknown keys
  // (a hook imported with fields we don't render must round-trip intact).
  function _cleanPreCommitHook(h) {
    const out = deepClone(h);
    const id = (out.id || "").trim();
    if (!id) return null;
    out.id = id;
    ["name", "entry", "language", "files", "exclude"].forEach(k => {
      if (typeof out[k] === "string") { const v = out[k].trim(); if (v) out[k] = v; else delete out[k]; }
    });
    if (out.pass_filenames !== true && out.pass_filenames !== false) delete out.pass_filenames;
    ["args", "stages", "additional_dependencies", "types"].forEach(k => {
      if (Array.isArray(out[k])) {
        const v = out[k].map(s => (s || "").trim()).filter(Boolean);
        if (v.length) out[k] = v; else delete out[k];
      }
    });
    return out;
  }

  function _ensureConfigFiles() {
    if (!state.gitignore_extras || !Array.isArray(state.gitignore_extras.patterns)) {
      state.gitignore_extras = { patterns: Array.isArray((state.gitignore_extras || {}).patterns) ? state.gitignore_extras.patterns : [] };
    }
    if (!state.coderabbit_extras || typeof state.coderabbit_extras !== "object") {
      state.coderabbit_extras = {};
    }
    if (!Array.isArray(state.coderabbit_extras.path_filters)) state.coderabbit_extras.path_filters = [];
    // Pre-commit: list of raw hook objects (unknown keys preserved verbatim).
    if (!state.pre_commit_extras || typeof state.pre_commit_extras !== "object") state.pre_commit_extras = {};
    if (!Array.isArray(state.pre_commit_extras.hooks)) state.pre_commit_extras.hooks = [];
    // MCP project servers: hydrate the editing list from a baseline/applied map
    // exactly once, then treat the list as the single source of truth.
    if (!Array.isArray(state.mcp_project_servers_edit)) {
      state.mcp_project_servers_edit = _mcpMapToList(state.mcp_project_servers);
      delete state.mcp_project_servers;
    }
    return state;
  }

  function updateConfigFilesCounter() {
    const el = document.getElementById("tab-count-configfiles");
    if (!el) return;
    _ensureConfigFiles();
    const n = state.gitignore_extras.patterns.length
      + state.coderabbit_extras.path_filters.length
      + state.pre_commit_extras.hooks.length
      + state.mcp_project_servers_edit.length;
    el.textContent = String(n);
  }

  function _renderStrList(container, arr, kind, onChange) {
    if (!container) return;
    container.innerHTML = "";
    arr.forEach((v, i) => {
      const row = document.createElement("div");
      row.className = "settings-strrow";
      row.innerHTML = `
        <input class="settings-input wide" data-cf="${kind}:${i}" value="${escapeHtml(v)}" />
        <button type="button" class="btn small ghost" data-cf-remove="${kind}:${i}">✕</button>`;
      container.appendChild(row);
    });
    if (!arr.length) container.innerHTML = `<p class="files-inspector-hint">None.</p>`;
    container.querySelectorAll("[data-cf]").forEach(inp => {
      inp.addEventListener("input", () => {
        const i = Number(inp.dataset.cf.split(":")[1]);
        arr[i] = inp.value;
        updateConfigFilesCounter();
      });
    });
    container.querySelectorAll("[data-cf-remove]").forEach(btn => {
      btn.addEventListener("click", () => {
        arr.splice(Number(btn.dataset.cfRemove.split(":")[1]), 1);
        onChange();
      });
    });
  }

  function renderConfigFiles() {
    _ensureConfigFiles();
    _renderStrList(
      document.getElementById("cf-gitignore-list"),
      state.gitignore_extras.patterns, "gi", renderConfigFiles,
    );
    _renderStrList(
      document.getElementById("cf-coderabbit-list"),
      state.coderabbit_extras.path_filters, "cr", renderConfigFiles,
    );
    renderPreCommit();
    renderMcpProject();
    updateConfigFilesCounter();
  }

  // ---- Nested string-list sub-editor (shared by pre-commit + mcp) ----
  // Path encodes the owning array: "pc:<i>:<field>" or "mcp:<i>:<field>" where
  // field may be dotted ("env.required"). Item rows append ":<j>".
  function _resolveNestedArr(path) {
    const [kind, idxStr, field] = path.split(":");
    const idx = Number(idxStr);
    if (kind === "pc") {
      const h = state.pre_commit_extras.hooks[idx];
      if (!h) return null;
      if (!Array.isArray(h[field])) h[field] = [];
      return h[field];
    }
    if (kind === "mcp") {
      const rec = state.mcp_project_servers_edit[idx];
      if (!rec) return null;
      if (field === "env.required" || field === "env.optional") {
        if (!rec.env || typeof rec.env !== "object") rec.env = {};
        const sub = field.split(".")[1];
        if (!Array.isArray(rec.env[sub])) rec.env[sub] = [];
        return rec.env[sub];
      }
      if (!Array.isArray(rec[field])) rec[field] = [];
      return rec[field];
    }
    return null;
  }

  function _renderNestedStrList(path, label, arr) {
    const items = (arr || []).map((v, j) => `
      <div class="nested-strrow">
        <input class="settings-input" data-nl="${path}:${j}" value="${escapeHtml(v || "")}" />
        <button type="button" class="btn small ghost" data-nl-remove="${path}:${j}">✕</button>
      </div>`).join("");
    return `
      <div class="nested-sublist">
        <div class="nested-sublist-head">
          <span>${escapeHtml(label)}</span>
          <button type="button" class="btn small" data-nl-add="${path}">+ add</button>
        </div>
        ${items || `<span class="files-inspector-hint">none</span>`}
      </div>`;
  }

  function _wireNestedLists(host, onStructural) {
    host.querySelectorAll("[data-nl]").forEach(inp => {
      inp.addEventListener("input", () => {
        const parts = inp.dataset.nl.split(":");
        const j = Number(parts.pop());
        const arr = _resolveNestedArr(parts.join(":"));
        if (arr) { arr[j] = inp.value; }
      });
    });
    host.querySelectorAll("[data-nl-add]").forEach(btn => {
      btn.addEventListener("click", () => {
        const arr = _resolveNestedArr(btn.dataset.nlAdd);
        if (arr) { arr.push(""); onStructural(); }
      });
    });
    host.querySelectorAll("[data-nl-remove]").forEach(btn => {
      btn.addEventListener("click", () => {
        const parts = btn.dataset.nlRemove.split(":");
        const j = Number(parts.pop());
        const arr = _resolveNestedArr(parts.join(":"));
        if (arr) { arr.splice(j, 1); onStructural(); }
      });
    });
  }

  // ---- .pre-commit-config.yaml — extra hooks ----
  const _PC_SCALARS = [
    { key: "name", ph: "name" },
    { key: "entry", ph: "entry (command/script)" },
    { key: "language", ph: "language (system/python/script…)" },
    { key: "files", ph: "files (regex)" },
    { key: "exclude", ph: "exclude (regex)" },
  ];
  const _PC_LISTS = ["args", "stages", "additional_dependencies", "types"];

  function renderPreCommit() {
    const host = document.getElementById("cf-precommit-list");
    if (!host) return;
    const hooks = state.pre_commit_extras.hooks;
    host.innerHTML = "";
    if (!hooks.length) { host.innerHTML = `<p class="files-inspector-hint">No extra hooks.</p>`; return; }
    hooks.forEach((h, i) => {
      const card = document.createElement("div");
      card.className = "nested-card";
      const scalars = _PC_SCALARS.map(f => `
        <label class="nested-field"><span>${f.key}</span>
          <input class="settings-input" data-pc="${i}:${f.key}" placeholder="${escapeHtml(f.ph)}" value="${escapeHtml(h[f.key] || "")}" />
        </label>`).join("");
      const pf = (h.pass_filenames === true) ? "true" : (h.pass_filenames === false) ? "false" : "";
      const lists = _PC_LISTS.map(k => _renderNestedStrList(`pc:${i}:${k}`, k, h[k] || [])).join("");
      card.innerHTML = `
        <div class="nested-card-head">
          <input class="settings-input nested-id" data-pc="${i}:id" placeholder="id (required)" value="${escapeHtml(h.id || "")}" />
          <button type="button" class="btn small ghost" data-pc-remove="${i}">Remove hook</button>
        </div>
        <div class="nested-grid">${scalars}
          <label class="nested-field"><span>pass_filenames</span>
            <select class="settings-input" data-pc-pf="${i}">
              <option value=""${pf === "" ? " selected" : ""}>(default)</option>
              <option value="true"${pf === "true" ? " selected" : ""}>true</option>
              <option value="false"${pf === "false" ? " selected" : ""}>false</option>
            </select>
          </label>
        </div>
        <div class="nested-lists">${lists}</div>`;
      host.appendChild(card);
    });
    _wirePreCommit();
  }

  function _wirePreCommit() {
    const host = document.getElementById("cf-precommit-list");
    if (!host) return;
    const hooks = state.pre_commit_extras.hooks;
    host.querySelectorAll("[data-pc]").forEach(inp => {
      inp.addEventListener("input", () => {
        const [iStr, field] = inp.dataset.pc.split(":");
        const h = hooks[Number(iStr)];
        if (h) { h[field] = inp.value; if (field === "id") updateConfigFilesCounter(); }
      });
    });
    host.querySelectorAll("[data-pc-pf]").forEach(sel => {
      sel.addEventListener("change", () => {
        const h = hooks[Number(sel.dataset.pcPf)];
        if (!h) return;
        if (sel.value === "") delete h.pass_filenames;
        else h.pass_filenames = (sel.value === "true");
      });
    });
    host.querySelectorAll("[data-pc-remove]").forEach(btn => {
      btn.addEventListener("click", () => { hooks.splice(Number(btn.dataset.pcRemove), 1); renderPreCommit(); updateConfigFilesCounter(); });
    });
    _wireNestedLists(host, renderPreCommit);
  }

  // ---- mcp-servers.project.yaml — project servers ----
  const _MCP_TRANSPORTS = ["stdio", "http", "sse", "streamable-http"];
  const _MCP_SCOPES = ["", "project", "universal"]; // personal is personal-layer-only

  function renderMcpProject() {
    const host = document.getElementById("cf-mcpserver-list");
    if (!host) return;
    const list = state.mcp_project_servers_edit;
    host.innerHTML = "";
    if (!list.length) { host.innerHTML = `<p class="files-inspector-hint">No project servers.</p>`; return; }
    list.forEach((rec, i) => {
      if (!rec.env || typeof rec.env !== "object") rec.env = {};
      if (!Array.isArray(rec.env.required)) rec.env.required = [];
      if (!Array.isArray(rec.env.optional)) rec.env.optional = [];
      if (!Array.isArray(rec.capabilities_hint)) rec.capabilities_hint = [];
      const transport = rec.transport || "stdio";
      const transOpts = _MCP_TRANSPORTS.map(t => `<option value="${t}"${t === transport ? " selected" : ""}>${t}</option>`).join("");
      const scope = rec.scope || "";
      const scopeOpts = _MCP_SCOPES.map(s => `<option value="${s}"${s === scope ? " selected" : ""}>${s || "(unset)"}</option>`).join("");
      const connField = (transport === "stdio")
        ? `<label class="nested-field"><span>command</span><input class="settings-input" data-mcp="${i}:command" placeholder="command (argv joined)" value="${escapeHtml(rec.command || "")}" /></label>`
        : `<label class="nested-field"><span>endpoint</span><input class="settings-input" data-mcp="${i}:endpoint" placeholder="https://… endpoint URL" value="${escapeHtml(rec.endpoint || "")}" /></label>`;
      const card = document.createElement("div");
      card.className = "nested-card";
      card.innerHTML = `
        <div class="nested-card-head">
          <input class="settings-input nested-id" data-mcp="${i}:id" placeholder="server id (required)" value="${escapeHtml(rec.id || "")}" />
          <button type="button" class="btn small ghost" data-mcp-remove="${i}">Remove server</button>
        </div>
        <div class="nested-grid">
          <label class="nested-field"><span>description</span><input class="settings-input" data-mcp="${i}:description" value="${escapeHtml(rec.description || "")}" /></label>
          <label class="nested-field"><span>transport</span><select class="settings-input" data-mcp-trans="${i}">${transOpts}</select></label>
          ${connField}
          <label class="nested-field"><span>scope</span><select class="settings-input" data-mcp="${i}:scope">${scopeOpts}</select></label>
          <label class="nested-field"><span>auth</span><input class="settings-input" data-mcp="${i}:auth" placeholder="optional" value="${escapeHtml(rec.auth || "")}" /></label>
        </div>
        <div class="nested-lists">
          ${_renderNestedStrList(`mcp:${i}:env.required`, "env.required", rec.env.required)}
          ${_renderNestedStrList(`mcp:${i}:env.optional`, "env.optional", rec.env.optional)}
          ${_renderNestedStrList(`mcp:${i}:capabilities_hint`, "capabilities_hint", rec.capabilities_hint)}
        </div>`;
      host.appendChild(card);
    });
    _wireMcpProject();
  }

  function _wireMcpProject() {
    const host = document.getElementById("cf-mcpserver-list");
    if (!host) return;
    const list = state.mcp_project_servers_edit;
    host.querySelectorAll("[data-mcp]").forEach(el => {
      const handler = () => {
        const [iStr, field] = el.dataset.mcp.split(":");
        const rec = list[Number(iStr)];
        if (rec) { rec[field] = el.value; if (field === "id") updateConfigFilesCounter(); }
      };
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
    host.querySelectorAll("[data-mcp-trans]").forEach(sel => {
      sel.addEventListener("change", () => {
        const rec = list[Number(sel.dataset.mcpTrans)];
        if (rec) { rec.transport = sel.value; renderMcpProject(); }
      });
    });
    host.querySelectorAll("[data-mcp-remove]").forEach(btn => {
      btn.addEventListener("click", () => { list.splice(Number(btn.dataset.mcpRemove), 1); renderMcpProject(); updateConfigFilesCounter(); });
    });
    _wireNestedLists(host, renderMcpProject);
  }

  function updateSkillsSummary() {
    const summary = $("#skills-summary");
    if (!summary) return;
    const disabledSize = (state.skills_enforce.disabled || []).length;
    const total = inv.skills.length;
    summary.textContent = `${total - disabledSize}/${total} enforced (${disabledSize} disabled)`;
  }

  function toggleSkillEnforced(slug, enforced) {
    const set = new Set(state.skills_enforce.disabled || []);
    if (enforced) set.delete(slug); else set.add(slug);
    state.skills_enforce.disabled = [...set].sort();
    updateCounters();
    updateSkillsSummary();
  }

  function renderSkillsEnforce() {
    const list = $("#skills-list");
    if (!list) return;
    list.innerHTML = "";
    const disabledSet = new Set(state.skills_enforce.disabled || []);

    const filtered = inv.skills.filter(s => {
      const isDisabled = disabledSet.has(s.slug);
      if (skillsFilter.onlyDisabled && !isDisabled) return false;
      if (skillsFilter.search) {
        const hay = (s.slug + " " + (s.description || "")).toLowerCase();
        if (!hay.includes(skillsFilter.search)) return false;
      }
      return true;
    });

    filtered.forEach(s => {
      const isDisabled = disabledSet.has(s.slug);
      const li = document.createElement("li");
      li.className = "enforce-row" + (isDisabled ? " disabled" : "");
      li.innerHTML = `
        <label class="enforce-cell">
          <input type="checkbox" data-enforce-skill="${escapeHtml(s.slug)}" ${isDisabled ? "" : "checked"} />
          <span class="enforce-name">${escapeHtml(s.slug)}</span>
        </label>
        <div class="enforce-desc">${escapeHtml(s.description || "")}</div>
      `;
      const cb = li.querySelector(`[data-enforce-skill="${cssEscape(s.slug)}"]`);
      if (cb) cb.addEventListener("change", (e) => {
        toggleSkillEnforced(s.slug, e.target.checked);
        li.classList.toggle("disabled", !e.target.checked);
        if (skillsFilter.onlyDisabled && e.target.checked) li.remove();
      });
      list.appendChild(li);
    });

    updateSkillsSummary();
  }

  function updateMcpsSummary() {
    const summary = $("#mcps-summary");
    if (!summary) return;
    const disabledSize = (state.mcps_enforce.disabled || []).length;
    const total = inv.mcps.length;
    summary.textContent = `${total - disabledSize}/${total} enforced (${disabledSize} disabled)`;
  }

  function toggleMcpEnforced(id, enforced) {
    const set = new Set(state.mcps_enforce.disabled || []);
    if (enforced) set.delete(id); else set.add(id);
    state.mcps_enforce.disabled = [...set].sort();
    updateCounters();
    updateMcpsSummary();
  }

  function renderMcpsEnforce() {
    const list = $("#mcps-list");
    if (!list) return;
    list.innerHTML = "";
    const disabledSet = new Set(state.mcps_enforce.disabled || []);

    const filtered = inv.mcps.filter(m => {
      const isDisabled = disabledSet.has(m.id);
      if (mcpsFilter.onlyDisabled && !isDisabled) return false;
      if (mcpsFilter.search) {
        const hay = [m.id, m.description, m.layer, m.transport, m.scope].filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(mcpsFilter.search)) return false;
      }
      return true;
    });

    filtered.forEach(m => {
      const isDisabled = disabledSet.has(m.id);
      const li = document.createElement("li");
      li.className = "enforce-row" + (isDisabled ? " disabled" : "");
      const badges = [
        m.layer ? `<span class="badge layer">${escapeHtml(m.layer)}</span>` : "",
        m.transport ? `<span class="badge">${escapeHtml(m.transport)}</span>` : "",
        m.scope ? `<span class="badge">${escapeHtml(m.scope)}</span>` : "",
      ].filter(Boolean).join(" ");
      li.innerHTML = `
        <label class="enforce-cell">
          <input type="checkbox" data-enforce-mcp="${escapeHtml(m.id)}" ${isDisabled ? "" : "checked"} />
          <span class="enforce-name">${escapeHtml(m.id)}</span>
          <span class="enforce-badges">${badges}</span>
        </label>
        <div class="enforce-desc">${escapeHtml(m.description || "")}</div>
      `;
      const cb = li.querySelector(`[data-enforce-mcp="${cssEscape(m.id)}"]`);
      if (cb) cb.addEventListener("change", (e) => {
        toggleMcpEnforced(m.id, e.target.checked);
        li.classList.toggle("disabled", !e.target.checked);
        if (mcpsFilter.onlyDisabled && e.target.checked) li.remove();
      });
      list.appendChild(li);
    });

    updateMcpsSummary();
  }

  function cssEscape(s) {
    if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, c => "\\" + c);
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

    // L1 capability (D20): `has_l1` means a rule.py exists; `l1_effective` means
    // an L1 hook actually fires (Claude-targeted + declares triggers). The badge
    // reflects the truth. Back-compat: absent l1_effective falls back to has_l1.
    const l1Effective = rule.l1_effective !== undefined ? rule.l1_effective : rule.has_l1;
    const layerBadge = (L) => {
      if (L === "L1") {
        if (!rule.has_l1) return `<span class="badge layer">—</span>`;
        if (!l1Effective) {
          const why = (rule.triggers && rule.triggers.length)
            ? "L1 fires only on Claude; this rule is not Claude-targeted"
            : "rule.py is a validator with no PreToolUse trigger — no L1 hook fires";
          return `<span class="badge layer na" title="${escapeHtml(why)}">L1 n/a</span>`;
        }
      }
      if (L === "L3" && !rule.has_l3) return `<span class="badge layer">—</span>`;
      const present = layers[L] !== undefined ? layers[L] : enabled;
      return `<span class="badge layer ${present ? "on" : "off"}">${L}${present ? "✓" : "✗"}</span>`;
    };
    const appliesTo = Array.isArray(rule.applies_to) && rule.applies_to.length
      ? rule.applies_to : ["claude", "gemini", "cursor"];
    const appliesChips = ["claude", "gemini", "cursor"].map(ai =>
      `<span class="target-chip ${appliesTo.includes(ai) ? "on" : "na"}">${ai}</span>`).join("");

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
        <h4>Applies to</h4>
        <div class="applies-row">${appliesChips}</div>
        <h4>Layers</h4>
        <div class="layer-row">
          <label><input type="checkbox" data-layer="${rule.slug}:L1" ${l1Effective ? "" : "disabled"} ${layerValue(layers, "L1", enabled, l1Effective) ? "checked" : ""} /> L1 (hook + rule.py)</label>
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
    const entries = Object.entries(inv.features);
    if (entries.length === 0) {
      wrap.innerHTML = `<div class="empty-state">No features inventory loaded. If you opened this UI via <code>file://</code>, check the banner above — most likely the inventory JSONs are blocked by browser CORS. Re-open under <code>python -m http.server</code> for full data.</div>`;
      return;
    }
    entries.forEach(([key, def]) => {
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
    if (inv.globalFlags.length === 0) {
      wrap.innerHTML = `<div class="empty-state">No global-flags inventory loaded. If you opened this UI via <code>file://</code>, check the banner above — most likely the inventory JSONs are blocked by browser CORS. Re-open under <code>python -m http.server</code> for full data.</div>`;
      return;
    }
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

    const skillsDisabled = (state.skills_enforce && state.skills_enforce.disabled) ? state.skills_enforce.disabled.length : 0;
    const tabSkills = $("#tab-count-skills");
    if (tabSkills) tabSkills.textContent = `${inv.skills.length - skillsDisabled}/${inv.skills.length}`;

    const mcpsDisabled = (state.mcps_enforce && state.mcps_enforce.disabled) ? state.mcps_enforce.disabled.length : 0;
    const tabMcps = $("#tab-count-mcps");
    if (tabMcps) tabMcps.textContent = `${inv.mcps.length - mcpsDisabled}/${inv.mcps.length}`;
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
    // Sparse: only emit `skills_enforce` / `mcps_enforce` if at least one
    // entry is disabled. apply_config writes the state file in either case,
    // but omitting them when empty keeps the exported bundle minimal.
    if (state.skills_enforce && Array.isArray(state.skills_enforce.disabled) && state.skills_enforce.disabled.length > 0) {
      bundle.skills_enforce = { disabled: [...state.skills_enforce.disabled].sort() };
    }
    if (state.mcps_enforce && Array.isArray(state.mcps_enforce.disabled) && state.mcps_enforce.disabled.length > 0) {
      bundle.mcps_enforce = { disabled: [...state.mcps_enforce.disabled].sort() };
    }
    // Sparse: only emit file_curate_intents for files where the user actually
    // changed something away from defaults (default_action != "take_playbook"
    // OR per-block overrides exist).
    if (state.file_curate_intents && typeof state.file_curate_intents === "object") {
      const intentsOut = {};
      Object.entries(state.file_curate_intents).forEach(([relPath, entry]) => {
        if (!entry) return;
        const defaultAction = entry.default_action || "take_playbook";
        const blocks = entry.blocks || {};
        const hasNonDefault = (
          (defaultAction !== "take_playbook") ||
          Object.keys(blocks).length > 0
        );
        if (!hasNonDefault) return;
        const out = {};
        if (defaultAction !== "take_playbook") out.default_action = defaultAction;
        if (Object.keys(blocks).length > 0) out.blocks = { ...blocks };
        intentsOut[relPath] = out;
      });
      if (Object.keys(intentsOut).length > 0) bundle.file_curate_intents = intentsOut;
    }
    // Config-files surfaces — sparse string lists.
    if (state.gitignore_extras && Array.isArray(state.gitignore_extras.patterns)) {
      const pats = state.gitignore_extras.patterns.map(v => (v || "").trim()).filter(Boolean);
      if (pats.length) bundle.gitignore_extras = { patterns: [...new Set(pats)] };
    }
    if (state.coderabbit_extras && Array.isArray(state.coderabbit_extras.path_filters)) {
      const filters = state.coderabbit_extras.path_filters.map(v => (v || "").trim()).filter(Boolean);
      // Preserve any path_instructions imported via JSON (not edited in this tab).
      const out = {};
      if (filters.length) out.path_filters = [...new Set(filters)];
      const instrs = state.coderabbit_extras.path_instructions;
      if (Array.isArray(instrs) && instrs.length) out.path_instructions = instrs;
      if (Object.keys(out).length) bundle.coderabbit_extras = out;
    }
    // Pre-commit extra hooks — sparse list of cleaned hook objects (id required).
    if (state.pre_commit_extras && Array.isArray(state.pre_commit_extras.hooks)) {
      const hooks = state.pre_commit_extras.hooks.map(_cleanPreCommitHook).filter(Boolean);
      if (hooks.length) bundle.pre_commit_extras = { hooks };
    }
    // MCP project servers — fold the editing list back into the id→record map.
    if (Array.isArray(state.mcp_project_servers_edit)) {
      const map = _mcpListToMap(state.mcp_project_servers_edit);
      if (Object.keys(map).length) bundle.mcp_project_servers = map;
    }
    // Model-agnostic settings surface — sparse. Only emit non-empty entries; a
    // hook targeting every model omits `targets` (the schema default). Hooks
    // missing event or command are dropped (incomplete rows).
    if (state.settings) {
      const s = state.settings;
      const hooks = (s.hooks || [])
        .filter(h => (h.event || "").trim() && (h.command || "").trim())
        .map(h => {
          const out = { event: h.event.trim(), command: h.command.trim() };
          if ((h.matcher || "").trim()) out.matcher = h.matcher.trim();
          if (typeof h.timeout === "number" && Number.isFinite(h.timeout)) out.timeout = h.timeout;
          const targets = Array.isArray(h.targets) ? h.targets : [];
          const all = _SETTINGS_TARGETS.every(t => targets.includes(t));
          if (targets.length && !all) out.targets = _SETTINGS_TARGETS.filter(t => targets.includes(t));
          return out;
        });
      const perms = (s.permissions_allow || []).map(v => (v || "").trim()).filter(Boolean);
      const dirs = (s.additional_directories || []).map(v => (v || "").trim()).filter(Boolean);
      const settingsOut = {};
      if (hooks.length) settingsOut.hooks = hooks;
      if (perms.length) settingsOut.permissions_allow = [...new Set(perms)];
      if (dirs.length) settingsOut.additional_directories = [...new Set(dirs)];
      if (Object.keys(settingsOut).length) bundle.settings = settingsOut;
    }
    // Optimistic concurrency (compare-and-swap): stamp the whole-file SHA the UI
    // loaded for each managed file (from files-state.js) so apply_config refuses
    // to overwrite a file that changed on disk since the UI opened. Sparse —
    // emitted only when files-state.js is present with file_sha tokens.
    const filesState = window.FILES_STATE;
    if (filesState && Array.isArray(filesState.files)) {
      const baseShas = {};
      filesState.files.forEach(f => {
        if (f && f.rel_path && typeof f.file_sha === "string") {
          baseShas[f.rel_path] = f.file_sha;
        }
      });
      if (Object.keys(baseShas).length > 0) bundle.base_shas = baseShas;
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
        state.skills_enforce = state.skills_enforce || { disabled: [] };
        state.mcps_enforce = state.mcps_enforce || { disabled: [] };
        if (data.rules) state.rules = deepClone(data.rules);
        if (data.features) {
          state.features = state.features || {};
          Object.entries(data.features).forEach(([k, f]) => { state.features[k] = deepClone(f); });
        }
        if (data.global_flags) state.global_flags = deepClone(data.global_flags);
        if (data.skills_enforce && Array.isArray(data.skills_enforce.disabled)) {
          state.skills_enforce = { disabled: [...data.skills_enforce.disabled] };
        }
        if (data.mcps_enforce && Array.isArray(data.mcps_enforce.disabled)) {
          state.mcps_enforce = { disabled: [...data.mcps_enforce.disabled] };
        }
        state.settings = _normalizeSettings(data.settings);
        if (data.gitignore_extras && Array.isArray(data.gitignore_extras.patterns)) {
          state.gitignore_extras = { patterns: [...data.gitignore_extras.patterns] };
        }
        if (data.coderabbit_extras && typeof data.coderabbit_extras === "object") {
          state.coderabbit_extras = deepClone(data.coderabbit_extras);
        }
        if (data.pre_commit_extras && Array.isArray(data.pre_commit_extras.hooks)) {
          state.pre_commit_extras = { hooks: data.pre_commit_extras.hooks.map(h => deepClone(h)) };
        }
        if (data.mcp_project_servers && typeof data.mcp_project_servers === "object") {
          state.mcp_project_servers_edit = _mcpMapToList(data.mcp_project_servers);
          delete state.mcp_project_servers;
        }
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
    state.skills_enforce = { disabled: [] };
    state.mcps_enforce = { disabled: [] };
    state.settings = _normalizeSettings(defaults && defaults.settings);
    delete state.gitignore_extras;
    delete state.coderabbit_extras;
    delete state.pre_commit_extras;
    delete state.mcp_project_servers;
    delete state.mcp_project_servers_edit;
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
