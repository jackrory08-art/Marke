import { get } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { num, pct, usd } from '../format.js';

export const title = 'Portfolio and risk';

function rowsOf(obj, labels) {
  return Object.entries(labels).filter(([k]) => obj && obj[k] !== undefined).flatMap(([k, [label, fmt]]) =>
    [h('dt', null, label), h('dd', { class: 'num' }, fmt(obj[k]))]);
}

export function mount(root) {
  const body = h('div');
  root.append(h('header', null, h('h1', { tabindex: '-1' }, 'Portfolio and risk'),
    h('p', { class: 'muted' }, 'Simulated balances for dry-run mode.')), body);
  body.append(statePanel('loading', 'Loading', 'Fetching portfolio and risk.'));

  async function load() {
    try {
      const s = await get('/api/state');
      const p = s.portfolio || {};
      const r = s.risk || {};
      if (!Object.keys(p).length && !Object.keys(r).length) {
        clear(body).append(statePanel('empty', 'No portfolio data yet', 'Numbers appear once the bot has started.'));
        return;
      }
      const pnl = p.pnl || {};
      clear(body).append(h('div', { class: 'cols' },
        h('section', null, h('h2', null, 'Portfolio'),
          h('dl', { class: 'facts' }, rowsOf(p, {
            initial_balance: ['Starting balance', usd], cash_balance: ['Cash', usd],
            total_exposure: ['Exposure', usd], total_trades: ['Trades', num],
            win_rate: ['Win rate', (x) => pct(x, 1)], total_volume: ['Volume', usd],
            positions_count: ['Open positions', num], markets_traded: ['Markets traded', num],
          }), rowsOf(pnl, {
            total_pnl: ['Total P&L', usd], realized_pnl: ['Realized', usd], unrealized_pnl: ['Unrealized', usd],
          }))),
        h('section', null, h('h2', null, 'Risk'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Within limits'), h('dd', null, r.within_limits ? badge('Yes', 'ok') : badge('No', 'bad')),
            h('dt', null, 'Kill switch'), h('dd', null, r.kill_switch_triggered ? badge(`Triggered: ${r.kill_switch_reason || ''}`, 'bad') : badge('Armed', 'neutral')),
            rowsOf(r, {
              global_exposure: ['Exposure', usd], max_global_exposure: ['Exposure limit', usd],
              utilization_pct: ['Utilisation', (x) => `${x.toFixed(1)}%`],
              daily_pnl: ['Daily P&L', usd], max_daily_loss: ['Daily loss limit', usd],
              current_drawdown_pct: ['Drawdown', (x) => `${x.toFixed(1)}%`],
              max_drawdown_pct: ['Drawdown limit', (x) => `${x.toFixed(1)}%`],
              markets_with_exposure: ['Markets with exposure', num], session_trade_count: ['Trades this session', num],
            })))));
    } catch (e) {
      clear(body).append(statePanel('error', 'Could not load portfolio', e.message));
    }
  }
  load();
  const timer = setInterval(load, 5000);
  return () => clearInterval(timer);
}
