// Small shared state for the header and overview: connection, bot state,
// agent state and a ring of recent events. Views fetch their own tables.
import { on } from './ws.js';

const subscribers = new Set();
export const store = {
  connection: 'connecting',
  state: null,
  agent: { state: 'idle', detail: '', progress: { done: 0, total: 0 } },
  ai: { enabled: false, provider: null, model: null, mock: false, budget: {} },
  events: [],
};

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

function notify() {
  for (const fn of subscribers) {
    try { fn(store); } catch (e) { console.error(e); }
  }
}

function pushEvent(text, kind) {
  store.events.unshift({ at: new Date().toISOString(), text, kind });
  if (store.events.length > 30) store.events.length = 30;
}

function applyState(data) {
  if (!data) return;
  store.state = data;
  if (data.agent_state) store.agent = data.agent_state;
  if (data.ai) store.ai = data.ai;
}

on('_status', ({ status }) => { store.connection = status; notify(); });
on('initial', (d) => { applyState(d); notify(); });
on('update', (d) => { applyState(d); notify(); });
on('agent_state', (d) => { store.agent = d; notify(); });
on('ai_budget', (d) => { store.ai = { ...store.ai, budget: d }; notify(); });
on('config_changed', (d) => {
  pushEvent(`Setting ${d.key} changed by ${d.by}`, 'config');
  if (d.key === 'ai.enabled') store.ai = { ...store.ai, enabled: d.value };
  if (d.key === 'mode.paused' && store.state) store.state = { ...store.state, paused: d.value };
  notify();
});
on('verification_finished', (d) => {
  pushEvent(`Pair ${d.status}${d.verdict ? ` (${d.verdict.replace(/_/g, ' ')})` : ''}`, 'verify');
  notify();
});
on('opportunity', (d) => {
  if (d.actionable) pushEvent(`Opportunity: ${(d.net_edge * 100).toFixed(1)}¢ net edge`, 'opp');
  notify();
});
on('analysis_ready', () => { pushEvent('Analysis ready', 'analysis'); notify(); });
on('pair_dismissed', (d) => { pushEvent(d.dismissed ? 'Pair dismissed' : 'Pair restored', 'pair'); notify(); });

export function setEvent(text, kind) { pushEvent(text, kind); notify(); }
