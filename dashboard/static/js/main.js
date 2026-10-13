import * as api from './api.js';
import { connect, on } from './ws.js';
import { store, subscribe } from './store.js';
import { createMascot } from './mascot.js';
import { h, clear, badge } from './dom.js';
import { duration } from './format.js';

import * as overview from './views/overview.js';
import * as opportunities from './views/opportunities.js';
import * as pairs from './views/pairs.js';
import * as portfolio from './views/portfolio.js';
import * as logs from './views/logs.js';
import * as settings from './views/settings.js';

const ROUTES = [
  ['overview', 'Overview', overview],
  ['opportunities', 'Opportunities', opportunities],
  ['pairs', 'Matched pairs', pairs],
  ['portfolio', 'Portfolio and risk', portfolio],
  ['logs', 'Logs and audit', logs],
  ['settings', 'Settings', settings],
];

const main = document.getElementById('main');
const nav = document.getElementById('nav-list');
const statusLine = document.getElementById('status-line');
const meta = document.getElementById('topbar-meta');
const mascot = createMascot(document.getElementById('mascot'));
let unmount = null;
let current = null;

// ---------------------------------------------------------------- theme
const THEME_KEY = 'marke-theme';
function applyTheme(value) {
  if (value === 'light' || value === 'dark') document.documentElement.dataset.theme = value;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem(THEME_KEY)); } catch (e) { /* storage unavailable */ }

function cycleTheme() {
  const now = document.documentElement.dataset.theme;
  const next = now === 'dark' ? 'light' : now === 'light' ? null : 'dark';
  applyTheme(next);
  try { next ? localStorage.setItem(THEME_KEY, next) : localStorage.removeItem(THEME_KEY); } catch (e) { /* ignore */ }
  renderMeta();
}

// --------------------------------------------------------------- router
function buildNav() {
  clear(nav);
  for (const [id, label] of ROUTES) {
    nav.append(h('li', null, h('a', { href: `#/${id}`, dataset: { route: id } }, label)));
  }
}

function route() {
  const id = (location.hash.match(/^#\/([a-z]+)/) || [])[1] || 'overview';
  const entry = ROUTES.find(([rid]) => rid === id) || ROUTES[0];
  if (current === entry[0]) return;
  current = entry[0];
  if (unmount) { try { unmount(); } catch (e) { console.error(e); } }
  clear(main);
  for (const a of nav.querySelectorAll('a')) {
    if (a.dataset.route === current) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  document.title = `${entry[2].title} · Marke`;
  unmount = entry[2].mount(main);
  const heading = main.querySelector('h1');
  if (heading) heading.focus({ preventScroll: true });
}

// ------------------------------------------------------- header status
let uptimeBase = null;
function renderMeta() {
  const ai = store.ai || {};
  const mode = store.state && store.state.mode;
  const theme = document.documentElement.dataset.theme || 'auto';
  const paused = !!(store.state && store.state.paused);
  clear(meta).append(
    badge(mode === 'live' ? 'LIVE' : 'DRY RUN', 'accent'),
    ...(paused ? [badge('PAUSED', 'caveats')] : []),
    ai.enabled ? badge(ai.mock ? 'AI MOCK' : 'AI ON', ai.mock ? 'caveats' : 'ok') : badge('AI OFF', 'neutral'),
    h('span', { class: 'small muted num', id: 'uptime' }, uptimeBase == null ? '' : `up ${duration(uptimeBase)}`),
    h('button', { type: 'button', class: paused ? 'primary' : null, id: 'pause-toggle', onclick: () => setPaused(!paused),
      'aria-pressed': paused ? 'true' : 'false',
      title: paused ? 'Resume scanning, matching and AI checks' : 'Stop scanning, matching and AI checks' },
      paused ? 'Resume processing' : 'Pause processing'),
    h('button', { type: 'button', onclick: cycleTheme, 'aria-label': `Theme: ${theme}. Change theme` }, `Theme: ${theme}`),
    h('button', { type: 'button', onclick: logout }, 'Sign out'));
}

async function setPaused(next) {
  const btn = document.getElementById('pause-toggle');
  if (btn) btn.disabled = true;
  try {
    await api.patch('/api/settings', { 'mode.paused': next });
    if (store.state) store.state.paused = next;
    pendingLine = describeAgent();
    statusLine.textContent = pendingLine; lastLine = pendingLine;
  } catch (e) {
    statusLine.textContent = `Could not ${next ? 'pause' : 'resume'}: ${e.message}`;
  }
  renderMeta();
}

async function logout() {
  try { await api.post('/api/auth/logout'); } catch (e) { /* fall through */ }
  api.goToLogin();
}

// Status text is throttled so a screen reader isn't flooded.
let pendingLine = '';
let lastLine = '';
function describeAgent() {
  if (store.connection !== 'open') return store.connection === 'connecting' ? 'Connecting…' : 'Offline. Reconnecting…';
  if (store.state && store.state.paused) return 'Paused. Scanning, matching and AI checks are stopped.';
  const a = store.agent || {};
  const p = a.progress || {};
  const base = a.detail || ({ idle: 'Idle', scanning: 'Scanning', verifying: 'Verifying', analysing: 'Analysing', found: 'Found one', error: 'Error' }[a.state] || 'Idle');
  return base;
}
setInterval(() => {
  if (pendingLine !== lastLine) { statusLine.textContent = pendingLine; lastLine = pendingLine; }
}, 1500);

function onStore() {
  const agentState = store.connection === 'open' ? (store.agent.state || 'idle') : 'offline';
  mascot.set(agentState);
  pendingLine = describeAgent();
  if (store.state && store.state.uptime_seconds != null) uptimeBase = store.state.uptime_seconds;
  renderMeta();
}

async function start() {
  buildNav();
  try {
    await api.init();
  } catch (e) {
    clear(main).append(h('p', { role: 'alert' }, `Could not start: ${e.message}`));
    return;
  }
  subscribe(onStore);
  connect();
  onStore();
  statusLine.textContent = pendingLine;
  window.addEventListener('hashchange', route);
  route();
  setInterval(() => { if (uptimeBase != null) { uptimeBase += 1; const u = document.getElementById('uptime'); if (u) u.textContent = `up ${duration(uptimeBase)}`; } }, 1000);
}

start();
