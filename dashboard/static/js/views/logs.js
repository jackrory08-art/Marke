import { get } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { dataTable } from '../table.js';

export const title = 'Logs and audit';

const LEVEL_KIND = { ERROR: 'rejected', CRITICAL: 'rejected', WARNING: 'caveats', INFO: 'neutral', DEBUG: 'neutral' };

export function mount(root) {
  const level = h('select', { id: 'l-level' },
    [['', 'All levels'], ['WARNING', 'Warnings and up'], ['ERROR', 'Errors only']].map(([v, t]) => h('option', { value: v }, t)));
  const logHolder = h('div');
  const auditHolder = h('div');

  const logTable = dataTable({
    caption: 'Recent bot log, newest first', rowKey: (r) => r.id,
    initialSort: { key: 'id', dir: 'desc' },
    columns: [
      { key: 'id', label: 'Time', sortValue: (r) => r.id, render: (r) => new Date(r.ts).toLocaleTimeString(undefined, { hour12: false }) },
      { key: 'level', label: 'Level', render: (r) => badge(r.level, LEVEL_KIND[r.level] || 'neutral') },
      { key: 'logger', label: 'Source', class: 'small' },
      { key: 'message', label: 'Message', class: 'cell-title', sortable: false },
    ],
  });
  const auditTable = dataTable({
    caption: 'Sign-ins and configuration changes, newest first', rowKey: (r) => r.id,
    initialSort: { key: 'id', dir: 'desc' },
    columns: [
      { key: 'id', label: 'When', sortValue: (r) => r.id, render: (r) => new Date(r.at).toLocaleString(undefined, { hour12: false }) },
      { key: 'event', label: 'Event', render: (r) => badge(r.event.replace(/_/g, ' '), /failure|lockout/.test(r.event) ? 'bad' : r.event === 'config_change' ? 'accent' : 'neutral') },
      { key: 'ip', label: 'From', class: 'mono small', render: (r) => r.ip || '—' },
      { key: 'detail', label: 'Detail', class: 'cell-title mono small', sortable: false,
        render: (r) => (r.detail && Object.keys(r.detail).length ? Object.entries(r.detail).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join('; ') : '') },
    ],
  });

  root.append(
    h('header', null, h('h1', { tabindex: '-1' }, 'Logs and audit')),
    h('section', { class: 'block' }, h('h2', null, 'Bot log'),
      h('div', { class: 'toolbar' }, h('label', { for: 'l-level' }, h('span', { class: 'visually-hidden' }, 'Level'), level)),
      logHolder),
    h('section', { class: 'block' }, h('h2', null, 'Audit trail'), auditHolder));

  async function loadLogs() {
    try {
      const data = await get(`/api/logs?limit=300${level.value ? `&level=${level.value}` : ''}`);
      clear(logHolder);
      if (!data.logs.length) logHolder.append(statePanel('empty', 'No log lines', 'Nothing has been logged at this level.'));
      else { logTable.setRows(data.logs); logHolder.append(logTable.el); }
    } catch (e) { clear(logHolder).append(statePanel('error', 'Could not load the log', e.message)); }
  }
  async function loadAudit() {
    try {
      const data = await get('/api/audit?limit=200');
      clear(auditHolder);
      if (!data.events.length) auditHolder.append(statePanel('empty', 'No audit events', 'Sign-ins and setting changes are recorded here.'));
      else { auditTable.setRows(data.events); auditHolder.append(auditTable.el); }
    } catch (e) { clear(auditHolder).append(statePanel('error', 'Could not load the audit trail', e.message)); }
  }
  clear(logHolder).append(statePanel('loading', 'Loading', 'Fetching the log.'));
  clear(auditHolder).append(statePanel('loading', 'Loading', 'Fetching the audit trail.'));
  level.addEventListener('change', loadLogs);
  loadLogs(); loadAudit();
  const timer = setInterval(() => { loadLogs(); loadAudit(); }, 10000);
  return () => clearInterval(timer);
}
