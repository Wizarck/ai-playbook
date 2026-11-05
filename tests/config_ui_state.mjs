// config-ui state round trip without a browser: runs config-ui/app.js in a Node
// vm against a stub DOM, loads an applied bundle the way applied-config.js does,
// and prints the Preview JSON, then the Preview JSON after "Reset to defaults".
// argv: <repo root> <applied bundle .json>
import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import vm from 'vm';

const [repo, appliedPath] = process.argv.slice(2);
const ui = join(repo, 'config-ui');
const TABS = ['rules', 'features', 'global', 'skills', 'mcps', 'settings', 'configfiles',
  'files', 'dispatchers', 'preview', 'dashboard'];

// Just enough DOM for init / render / reset to run: every lookup returns an
// inert element that records its event listeners.
function makeEl(extra = {}) {
  const listeners = {};
  return {
    listeners, dataset: {}, style: {}, hidden: false, textContent: '', innerHTML: '',
    value: '', checked: false, id: '',
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    removeEventListener() {}, appendChild(c) { return c; }, removeChild(c) { return c; },
    remove() {}, querySelector() { return makeEl(); }, querySelectorAll() { return []; },
    setAttribute() {}, getAttribute() { return null; }, closest() { return null; },
    scrollIntoView() {}, focus() {}, insertAdjacentHTML() {},
    ...extra,
  };
}
const bySelector = new Map();
const el = (sel) => {
  if (!bySelector.has(sel)) bySelector.set(sel, makeEl());
  return bySelector.get(sel);
};
const tabs = TABS.map(tab => makeEl({ dataset: { tab } }));
const document = {
  readyState: 'complete',
  addEventListener() {},
  querySelector: (sel) => el(sel),
  getElementById: (id) => el('#' + id),
  querySelectorAll: (sel) => (sel === '.tab' ? tabs : []),
  createElement: () => makeEl(),
};
const errors = [];
const ctx = {
  document, setTimeout, clearTimeout, confirm: () => true, navigator: {},
  fetch: () => Promise.reject(new Error('fetch is not available here')),
  console: { log() {}, warn() {}, error: (...a) => errors.push(a.join(' ')) },
};
ctx.window = ctx;
vm.createContext(ctx);
// The .js sidecars set the inventories as window globals, as under file://.
for (const f of readdirSync(ui).filter(f => f.endsWith('.js') && f !== 'app.js' && f !== 'dashboard.js')) {
  vm.runInContext(readFileSync(join(ui, f), 'utf8'), ctx, { filename: f });
}
ctx.APPLIED_CONFIG = JSON.parse(readFileSync(appliedPath, 'utf8'));
vm.runInContext(readFileSync(join(ui, 'app.js'), 'utf8'), ctx, { filename: 'app.js' });
await new Promise(resolve => setTimeout(resolve, 50));  // init() is async

const click = (node) => (node.listeners.click || []).forEach(fn => fn({ target: node }));
const preview = () => {
  click(tabs.find(t => t.dataset.tab === 'preview'));
  return JSON.parse(el('#preview-json').textContent);
};
const exported = preview();
const initBanner = el('#banner').textContent;
click(el('#btn-reset'));
const afterReset = preview();
console.log(JSON.stringify({ errors, initBanner, exported, afterReset }));
