import { get } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { dataTable } from '../table.js';
import { on } from '../ws.js';
import { cents, duration, num, platformName, price, VERDICT_LABEL, VERDICT_TEXT, REASON_TEXT, pct } from '../format.js';

export const title = 'Opportunities';

export function verdictBadge(status) {
  return badge(VERDICT_LABEL[status] || status, status === 'n/a' ? 'n-a' : status);
}

export function refsBlock(refs) {
  return h('div', { class: 'refs' }, (refs || []).map((r) => h('div', { class: 'ref' },
    h('div', null, badge(platformName(r.platform), 'neutral'), ' ', h('strong', null, r.title)),
    h('p', { class: 'small muted' },
      r.end_date ? `Ends ${r.end_date.slice(0, 10)}` : 'No end date', r.outcome_label ? ` · ${r.outcome_label}` : '',
      r.resolution_source ? ` · Source: ${r.resolution_source}` : ''),
    r.rules_text ? h('p', { class: 'rules small' }, r.rules_text)
      : h('p', { class: 'small muted' }, 'This platform does not publish resolution rules.'),
    r.url ? h('a', { class: 'small', href: r.url, target: '_blank', rel: 'noopener noreferrer' }, 'Open market') : null)));
}

export function differencesList(diffs) {
  if (!diffs || !diffs.length) return null;
  return h('ul', { class: 'plain small' }, diffs.map((d) =>
    h('li', null, badge(d.kind.replace(/_/g, ' '), 'caveats'), ' ', d.detail)));
}

function detail(o) {
  if (o.kind === 'bundle') {
    return h('div', null, h('p', null, 'Buy both outcomes on the same market for less than $1. This is an in-platform bundle, so no cross-platform check applies.'));
  }
  const a = o.analysis;
  const v = o.verdict;
  const fees = o.fees || {};
  return h('div', { class: 'cols' },
    h('div', null,
      h('h3', null, 'Trade'),
      h('p', null, `Buy ${o.token} on ${platformName(o.buy_platform)} at ${price(o.buy_price)}, sell ${o.token} on ${platformName(o.sell_platform)} at ${price(o.sell_price)}.`),
      o.manual_trade ? h('p', { class: 'small' }, badge('PredictIt: place manually', 'accent'), ' This tool cannot trade there.') : null,
      h('dl', { class: 'facts small' },
        h('dt', null, 'Gross edge'), h('dd', { class: 'num' }, cents(o.gross_edge)),
        h('dt', null, 'Net edge'), h('dd', { class: 'num' }, cents(o.net_edge)),
        h('dt', null, 'Fees'), h('dd', { class: 'num' }, `${cents(fees.total)} (buy ${cents(fees.buy_fee)}, sell ${cents(fees.sell_fee)}, gas ${cents(fees.gas)}${fees.profit_fee ? `, profit fee ${cents(fees.profit_fee)}` : ''}${fees.withdrawal_fee ? `, withdrawal ${cents(fees.withdrawal_fee)}` : ''})`),
        h('dt', null, 'Slippage'), h('dd', { class: 'num' }, o.slippage_estimate == null ? 'Unknown' : cents(o.slippage_estimate)),
        h('dt', null, 'Depth'), h('dd', { class: 'num' }, o.depth == null ? 'Not published' : `${num(o.depth)} shares`),
        h('dt', null, 'Suggested size'), h('dd', { class: 'num' }, `${num(o.suggested_size, 1)} shares`),
        h('dt', null, 'Time to expiry'), h('dd', { class: 'num' }, duration(o.time_to_expiry)))),
    h('div', null,
      h('h3', null, 'Verification'),
      v ? h('div', null,
        h('p', null, verdictBadge(o.verification_status), ' ',
          v.verdict ? `${VERDICT_TEXT[v.verdict] || v.verdict}, confidence ${pct(v.confidence)}` : (REASON_TEXT[v.reason] || '')),
        v.short_reason ? h('p', { class: 'small' }, v.short_reason) : null,
        differencesList(v.differences))
        : h('p', { class: 'muted' }, 'Not verified yet.'),
      h('h3', null, 'AI summary'),
      a ? h('div', null,
        h('p', null, a.summary),
        h('ul', { class: 'plain small' }, (a.risks || []).map((r) =>
          h('li', null, badge(r.severity, r.severity === 'high' ? 'rejected' : r.severity === 'medium' ? 'caveats' : 'neutral'),
            ' ', h('strong', null, r.kind.replace(/_/g, ' ')), ': ', r.detail))))
        : h('p', { class: 'muted' }, o.actionable ? 'No analysis yet.' : 'Analysis runs only for verified opportunities.')),
    h('div', { class: 'span-all' }, h('h3', null, 'Resolution rules'), refsBlock(o.refs)));
}

export function mount(root) {
  const status = h('select', { id: 'f-status' },
    ['', 'verified', 'pending', 'unverified', 'rejected', 'n/a'].map((s) =>
      h('option', { value: s }, s ? VERDICT_LABEL[s] : 'Any verification')));
  const platform = h('select', { id: 'f-platform' },
    ['', 'polymarket', 'kalshi', 'predictit'].map((s) => h('option', { value: s }, s ? platformName(s) : 'Any platform')));
  const actionable = h('input', { type: 'checkbox', id: 'f-actionable' });
  const table = dataTable({
    caption: 'Opportunities, best net edge first',
    rowKey: (o) => o.id,
    expandable: true,
    renderDetail: detail,
    initialSort: { key: 'net_edge', dir: 'desc' },
    rowClass: (o) => (o.actionable ? null : 'dim'),
    columns: [
      { key: 'title', label: 'Pair', class: 'cell-title', sortValue: (o) => o.title_a,
        render: (o) => h('span', null, o.title_a, o.title_b && o.title_b !== o.title_a ? h('span', { class: 'sub' }, o.title_b) : null) },
      { key: 'platforms', label: 'Platforms', sortValue: (o) => o.platforms.join(),
        render: (o) => (o.kind === 'bundle' ? `Polymarket bundle (${(o.bundle_type || '').replace('bundle_', '') || 'both outcomes'})` : `${platformName(o.buy_platform)} → ${platformName(o.sell_platform)}`) },
      { key: 'net_edge', label: 'Net edge', numeric: true, render: (o) => cents(o.net_edge) },
      { key: 'depth', label: 'Depth', numeric: true, render: (o) => (o.depth == null ? '—' : num(o.depth)) },
      { key: 'verdict', label: 'Verdict', sortValue: (o) => o.verification_status,
        render: (o) => h('span', null, verdictBadge(o.verification_status), o.manual_trade ? ' ' : null,
          o.manual_trade ? badge('manual', 'accent') : null) },
      { key: 'quality_score', label: 'Quality', numeric: true, render: (o) => (o.quality_score == null ? '—' : String(o.quality_score)) },
    ],
  });
  const holder = h('div');
  const count = h('p', { class: 'muted small', 'aria-live': 'polite' });

  root.append(
    h('header', null, h('h1', { tabindex: '-1' }, 'Opportunities'), count),
    h('div', { class: 'toolbar' },
      h('label', { for: 'f-status' }, h('span', { class: 'visually-hidden' }, 'Verification'), status),
      h('label', { for: 'f-platform' }, h('span', { class: 'visually-hidden' }, 'Platform'), platform),
      h('label', { for: 'f-actionable' }, actionable, 'Actionable only')),
    holder);

  let loaded = false;
  async function load() {
    const q = new URLSearchParams();
    if (status.value) q.set('status', status.value);
    if (platform.value) q.set('platform', platform.value);
    if (actionable.checked) q.set('actionable', 'true');
    try {
      const data = await get(`/api/opportunities?${q}`);
      loaded = true;
      count.textContent = `${data.count} shown`;
      clear(holder);
      if (!data.opportunities.length) {
        holder.append(statePanel('empty', 'No opportunities',
          'Nothing clears the minimum edge right now. New ones appear here when found.'));
      } else {
        table.setRows(data.opportunities);
        holder.append(table.el);
      }
    } catch (e) {
      clear(holder).append(statePanel('error', 'Could not load opportunities', e.message));
    }
  }
  clear(holder).append(statePanel('loading', 'Loading', 'Fetching opportunities.'));

  let debounce;
  const refresh = () => { clearTimeout(debounce); debounce = setTimeout(load, 400); };
  for (const el of [status, platform, actionable]) el.addEventListener('change', load);
  const offs = ['opportunity', 'analysis_ready', 'verification_finished', 'pair_dismissed']
    .map((t) => on(t, refresh));
  const timer = setInterval(load, 10000);
  load();
  return () => { clearInterval(timer); clearTimeout(debounce); offs.forEach((f) => f()); };
}
