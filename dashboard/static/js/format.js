export const PLATFORM = { polymarket: 'Polymarket', kalshi: 'Kalshi', predictit: 'PredictIt' };
export const platformName = (p) => PLATFORM[p] || p || '';

export function cents(x) {
  if (x == null || Number.isNaN(x)) return '—';
  return `${(x * 100).toFixed(1)}¢`;
}
export function price(x) {
  if (x == null || Number.isNaN(x)) return '—';
  return `$${Number(x).toFixed(3)}`;
}
export function usd(x, digits = 2) {
  if (x == null || Number.isNaN(x)) return '—';
  const sign = x < 0 ? '-' : '';
  return `${sign}$${Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}
export function num(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return '—';
  return Number(x).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function pct(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return '—';
  return `${(x * 100).toFixed(digits)}%`;
}
export function duration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400);
  const hrs = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d >= 2) return `${d}d`;
  if (d === 1) return `1d ${hrs}h`;
  if (hrs >= 1) return `${hrs}h ${m}m`;
  if (m >= 1) return `${m}m`;
  return `${s}s`;
}
export function ago(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 5) return 'just now';
  return `${duration(s)} ago`;
}
export function clock(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso || '';
  return new Date(t).toLocaleTimeString(undefined, { hour12: false });
}
export const VERDICT_LABEL = {
  verified: 'Verified', rejected: 'Rejected', unverified: 'Unverified', pending: 'Pending',
  dismissed: 'Dismissed', 'n/a': 'n/a',
};
export const VERDICT_TEXT = {
  identical: 'Identical', equivalent_with_caveats: 'Equivalent, with caveats', different: 'Different',
};
export const REASON_TEXT = {
  ai_disabled: 'AI is off', budget_exhausted: 'Daily budget used up', backoff: 'Waiting after an error',
  provider_error: 'Provider error', rate_limited: 'Rate limited', bad_output: 'Unusable model output',
  provider_unavailable: 'Provider unavailable', unexpected_error: 'Unexpected error',
  below_threshold: 'Below the confidence threshold', inverse_polarity: 'YES on one side is NO on the other',
  different: 'Different markets', missing_market_text: 'No market text',
};
