/* ai-playbook telemetry dashboard renderer — vanilla JS, no build.
 *
 * Reads window.DASHBOARD_DATA (set by ../../dashboard-data.js, the sidecar
 * produced by scripts/telemetry/build_dashboard_data.py) and renders the
 * Dashboard tab inside the existing config UI.
 *
 * Contract: dashboard-data/v1. Schema at schemas/schema-dashboard-data-v1.json.
 * Design: docs/concepts/telemetry-dashboard.md.
 *
 * Privacy: this script never logs raw target paths, raw Bash commands, or
 * unhashed session IDs. The sidecar enforces those invariants Python-side;
 * we only render what reached us.
 */
(function () {
  "use strict";

  const SCHEMA_VERSION = "dashboard-data/v1";
  const REFRESH_COMMAND = "python -m scripts.telemetry.build_dashboard_data";
  const TELEMETRY_DESIGN_DOC = "../../docs/concepts/telemetry-design.md";

  const EMOJI = { green: "🟢", yellow: "🟡", red: "🔴" };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props) {
      Object.entries(props).forEach(([k, v]) => {
        if (k === "class") node.className = v;
        else if (k === "html") node.innerHTML = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v);
      });
    }
    children.flat().forEach(c => {
      if (c == null) return;
      if (typeof c === "string") node.appendChild(document.createTextNode(c));
      else node.appendChild(c);
    });
    return node;
  }

  function clear(root) { while (root.firstChild) root.removeChild(root.firstChild); }

  function fmtPct(value) {
    if (typeof value !== "number" || !isFinite(value)) return "—";
    return (value * 100).toFixed(1) + "%";
  }

  function fmtMoney(value) {
    if (typeof value !== "number" || !isFinite(value)) return "—";
    return "$" + value.toFixed(2);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for file:// where the async clipboard API may be denied.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* swallow */ }
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  // -------------------------------------------------------------------------
  // Rendering primitives.
  // -------------------------------------------------------------------------

  function banner(kind, text) {
    return el("div", { class: "dash-banner " + kind, text });
  }

  function renderMissingSidecar(root) {
    clear(root);
    root.appendChild(el(
      "div",
      { class: "dash-empty" },
      el("h2", { text: "No telemetry data yet" }),
      el("p", {
        text:
          "The aggregator has not produced a dashboard-data.js sidecar for this consumer. " +
          "Run the command below from the consumer root, then reload this page.",
      }),
      el("p", null, el("code", { text: REFRESH_COMMAND })),
      el("p", null,
        "See ",
        el("a", { href: TELEMETRY_DESIGN_DOC, text: "telemetry-design.md" }),
        " for what gets recorded.",
      ),
    ));
  }

  function renderSchemaMismatch(root, found) {
    clear(root);
    root.appendChild(banner(
      "error",
      `Dashboard schema mismatch: expected ${SCHEMA_VERSION}, got ${found || "<unset>"}. ` +
      `Bump the playbook submodule on this consumer and re-run the aggregator.`
    ));
  }

  function renderChartLibFailed(root, payload) {
    clear(root);
    root.appendChild(banner(
      "warn",
      "Chart library failed to load (CDN unreachable, integrity mismatch, or proxy block). " +
      "Numbers still render below; charts are unavailable. Native-SVG fallback ships in a later release."
    ));
    renderHero(root, payload.panels);
    renderToolbar(root, payload);
    // Render text-only panel summaries.
    root.appendChild(el(
      "div",
      { class: "dash-panel" },
      el("h2", { text: "Obey-rate trend" }),
      el("div", { class: "sub", text: "chart unavailable; latest daily values follow" }),
      ...payload.panels.trend.points.slice(-7).map(p => el(
        "div", { text: `${p.iso_day} — ${fmtPct(p.obey_rate)} (${p.events} events)` }
      )),
    ));
    renderMatrixPanel(root, payload.panels.matrix);
    renderHonestyPanel(root, payload.panels.honesty);
    renderFrictionPanel(root, payload.panels.friction);
    renderCavemanPanel(root, payload);
    renderFooter(root, payload);
  }

  function renderEmpty(root, payload) {
    clear(root);
    root.appendChild(el(
      "div",
      { class: "dash-empty" },
      el("h2", { text: "Dashboard is warming up" }),
      el("p", {
        text:
          `Only ${payload.window.events_seen} telemetry events recorded so far ` +
          `(threshold: ${payload.empty_state_threshold}). Use the playbook as you normally would; ` +
          `the data lands on its own. Panels appear once we have enough signal.`,
      }),
      el("p", null,
        "See ",
        el("a", { href: TELEMETRY_DESIGN_DOC, text: "telemetry-design.md" }),
        " for what each event records and what stays on disk.",
      ),
    ));
    renderFooter(root, payload);
  }

  function renderHero(root, panels) {
    const hero = panels.hero || {};
    const sec = panels.secondary || {};
    const cost = (sec.cost_saved_usd || {});
    root.appendChild(el(
      "div",
      { class: "dash-hero" },
      el(
        "div",
        { class: "stat" },
        el("div", null,
          el("span", { text: String(hero.incidents_prevented_7d ?? 0), class: "num" }),
        ),
        el("div", { class: "label", text: "Incidents prevented (7d)" }),
        el("div", { class: "sub", html:
          `Prompt-injection blocks (OWASP LLM01): <strong>${hero.prompt_injection_blocks ?? 0}</strong>`,
        }),
      ),
      el(
        "div",
        { class: "stat" },
        el("div", null,
          el("span", { text: fmtPct(sec.obey_rate_7d), class: "num" }),
          el("span", { class: "emoji", text: EMOJI[sec.health_emoji] || "" }),
        ),
        el("div", { class: "label", text: "Obey-rate (7d)" }),
        el("div", { class: "sub", text:
          "🟢 ≥95%   🟡 ≥85%   🔴 <85%",
        }),
      ),
      el(
        "div",
        { class: "stat" },
        el("div", null,
          el("span", { text: fmtMoney(cost.value), class: "num" }),
        ),
        el("div", { class: "label", text: "Caveman cost saved (7d)" }),
        el("div", { class: "sub" },
          "methodology: ",
          el("a", { href: cost.methodology || "#", text: "see Caveman docs" }),
        ),
      ),
    ));
  }

  function renderToolbar(root, payload) {
    const refreshBtn = el("button", { class: "btn small", text: "Copy refresh command" });
    refreshBtn.addEventListener("click", () => {
      copyToClipboard(REFRESH_COMMAND).then(() => {
        refreshBtn.textContent = "Copied! Paste into a terminal then reload";
        setTimeout(() => { refreshBtn.textContent = "Copy refresh command"; }, 4000);
      });
    });
    root.appendChild(el(
      "div",
      { class: "dash-toolbar" },
      el("div", { class: "pricing" },
        `generated ${payload.generated_at} · pricing.yaml sha256: ${(payload.pricing_version || "").slice(0, 12)}…`,
      ),
      refreshBtn,
    ));
  }

  function renderTrendChart(root, trend) {
    const wrap = el("div", { class: "dash-panel" },
      el("h2", { text: "Obey-rate trend" }),
      el("div", { class: "sub", text: `${trend.points.length} daily buckets` }),
    );
    const canvasWrap = el("div", { class: "dash-canvas-wrap" });
    const canvas = el("canvas");
    canvasWrap.appendChild(canvas);
    wrap.appendChild(canvasWrap);
    root.appendChild(wrap);

    new window.Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: trend.points.map(p => p.iso_day),
        datasets: [{
          label: "obey-rate",
          data: trend.points.map(p => p.obey_rate * 100),
          borderColor: "#0f62fe",
          backgroundColor: "rgba(15, 98, 254, 0.08)",
          fill: true,
          tension: 0.3,
          pointRadius: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { min: 60, max: 100, ticks: { callback: v => v + "%" } },
        },
      },
    });
  }

  function renderMatrixPanel(root, matrix) {
    const rows = matrix && matrix.rows ? matrix.rows : [];
    const llms = Array.from(new Set(rows.flatMap(r => Object.keys(r.by_llm || {})))).sort();

    const table = el("table", { class: "dash-matrix" });
    const thead = el("tr", null,
      el("th", { text: "rule" }),
      ...llms.map(l => el("th", { text: l })),
      el("th", { text: "drift" }),
    );
    table.appendChild(thead);
    rows.forEach(row => {
      const tr = el("tr", null);
      tr.appendChild(el("td", { text: row.rule_slug, class: "slug" }));
      llms.forEach(l => {
        const v = (row.by_llm || {})[l];
        const td = el("td", { text: v == null ? "—" : fmtPct(v) });
        if (row.drift_flag && row.drift_flag !== "none") {
          td.className = "drift-" + row.drift_flag;
        }
        tr.appendChild(td);
      });
      tr.appendChild(el("td", { text: row.drift_flag || "none" }));
      table.appendChild(tr);
    });

    root.appendChild(el(
      "div",
      { class: "dash-panel" },
      el("h2", { text: "Rule × LLM agreement" }),
      el("div", { class: "sub", text: "obey-rate per (rule, LLM); shaded cells flag drift" }),
      table,
    ));
  }

  function renderHonestyPanel(root, honesty) {
    const rows = honesty && honesty.rows ? honesty.rows : [];
    const list = el("div", { class: "dash-honesty" });
    rows.forEach(r => {
      const pct = (r.self_check_verdict_agreement_rate || 0) * 100;
      list.appendChild(el(
        "div",
        { class: "row" },
        el("div", { class: "label", text: r.llm }),
        el("div", { class: "dash-bar honesty" }, el("span", { style: `width: ${pct.toFixed(1)}%` })),
        el("div", { text: `${pct.toFixed(1)}%  (${r.n_events})` }),
      ));
    });
    if (rows.length === 0) {
      list.appendChild(el("div", { class: "sub", text: "no LLM has accumulated enough events for an honesty signal yet" }));
    }
    root.appendChild(el(
      "div",
      { class: "dash-panel" },
      el("h2", { text: "Honesty meter" }),
      el("div", { class: "sub", text: "self_check ↔ hook verdict agreement per LLM (SaaS observability cannot compute this)" }),
      list,
    ));
  }

  function renderFrictionPanel(root, friction) {
    const rows = friction && friction.rows ? friction.rows : [];
    const max = rows.length > 0 ? Math.max(...rows.map(r => r.break_glass_count)) : 1;
    const list = el("div", { class: "dash-friction" });
    rows.forEach(r => {
      const w = max > 0 ? (r.break_glass_count / max) * 100 : 0;
      const reasons = (r.override_reasons_top || []).join(" · ") || "—";
      list.appendChild(el(
        "div",
        { class: "row" },
        el("div", { class: "label", text: r.rule_slug, title: reasons }),
        el("div", { class: "dash-bar friction" }, el("span", { style: `width: ${w.toFixed(1)}%` })),
        el("div", { text: String(r.break_glass_count) }),
      ));
    });
    if (rows.length === 0) {
      list.appendChild(el("div", { class: "sub", text: "no break-glass overrides in this window" }));
    }
    root.appendChild(el(
      "div",
      { class: "dash-panel" },
      el("h2", { text: "Top friction rules" }),
      el("div", { class: "sub", text: "rules with the most break-glass overrides in the window" }),
      list,
    ));
  }

  function renderCavemanPanel(root, payload) {
    const state = payload.caveman_state;
    const data = (payload.panels || {}).caveman || {};
    const panel = el("div", { class: "dash-panel" });
    panel.appendChild(el("h2", { text: "Caveman impact" }));

    if (state === "off") {
      panel.appendChild(el("div", { class: "sub", text:
        "Caveman is off in this consumer. Enable it in the Rules tab to see token-saving evidence here.",
      }));
      root.appendChild(panel);
      return;
    }
    if (state === "missing") {
      panel.appendChild(el("div", { class: "sub", text:
        "Caveman is not installed for this consumer (.ai-playbook/caveman.json absent). " +
        "Once Caveman is enabled and a session runs, this panel will populate.",
      }));
      root.appendChild(panel);
      return;
    }

    // state === "on"
    const components = data.components || {};
    const componentList = Object.entries(components)
      .map(([name, on]) => `${on ? "✓" : "✗"} ${name}`)
      .join("  ·  ");
    panel.appendChild(el("div", { class: "sub", text:
      `mode: ${data.mode || "?"}   ·   activation rate: ${fmtPct(data.activation_rate)}` +
      `   ·   ${componentList}`,
    }));
    panel.appendChild(el("div", { html:
      `tokens_in delta: <strong>${(data.tokens_in_delta || 0).toLocaleString()}</strong>` +
      `   ·   tokens_out delta: <strong>${(data.tokens_out_delta || 0).toLocaleString()}</strong>` +
      `   ·   cost saved: <strong>${fmtMoney(data.cost_saved_usd)}</strong>`,
    }));
    root.appendChild(panel);
  }

  function renderFooter(root, payload) {
    const ev = (payload.window || {});
    const skipped = ev.events_skipped || 0;
    const pieces = [];
    pieces.push("Renders only fields already authorized by the rule-event/v2 telemetry pipeline; ");
    pieces.push("target paths shown only in glob form (e.g. <code>*.env</code>); raw Bash commands and unhashed session IDs are not present in the source data.");
    if (skipped > 0) {
      pieces.push(` ${skipped} event(s) skipped this window (torn or unparseable).`);
    }
    root.appendChild(el("div", { class: "dash-footer", html: pieces.join("") }));
  }

  // -------------------------------------------------------------------------
  // mount() — entry point. Idempotent: replaces target's contents on each call.
  // -------------------------------------------------------------------------

  function mount(selector) {
    const root = typeof selector === "string" ? $(selector) : selector;
    if (!root) return;

    if (window.DASHBOARD_DATA_MISSING) {
      renderMissingSidecar(root);
      return;
    }

    const payload = window.DASHBOARD_DATA;
    if (!payload || typeof payload !== "object") {
      renderMissingSidecar(root);
      return;
    }

    if (payload.schema_version !== SCHEMA_VERSION) {
      renderSchemaMismatch(root, payload.schema_version);
      return;
    }

    // Empty-state branch.
    const seen = (payload.window || {}).events_seen || 0;
    const threshold = payload.empty_state_threshold || 100;
    if (seen < threshold) {
      renderEmpty(root, payload);
      return;
    }

    const chartReady = typeof window.Chart === "function" || typeof window.Chart === "object";

    if (!chartReady) {
      renderChartLibFailed(root, payload);
      return;
    }

    clear(root);
    renderHero(root, payload.panels);
    renderToolbar(root, payload);
    root.appendChild(el(
      "div",
      { class: "dash-grid-2" },
      el("div", null, /* placeholder; trend panel injected next */),
    ));
    // Render trend in its own panel.
    renderTrendChart(root, payload.panels.trend);
    renderMatrixPanel(root, payload.panels.matrix);
    renderHonestyPanel(root, payload.panels.honesty);
    renderFrictionPanel(root, payload.panels.friction);
    renderCavemanPanel(root, payload);
    renderFooter(root, payload);
  }

  window.DashboardRender = { mount: mount, SCHEMA_VERSION: SCHEMA_VERSION };
})();
