import { get, patch } from '../api.js';
import { h, clear, badge, statePanel } from '../dom.js';
import { num, usd } from '../format.js';

export const title = 'Settings';

export function mount(root) {
  const body = h('div');
  const status = h('p', { class: 'small', role: 'status', 'aria-live': 'polite' });
  root.append(h('header', null, h('h1', { tabindex: '-1' }, 'Settings'), status), body);
  body.append(statePanel('loading', 'Loading', 'Fetching settings.'));

  async function save(key, value) {
    status.textContent = 'Saving…';
    try {
      await patch('/api/settings', { [key]: value });
      status.textContent = `Saved ${key}.`;
      await load();
    } catch (e) {
      status.textContent = `Not saved: ${e.message}`;
      await load();
    }
  }

  function toggle(id, key, label, value, hint) {
    const input = h('input', { type: 'checkbox', id, checked: value ? true : null,
      onchange: () => save(key, input.checked) });
    return h('div', null, h('label', { for: id }, input, ' ', label), hint ? h('p', { class: 'small muted' }, hint) : null);
  }

  function numberField(id, key, label, value, schema, step) {
    const input = h('input', { type: 'number', id, value: String(value), step: String(step),
      min: schema.min ?? null, max: schema.max ?? null });
    const form = h('form', { class: 'toolbar', onsubmit: (ev) => { ev.preventDefault(); save(key, Number(input.value)); } },
      h('label', { for: id }, label), input, h('button', { type: 'submit' }, 'Save'));
    return form;
  }

  async function load() {
    try {
      const [cfg, usage] = await Promise.all([get('/api/settings'), get('/api/ai/usage')]);
      const s = cfg.settings, sc = cfg.schema, ro = cfg.readonly;
      clear(body).append(
        h('section', { class: 'block' }, h('h2', null, 'AI verification'),
          h('div', { class: 'cols' },
            h('div', { class: 'stack' },
              toggle('s-ai', 'ai.enabled', 'Verify pairs with AI', s['ai.enabled'],
                'Off is the kill switch: every pair becomes unverified and nothing is actionable.'),
              numberField('s-conf', 'ai.min_confidence', 'Min confidence, identical', s['ai.min_confidence'], sc['ai.min_confidence'], 0.01),
              numberField('s-conf2', 'ai.min_confidence_caveats', 'Min confidence, with caveats', s['ai.min_confidence_caveats'], sc['ai.min_confidence_caveats'], 0.01),
              numberField('s-calls', 'ai.daily_call_budget', 'Daily call budget', s['ai.daily_call_budget'], sc['ai.daily_call_budget'], 1),
              numberField('s-cost', 'ai.daily_cost_budget_usd', 'Daily cost budget (USD, 0 = none)', s['ai.daily_cost_budget_usd'], sc['ai.daily_cost_budget_usd'], 0.1)),
            h('dl', { class: 'facts' },
              h('dt', null, 'Provider'), h('dd', { class: 'mono' }, ro['ai.provider'] + (usage.ai && usage.ai.mock ? ' (MOCK)' : '')),
              h('dt', null, 'Model'), h('dd', { class: 'mono' }, ro['ai.model']),
              h('dt', null, 'Used today'), h('dd', { class: 'num' }, `${num(usage.calls_today)} of ${num(usage.call_budget)} calls`),
              h('dt', null, 'Cost today'), h('dd', { class: 'num' }, usd(usage.cost_today, 4)),
              h('dt', null, 'Tokens today'), h('dd', { class: 'num' }, `${num(usage.input_tokens)} in / ${num(usage.output_tokens)} out`)))),
        h('section', { class: 'block' }, h('h2', null, 'Sources and edge'),
          h('div', { class: 'cols' },
            h('div', null,
              toggle('s-kalshi', 'mode.kalshi_enabled', 'Include Kalshi', s['mode.kalshi_enabled']),
              toggle('s-pi', 'predictit.enabled', 'Include PredictIt (read-only, trade by hand)', s['predictit.enabled'],
                'PredictIt data is licensed for non-commercial use only.')),
            numberField('s-edge', 'trading.min_edge', 'Minimum net edge (price units)', s['trading.min_edge'], sc['trading.min_edge'], 0.005))),
        h('section', { class: 'block' }, h('h2', null, 'Fixed in this build'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Trading mode'), h('dd', null, badge(ro.trading_mode === 'dry_run' ? 'DRY RUN' : ro.trading_mode, 'accent')),
            h('dt', null, 'Data mode'), h('dd', null, ro.data_mode),
            h('dt', null, 'Orders'), h('dd', null, 'This tool is advisory. It never places orders.'))));
    } catch (e) {
      clear(body).append(statePanel('error', 'Could not load settings', e.message));
    }
  }
  load();
  return () => {};
}
