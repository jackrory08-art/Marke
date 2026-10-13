import { get } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { subscribe, store } from '../store.js';
import { clock, duration, num, platformName, usd } from '../format.js';

export const title = 'Overview';

export function mount(root) {
  const body = h('div');
  root.append(h('header', null, h('h1', { tabindex: '-1' }, 'Overview'),
    h('p', { class: 'muted' }, 'Advisory only. This tool never places orders.')), body);
  body.append(statePanel('loading', 'Loading', 'Fetching the current state.'));

  async function load() {
    try {
      const [state, usage] = await Promise.all([get('/api/state'), get('/api/ai/usage')]);
      render(state, usage);
    } catch (e) {
      clear(body).append(statePanel('error', 'Could not load the overview', e.message));
    }
  }

  function render(state, usage) {
    const cp = state.cross_platform || {};
    const pairs = state.pairs || {};
    const ai = usage.ai || {};
    const used = usage.call_budget ? usage.calls_today / usage.call_budget : 0;
    const op = state.operational || {};
    clear(body).append(
      h('div', { class: 'cols' },
        h('section', null,
          h('h2', null, 'Bot'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Mode'), h('dd', null, badge(state.mode === 'dry_run' ? 'DRY RUN' : state.mode, 'accent')),
            h('dt', null, 'Running'), h('dd', null, state.is_running ? 'Yes' : 'No'),
            h('dt', null, 'Uptime'), h('dd', { class: 'num' }, duration(state.uptime_seconds)),
            h('dt', null, 'Polymarket markets'), h('dd', { class: 'num' }, num(op.total_markets ?? cp.polymarket_markets)),
            h('dt', null, 'With prices'), h('dd', { class: 'num' }, num(op.markets_with_prices)),
            h('dt', null, 'Kalshi markets'), h('dd', { class: 'num' }, num(cp.kalshi_markets)),
            h('dt', null, 'Matching'), h('dd', null, matchingText(cp)))),
        h('section', null,
          h('h2', null, 'Cross-platform pairs'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Total'), h('dd', { class: 'num' }, num(pairs.total ?? 0)),
            h('dt', null, 'Verified'), h('dd', null, badge(num(pairs.verified ?? 0), 'verified')),
            h('dt', null, 'Pending'), h('dd', null, badge(num(pairs.pending ?? 0), 'pending')),
            h('dt', null, 'Rejected'), h('dd', null, badge(num(pairs.rejected ?? 0), 'rejected')),
            h('dt', null, 'Unverified'), h('dd', null, badge(num(pairs.unverified ?? 0), 'unverified')),
            h('dt', null, 'Dismissed'), h('dd', null, badge(num(pairs.dismissed ?? 0), 'dismissed')),
            h('dt', null, 'Actionable now'), h('dd', { class: 'num' },
              num((cp.cross_opportunities || []).filter((o) => o.actionable).length)),
            h('dt', null, 'Last scan'), h('dd', null, scanText(cp.last_scan)))),
        h('section', null,
          h('h2', null, 'AI verification'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Status'), h('dd', null,
              ai.enabled ? (ai.configured === false ? badge('NO API KEY', 'bad') : badge(ai.mock ? 'ON (MOCK)' : 'ON', ai.mock ? 'caveats' : 'ok')) : badge('OFF', 'neutral')),
            ai.enabled && ai.configured === false ? h('dt', null, 'Fix') : null,
            ai.enabled && ai.configured === false ? h('dd', null, 'Set GEMINI_API_KEY in your hosting variables. Until then no pair can be verified, so nothing is actionable.') : null,
            h('dt', null, 'Model'), h('dd', { class: 'mono small' }, `${ai.provider || '—'} / ${ai.model || '—'}`),
            h('dt', null, 'Calls today'), h('dd', { class: 'num' }, `${num(usage.calls_today)} of ${num(usage.call_budget)}`),
            h('dt', null, 'Cost today'), h('dd', { class: 'num' }, usd(usage.cost_today, 4)),
            h('dt', null, 'Budget'), h('dd', null,
              h('meter', { min: '0', max: '1', low: '0.7', high: '0.9', optimum: '0', value: String(Math.min(1, used)),
                'aria-label': 'Daily call budget used' })),
            usage.exhausted ? h('dt', null, 'Note') : null,
            usage.exhausted ? h('dd', null, 'Daily budget used up. New pairs stay unverified until tomorrow.') : null))),
      h('section', { class: 'block' },
        h('h2', null, 'Recent events'),
        eventsList()));
  }

  function scanText(scan) {
    if (!scan) return 'No scan yet';
    const ago = Math.max(0, Math.round(Date.now() / 1000 - scan.at));
    const why = (scan.why_unpriced || []).length ? ` Missing: ${scan.why_unpriced.join('; ')}.` : '';
    return `${num(scan.pairs)} pairs, ${num(scan.priced ?? 0)} with live prices, ${num(scan.opportunities)} with an edge (${ago}s ago).${why}`;
  }

  function matchingText(cp) {
    if (cp.simulated) return 'Demo pairs (simulation)';
    if (!cp.enabled) return 'Cross-platform is off';
    if (cp.matching_status === 'matching') return `${cp.matching_progress ?? 0}% (${num(cp.matching_checked)} of ${num(cp.matching_total)} markets)`;
    return cp.matching_status || 'idle';
  }

  function eventsList() {
    if (!store.events.length) {
      return statePanel('empty', 'Nothing yet', 'Events appear here as pairs are verified and opportunities are found.');
    }
    return h('ul', { class: 'plain' }, store.events.slice(0, 12).map((ev) =>
      h('li', null, h('span', { class: 'mono small muted' }, clock(ev.at)), '  ', ev.text)));
  }

  load();
  const timer = setInterval(load, 15000);
  let last = 0;
  const unsub = subscribe(() => {
    if (Date.now() - last < 2000) return;
    last = Date.now();
    load();
  });
  return () => { clearInterval(timer); unsub(); };
}
