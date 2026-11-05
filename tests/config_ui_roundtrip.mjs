// Applied state -> Preview JSON must keep every bundle section (config-ui hydration).
import { cpSync, readFileSync, writeFileSync, mkdtempSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { pathToFileURL } from 'url';

// argv: <repo root> <playwright package dir> <applied bundle .json>
const [repo, playwrightDir, appliedPath] = process.argv.slice(2);
const { chromium } = await import(pathToFileURL(join(playwrightDir, 'index.mjs')).href);
const root = mkdtempSync(join(tmpdir(), 'ui-'));
cpSync(join(repo, 'config-ui'), join(root, 'config-ui'), { recursive: true });
const applied = JSON.parse(readFileSync(appliedPath, 'utf8'));
writeFileSync(join(root, 'applied-config.js'), `window.APPLIED_CONFIG = ${JSON.stringify(applied)};`);
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => errors.push(String(e)));
await page.goto(`file://${root}/config-ui/index.html`);
await page.waitForTimeout(800);
await page.click('button.tab[data-tab="preview"]');
await page.waitForTimeout(300);
const out = JSON.parse(await page.textContent('#preview-json'));
const keys = ['pre_commit_extras', 'coderabbit_extras', 'mcp_project_servers', 'gitignore_extras', 'file_curate_intents', 'project_meta', 'backup_preferences'];
const missing = keys.filter(k => !(k in out));
console.log(JSON.stringify({ errors, missing, bundle: out }, null, 1));
await browser.close();
process.exit(missing.length || errors.length ? 1 : 0);
