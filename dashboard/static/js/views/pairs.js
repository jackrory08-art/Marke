import { get, post, del } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { dataTable } from '../table.js';
import { on } from '../ws.js';
import { pct, platformName, REASON_TEXT, VERDICT_LABEL, VERDICT_TEXT } from '../format.js';
import { verdictBadge, refsBlock, differencesList } from './opportunities.js';
import { setEvent } from '../store.js';

export const title = 'Matched pairs';

export function mount(root) {
  const status = h('select', { id: 'p-status' },
    ['', 'verified', 'pending', 'unverified', 'rejected', 'dismissed'].map((s) =>
      h('option', { value: s }, s ? VERDICT_LABEL[s] : 'Any status')));
  const platform = h('select', { id: 'p-platform' },
    ['', 'polymarket', 'kalshi', 'predictit'].map((s) => h('option', { value: s }, s ? platformName(s) : 'Any platform')));
  const note = h('p', { class: 'muted small', 'aria-live': 'polite' });
  const holder = h('div');

  async function act(fn, pair, message) {
    try {
      await fn();
      setEvent(message, 'pair');
      await load();
    } catch (e) {
      note.textContent = e.message;
    }
  }

  const table = dataTable({
    caption: 'Pairs proposed by the title matcher and checked by the verifier',
    rowKey: (p) => p.pair_id,
    expandable: true,
    initialSort: { key: 'similarity', dir: 'desc' },
    rowClass: (p) => (p.dismissed ? 'dim' : null),
    renderDetail: (p) => h('div', null,
      p.verdict && p.verdict.short_reason ? h('p', null, p.verdict.short_reason) : null,
      p.verdict && p.verdict.reason ? h('p', { class: 'small muted' }, REASON_TEXT[p.verdict.reason] || p.verdict.reason) : null,
      differencesList(p.verdict && p.verdict.differences),
      h('h3', null, 'Resolution rules'), refsBlock(p.refs)),
    columns: [
      { key: 'title', label: 'Pair', class: 'cell-title', sortValue: (p) => p.title_a,
        render: (p) => h('span', null, p.title_a, h('span', { class: 'sub' }, p.title_b)) },
      { key: 'platforms', label: 'Platforms', sortValue: (p) => p.platforms.join(),
        render: (p) => p.platforms.map(platformName).join(' / ') },
      { key: 'similarity', label: 'Match', numeric: true, render: (p) => pct(p.similarity) },
      { key: 'status', label: 'Verdict',
        render: (p) => h('span', null, verdictBadge(p.status),
          p.verdict && p.verdict.verdict ? h('span', { class: 'sub' },
            `${VERDICT_TEXT[p.verdict.verdict] || p.verdict.verdict} · ${pct(p.verdict.confidence)}`) : null,
          p.status === 'unverified' && p.verdict && p.verdict.reason
            ? h('span', { class: 'sub' }, REASON_TEXT[p.verdict.reason] || p.verdict.reason) : null) },
      { key: 'diffs', label: 'Differences', sortable: false,
        render: (p) => {
          const d = (p.verdict && p.verdict.differences) || [];
          return d.length ? h('span', null, d.map((x) => [badge(x.kind.replace(/_/g, ' '), 'caveats'), ' '])) : '—';
        } },
      { key: 'actions', label: 'Actions', sortable: false,
        render: (p) => h('span', { class: 'toolbar' },
          p.dismissed
            ? h('button', { type: 'button', onclick: () => act(() => del(`/api/pairs/${encodeURIComponent(p.pair_id)}/dismiss`), p, 'Pair restored') }, 'Undismiss')
            : h('button', { type: 'button', onclick: () => act(() => post(`/api/pairs/${encodeURIComponent(p.pair_id)}/dismiss`), p, 'Pair dismissed') }, 'Dismiss'),
          h('button', { type: 'button', onclick: () => act(() => post(`/api/pairs/${encodeURIComponent(p.pair_id)}/reverify`), p, 'Re-verification queued') }, 'Re-verify')) },
    ],
  });

  root.append(
    h('header', null, h('h1', { tabindex: '-1' }, 'Matched pairs'), note),
    h('div', { class: 'toolbar' },
      h('label', { for: 'p-status' }, h('span', { class: 'visually-hidden' }, 'Status'), status),
      h('label', { for: 'p-platform' }, h('span', { class: 'visually-hidden' }, 'Platform'), platform)),
    h('div', null, holder));

  async function load() {
    const q = new URLSearchParams();
    if (status.value) q.set('status', status.value);
    if (platform.value) q.set('platform', platform.value);
    try {
      const data = await get(`/api/pairs?${q}`);
      clear(holder);
      const c = data.counts || {};
      if (!data.pairs.length) {
        holder.append(statePanel('empty', 'No pairs', c.total
          ? 'No pairs match these filters.'
          : 'Pairs show up after the matcher finishes comparing platforms.'));
      } else {
        note.textContent = `${data.pairs.length} shown of ${c.total}`;
        table.setRows(data.pairs);
        holder.append(table.el);
      }
    } catch (e) {
      clear(holder).append(statePanel('error',
        e.status === 503 ? 'Matching is not running' : 'Could not load pairs', e.message));
    }
  }
  clear(holder).append(statePanel('loading', 'Loading', 'Fetching pairs.'));

  let debounce;
  const refresh = () => { clearTimeout(debounce); debounce = setTimeout(load, 500); };
  status.addEventListener('change', load);
  platform.addEventListener('change', load);
  const offs = ['verification_finished', 'pair_dismissed'].map((t) => on(t, refresh));
  const timer = setInterval(load, 15000);
  load();
  return () => { clearInterval(timer); clearTimeout(debounce); offs.forEach((f) => f()); };
}
