// Config UI sweep — drives every interactive control under file:// and http://
// then writes test-errors.md + screenshots/ for human review.

import { chromium } from 'playwright';
import { spawn } from 'child_process';
import { writeFileSync, existsSync, mkdirSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { setTimeout as sleep } from 'timers/promises';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_DIR = resolve(__dirname, '..');
const FILE_URL = `file:///${UI_DIR.replace(/\\/g, '/')}/index.html`;
const HTTP_PORT = 8765;
const HTTP_URL = `http://localhost:${HTTP_PORT}/`;
const SHOTS = resolve(__dirname, 'screenshots');
const REPORT = resolve(__dirname, 'test-errors.md');

if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });

const findings = { A: [], B: [], console: [] };

async function snapshot(page, name) {
  try {
    await page.screenshot({ path: resolve(SHOTS, `${name}.png`), fullPage: false });
  } catch {}
  return `screenshots/${name}.png`;
}

function attachListeners(page, tag) {
  page.on('console', msg => {
    const t = msg.type();
    if (t === 'error' || t === 'warning') findings.console.push(`[${tag} console.${t}] ${msg.text()}`);
  });
  page.on('pageerror', err => findings.console.push(`[${tag} pageerror] ${err.message}`));
  page.on('requestfailed', req => {
    const url = req.url();
    if (!url.startsWith('chrome-extension:')) {
      findings.console.push(`[${tag} requestfailed] ${url} — ${req.failure()?.errorText || 'unknown'}`);
    }
  });
}

async function safeClick(page, sel, meta) {
  try {
    await page.click(sel, { timeout: 1500 });
    await sleep(80);
  } catch (e) {
    findings.B.push({ ...meta, sev: 'broken', expected: 'click succeeds', observed: e.message.split('\n')[0].slice(0, 120), evidence: '' });
  }
}

async function safeFill(page, sel, val, meta) {
  try {
    await page.fill(sel, val, { timeout: 1500 });
    await sleep(80);
  } catch (e) {
    findings.B.push({ ...meta, sev: 'broken', expected: 'fill succeeds', observed: e.message.split('\n')[0].slice(0, 120), evidence: '' });
  }
}

async function safeCheckToggle(page, sel, meta) {
  try {
    const before = await page.locator(sel).isChecked().catch(() => null);
    await page.click(sel, { timeout: 1500 });
    await sleep(80);
    const after = await page.locator(sel).isChecked().catch(() => null);
    if (before !== null && after !== null && before === after) {
      findings.B.push({ ...meta, sev: 'broken', expected: 'toggle flips checked state', observed: `state unchanged (${before})`, evidence: '' });
    }
  } catch (e) {
    findings.B.push({ ...meta, sev: 'broken', expected: 'toggle succeeds', observed: e.message.split('\n')[0].slice(0, 120), evidence: '' });
  }
}

// ============================================================
// Scenario A: file://
// ============================================================
async function runFileScenario(browser) {
  console.log('--- A: file:// ---');
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  attachListeners(page, 'A');
  page.on('dialog', d => d.dismiss().catch(() => {}));

  await page.goto(FILE_URL);
  await sleep(2500);

  const bannerText = (await page.locator('#banner').textContent().catch(() => '') || '').trim();
  const bannerClass = await page.locator('#banner').getAttribute('class').catch(() => '') || '';
  const shot1 = await snapshot(page, 'A1-load');
  if (/Failed to load|error/i.test(bannerText) || bannerClass.includes('error')) {
    findings.A.push({
      id: 'A1', sev: 'blocker', area: 'init',
      symptom: `Banner shows error: "${bannerText.slice(0, 110)}…" — init() aborted`,
      evidence: shot1,
    });
  } else if (bannerText === '') {
    findings.A.push({ id: 'A1', sev: 'info', area: 'init', symptom: 'No banner — init may have succeeded or never ran', evidence: shot1 });
  }

  const tabs = ['rules','features','global','skills','mcps','files','dispatchers','preview','dashboard'];
  for (const t of tabs) {
    try {
      await page.click(`.tab[data-tab="${t}"]`, { timeout: 1500 });
      await sleep(250);
      await snapshot(page, `A2-tab-${t}`);
      const panelText = await page.locator(`#panel-${t}`).innerText().catch(() => '');
      if (!panelText || panelText.trim().length < 10) {
        findings.A.push({
          id: `A2-${t}`, sev: 'blocker', area: 'tabs',
          symptom: `Tab "${t}" panel empty — wireEvents/renderAll never ran`,
          evidence: `screenshots/A2-tab-${t}.png`,
        });
      }
    } catch (e) {
      findings.A.push({
        id: `A2-${t}-click`, sev: 'blocker', area: 'tabs',
        symptom: `Cannot click tab "${t}": ${e.message.split('\n')[0].slice(0, 100)}`,
        evidence: '',
      });
    }
  }

  for (const btn of ['btn-reset', 'btn-export', 'btn-import']) {
    try {
      await page.click(`#${btn}`, { timeout: 1500 });
      await sleep(200);
    } catch (e) {
      findings.A.push({
        id: `A3-${btn}`, sev: 'blocker', area: 'header',
        symptom: `Cannot click #${btn}: ${e.message.split('\n')[0].slice(0, 80)}`,
        evidence: '',
      });
    }
  }

  await ctx.close();
}

// ============================================================
// Scenario B: http://localhost
// ============================================================
async function runHttpScenario(browser) {
  console.log('--- B: http:// ---');
  const server = spawn('python', ['-m', 'http.server', String(HTTP_PORT)], {
    cwd: UI_DIR, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.on('error', e => console.error('server error:', e.message));

  let ready = false;
  for (let i = 0; i < 30; i++) {
    await sleep(250);
    try {
      const r = await fetch(HTTP_URL);
      if (r.ok) { ready = true; break; }
    } catch {}
  }
  if (!ready) {
    findings.B.push({ id: 'B0-server', sev: 'blocker', tab: 'setup', control: 'python http.server', expected: 'serves on :8765', observed: 'never ready', evidence: '' });
    server.kill();
    return;
  }

  try {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    attachListeners(page, 'B');
    page.on('dialog', d => d.dismiss().catch(() => {}));

    await page.goto(HTTP_URL);
    let initOk = false;
    try {
      await page.waitForFunction(() => {
        const el = document.querySelector('#tab-count-rules');
        return el && el.textContent && el.textContent.trim().length > 0;
      }, { timeout: 8000 });
      initOk = true;
    } catch {
      findings.B.push({ id: 'B0-init', sev: 'blocker', tab: 'init', control: 'page load', expected: 'rules count populates', observed: 'timeout', evidence: await snapshot(page, 'B0-init-fail') });
    }
    await snapshot(page, 'B0-loaded');

    if (initOk) await runFunctionalSweep(page);

    await ctx.close();
  } finally {
    server.kill();
    await sleep(300);
  }
}

async function runFunctionalSweep(page) {
  // Rules
  await safeClick(page, '.tab[data-tab="rules"]', { id: 'B-rules-tab', tab: 'Rules', control: 'tab click' });
  await safeFill(page, '#rules-search', 'tdd', { id: 'B-rules-search', tab: 'Rules', control: '#rules-search' });
  for (const id of ['filter-modified', 'filter-has-advanced', 'filter-break-glass']) {
    await safeCheckToggle(page, `#${id}`, { id: `B-rf-${id}`, tab: 'Rules', control: `#${id}` });
  }
  await safeFill(page, '#rules-search', '', { id: 'B-rs-clear', tab: 'Rules', control: '#rules-search clear' });
  const ruleSlugs = await page.$$eval('[data-master]', els => els.slice(0, 3).map(el => el.getAttribute('data-master')));
  for (const slug of ruleSlugs) {
    await safeCheckToggle(page, `[data-master="${slug}"]`, { id: `B-rule-master-${slug}`, tab: 'Rules', control: `data-master="${slug}"` });
    await safeClick(page, `[data-toggle-adv="${slug}"]`, { id: `B-rule-advtog-${slug}`, tab: 'Rules', control: `data-toggle-adv="${slug}"` });
    await sleep(150);
    for (const L of ['L1', 'L2', 'L3']) {
      const sel = `[data-layer="${slug}:${L}"]`;
      if ((await page.locator(sel).count()) > 0) {
        await safeCheckToggle(page, sel, { id: `B-rule-layer-${slug}-${L}`, tab: 'Rules', control: `data-layer="${slug}:${L}"` });
      }
    }
    const advKeys = await page.$$eval(`[data-adv^="${slug}:"]`, els => els.slice(0, 2).map(el => el.getAttribute('data-adv')));
    for (const k of advKeys) {
      await safeCheckToggle(page, `[data-adv="${k}"]`, { id: `B-rule-adv-${k}`, tab: 'Rules', control: `data-adv="${k}"` });
    }
    if ((await page.locator(`[data-reason="${slug}"]`).count()) > 0) {
      await safeFill(page, `[data-reason="${slug}"]`, 'sweep test 12+', { id: `B-rule-reason-${slug}`, tab: 'Rules', control: `data-reason="${slug}"` });
    }
  }

  // Features
  await safeClick(page, '.tab[data-tab="features"]', { id: 'B-feat-tab', tab: 'Features', control: 'tab click' });
  const featKeys = await page.$$eval('[data-feature-enabled]', els => els.map(el => el.getAttribute('data-feature-enabled')));
  for (const k of featKeys.slice(0, 3)) {
    await safeCheckToggle(page, `[data-feature-enabled="${k}"]`, { id: `B-feat-en-${k}`, tab: 'Features', control: `data-feature-enabled="${k}"` });
    const modeSel = page.locator(`[data-feature-mode="${k}"]`);
    if ((await modeSel.count()) > 0) {
      try {
        const opts = await modeSel.locator('option').count();
        if (opts > 1) await modeSel.selectOption({ index: 1 });
      } catch (e) {
        findings.B.push({ id: `B-feat-mode-${k}`, sev: 'broken', tab: 'Features', control: `data-feature-mode="${k}"`, expected: 'selectOption succeeds', observed: e.message.split('\n')[0].slice(0, 100), evidence: '' });
      }
    }
    const comps = await page.$$eval(`[data-feature-component^="${k}:"]`, els => els.map(el => el.getAttribute('data-feature-component')));
    for (const c of comps) {
      await safeCheckToggle(page, `[data-feature-component="${c}"]`, { id: `B-feat-comp-${c}`, tab: 'Features', control: `data-feature-component="${c}"` });
    }
  }

  // Global flags
  await safeClick(page, '.tab[data-tab="global"]', { id: 'B-flag-tab', tab: 'Global flags', control: 'tab click' });
  const flags = await page.$$eval('[data-flag]', els => els.map(el => el.getAttribute('data-flag')));
  for (const f of flags) {
    await safeCheckToggle(page, `[data-flag="${f}"]`, { id: `B-flag-${f}`, tab: 'Global flags', control: `data-flag="${f}"` });
  }

  // Skills
  await safeClick(page, '.tab[data-tab="skills"]', { id: 'B-skills-tab', tab: 'Skills', control: 'tab click' });
  await safeFill(page, '#skills-search', 'test', { id: 'B-skills-search', tab: 'Skills', control: '#skills-search' });
  await safeCheckToggle(page, '#skills-filter-disabled', { id: 'B-skills-filter', tab: 'Skills', control: '#skills-filter-disabled' });
  await safeClick(page, '#skills-disable-all', { id: 'B-skills-dis-all', tab: 'Skills', control: '#skills-disable-all' });
  await safeClick(page, '#skills-enable-all', { id: 'B-skills-en-all', tab: 'Skills', control: '#skills-enable-all' });
  await safeFill(page, '#skills-search', '', { id: 'B-skills-clear', tab: 'Skills', control: '#skills-search clear' });
  // Un-toggle the onlyDisabled filter so the list re-populates with all enforced
  // skills; otherwise the individual-toggle step below has nothing to click.
  await safeCheckToggle(page, '#skills-filter-disabled', { id: 'B-skills-filter-off', tab: 'Skills', control: '#skills-filter-disabled (off)' });
  // Capture summary IMMEDIATELY before individual toggles so the comparison
  // isolates the individual-toggle code path (Bug 2 in fix-plan.md).
  const skSumBefore = (await page.locator('#skills-summary').textContent().catch(() => '') || '').trim();
  const skillSlugs = await page.$$eval('[data-enforce-skill]', els => els.slice(0, 3).map(el => el.getAttribute('data-enforce-skill')));
  for (const s of skillSlugs) {
    await safeCheckToggle(page, `[data-enforce-skill="${s}"]`, { id: `B-skill-${s}`, tab: 'Skills', control: `data-enforce-skill="${s}"` });
  }
  const skSumAfter = (await page.locator('#skills-summary').textContent().catch(() => '') || '').trim();
  if (skillSlugs.length > 0 && skSumBefore && skSumBefore === skSumAfter) {
    findings.B.push({ id: 'B-skills-summary', sev: 'broken', tab: 'Skills', control: '#skills-summary', expected: 'summary updates after individual toggles', observed: `unchanged after ${skillSlugs.length} toggle(s): "${skSumAfter.slice(0, 60)}"`, evidence: '' });
  }

  // MCPs
  await safeClick(page, '.tab[data-tab="mcps"]', { id: 'B-mcps-tab', tab: 'MCPs', control: 'tab click' });
  await safeFill(page, '#mcps-search', 'atlassian', { id: 'B-mcps-search', tab: 'MCPs', control: '#mcps-search' });
  await safeCheckToggle(page, '#mcps-filter-disabled', { id: 'B-mcps-filter', tab: 'MCPs', control: '#mcps-filter-disabled' });
  await safeClick(page, '#mcps-disable-all', { id: 'B-mcps-dis-all', tab: 'MCPs', control: '#mcps-disable-all' });
  await safeClick(page, '#mcps-enable-all', { id: 'B-mcps-en-all', tab: 'MCPs', control: '#mcps-enable-all' });
  await safeFill(page, '#mcps-search', '', { id: 'B-mcps-clear', tab: 'MCPs', control: '#mcps-search clear' });

  // Files (sidecar missing expected)
  await safeClick(page, '.tab[data-tab="files"]', { id: 'B-files-tab', tab: 'Files', control: 'tab click' });
  await snapshot(page, 'B-files');
  const filesItems = await page.locator('.files-list-item').count();
  const filesSummary = (await page.locator('#files-summary').textContent().catch(() => '') || '').trim();
  if (filesItems === 0 && !filesSummary) {
    findings.B.push({ id: 'B-files-empty-hint', sev: 'degraded', tab: 'Files', control: '#files-summary', expected: 'missing-sidecar hint visible', observed: 'no hint text and no items', evidence: 'screenshots/B-files.png' });
  }

  // Preview JSON
  await safeClick(page, '.tab[data-tab="preview"]', { id: 'B-preview-tab', tab: 'Preview JSON', control: 'tab click' });
  await sleep(200);
  const previewText = (await page.locator('#preview-json').textContent().catch(() => '') || '').trim();
  try {
    const obj = JSON.parse(previewText);
    if (obj.schema !== 'ai-playbook-config/v1') {
      findings.B.push({ id: 'B-preview-schema', sev: 'broken', tab: 'Preview JSON', control: '#preview-json', expected: 'schema "ai-playbook-config/v1"', observed: `got "${obj.schema}"`, evidence: '' });
    }
  } catch (e) {
    findings.B.push({ id: 'B-preview-parse', sev: 'blocker', tab: 'Preview JSON', control: '#preview-json', expected: 'valid JSON', observed: `JSON.parse failed: ${e.message.split('\n')[0].slice(0, 80)}`, evidence: '' });
  }

  // Dashboard
  await safeClick(page, '.tab[data-tab="dashboard"]', { id: 'B-dash-tab', tab: 'Dashboard', control: 'tab click' });
  await sleep(600);
  await snapshot(page, 'B-dashboard');
  const dashError = await page.locator('.dash-error, .dash-fail').count();
  if (dashError > 0) {
    findings.B.push({ id: 'B-dash-error', sev: 'broken', tab: 'Dashboard', control: '#panel-dashboard', expected: 'graceful empty state when sidecar missing', observed: '.dash-error/.dash-fail present', evidence: 'screenshots/B-dashboard.png' });
  }

  // Cross-tab: rule toggle affects counter
  await safeClick(page, '.tab[data-tab="rules"]', { id: 'B-cross-tab', tab: 'Cross-tab', control: 'tab click rules' });
  const cBefore = (await page.locator('#tab-count-rules').textContent().catch(() => '') || '').trim();
  if (ruleSlugs.length > 0) {
    await page.click(`[data-master="${ruleSlugs[0]}"]`).catch(() => {});
    await sleep(150);
    const cAfter = (await page.locator('#tab-count-rules').textContent().catch(() => '') || '').trim();
    if (cBefore && cBefore === cAfter) {
      findings.B.push({ id: 'B-counter', sev: 'broken', tab: 'Cross-tab', control: '#tab-count-rules', expected: 'counter updates after toggling a rule', observed: `unchanged: "${cAfter}"`, evidence: '' });
    }
  }
}

// ============================================================
// Report
// ============================================================
function writeReport(playwrightVer, chromiumVer) {
  const ts = new Date().toISOString();
  const lines = [];
  lines.push('# Config UI — Playwright sweep results');
  lines.push('');
  lines.push(`- Date: ${ts}`);
  lines.push(`- Target: ${UI_DIR.replace(/\\/g, '/')}  (config-ui at repo root after move; identical to GTM-Advisor copy pre-move)`);
  lines.push(`- Playwright: ${playwrightVer}`);
  lines.push(`- Chromium: ${chromiumVer}`);
  lines.push('');
  lines.push('## Scenario A: file://');
  lines.push('');
  if (findings.A.length === 0) {
    lines.push('_No findings._');
  } else {
    lines.push('| # | Sev | Area | Symptom | Evidence |');
    lines.push('|---|---|---|---|---|');
    for (const f of findings.A) {
      lines.push(`| ${f.id} | ${f.sev} | ${f.area} | ${escapePipe(f.symptom)} | ${f.evidence || ''} |`);
    }
  }
  lines.push('');
  lines.push('## Scenario B: http://localhost:8765');
  lines.push('');
  if (findings.B.length === 0) {
    lines.push('_No findings — every control behaved as expected._');
  } else {
    lines.push('| # | Sev | Tab | Control | Expected | Observed | Evidence |');
    lines.push('|---|---|---|---|---|---|---|');
    for (const f of findings.B) {
      lines.push(`| ${f.id} | ${f.sev} | ${f.tab} | \`${escapePipe(f.control)}\` | ${escapePipe(f.expected)} | ${escapePipe(f.observed)} | ${f.evidence || ''} |`);
    }
  }
  lines.push('');
  lines.push('## Console / network log digest');
  lines.push('');
  if (findings.console.length === 0) {
    lines.push('_No errors, warnings, or failed requests captured._');
  } else {
    lines.push('```');
    for (const ln of findings.console.slice(0, 120)) lines.push(ln);
    if (findings.console.length > 120) lines.push(`... (${findings.console.length - 120} more)`);
    lines.push('```');
  }
  lines.push('');
  lines.push('## Suggested fix anchors (informational, not in this plan)');
  lines.push('');
  lines.push('- `config-ui/app.js:29-35` — wrap each required fetch with `.catch(emptyFallback)` like skills/mcps already do.');
  lines.push('- `config-ui/app.js:80-83` — degrade gracefully; do not leave `state` null on init error.');
  lines.push('');
  lines.push('_Severity: blocker (UI dead) | broken (control misbehaves) | degraded (works but suboptimal) | cosmetic (visual only)._');
  writeFileSync(REPORT, lines.join('\n'));
}

function escapePipe(s) { return String(s || '').replace(/\|/g, '\\|').replace(/\n/g, ' '); }

// ============================================================
// main
// ============================================================
const browser = await chromium.launch();
const chromiumVer = browser.version();
console.log(`Chromium ${chromiumVer}`);
try {
  await runFileScenario(browser);
  await runHttpScenario(browser);
} finally {
  await browser.close();
}
writeReport('1.60.0', chromiumVer);
console.log(`Report: ${REPORT}`);
console.log(`Findings: A=${findings.A.length}  B=${findings.B.length}  console=${findings.console.length}`);
