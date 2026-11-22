import type { MarketGroup, MarketInstrument, MarketQuote } from '../types/market';

/** Market presentation metadata: groups, ticker-tape watchlist, timeframes. */

export const GROUP_ORDER: MarketGroup[] = ['indices', 'metals', 'stocks', 'forex', 'crypto', 'commodities'];

/** Featured instrument on the overview page. */
export const FEATURED_SYMBOL = 'BTC/USD';

/** Compact asset bar below the main navbar (symbols must exist in the backend registry). */
export const TAPE_SYMBOLS = [
  'BTC/USD',
  'XAU/USD',
  'EURUSD',
  'GBPUSD',
  'USDJPY',
  'AAPL',
  'NVDA',
  'TSLA',
  'MSFT',
  'ETH-USD',
  'GC=F',
  'CL=F',
  '^GSPC',
  'SPY',
] as const;

/** Subset of tape symbols eligible for Twelve Data WebSocket streaming (avoids wasting WS slots on yfinance-only symbols). */
export const TAPE_STREAM_SYMBOLS = [
  'BTC/USD',
  'EURUSD',
  'XAU/USD',
  'AAPL',
  'ETH-USD',
  'NVDA',
  'MSFT',
  'TSLA',
] as const;

/** Timeframe options offered in the price chart. Lookbacks for 1m/5m/15m span
 * at least 5-14 days so weekend/holiday views still return recent trading bars
 * while staying inside upstream intraday lookback limits (e.g. Yahoo 7d for 1m). */
export const ALL_TIMEFRAMES = [
  { id: '1m', days: 5 },
  { id: '5m', days: 7 },
  { id: '15m', days: 14 },
  { id: '1H', days: 60 },
  { id: '4H', days: 180 },
  { id: '1D', days: 365 },
  { id: '1W', days: 1825 },
  { id: '1M', days: 1825 },
] as const;

export type TimeframeId = (typeof ALL_TIMEFRAMES)[number]['id'];

/** Priority watchlist for the live subscription budget (server enforces the cap). */
export const STREAM_PRIORITY = [
  'BTC/USD',
  'EURUSD',
  'XAU/USD',
  'AAPL',
  'ETH-USD',
  'NVDA',
  'MSFT',
  'TSLA',
  'GBPUSD',
  'USDJPY',
  'GOOGL',
  'AMZN',
  'META',
  'SPY',
] as const;

const FX_6_RE = /^[A-Z]{6}$/;

/** Decimal precision tailored by asset class so FX pip moves (e.g. 1.09678) are clearly visible. */
export function priceDecimals(
  symbol: string,
  groupOrClass?: string | null,
  samplePrice?: number | null,
): number {
  const upper = (symbol ?? '').toUpperCase().replace('/', '');
  const g = (groupOrClass ?? '').toLowerCase();
  const isFx = g === 'forex' || g === 'fx' || (FX_6_RE.test(upper) && !upper.startsWith('X'));
  if (isFx) {
    return upper.includes('JPY') ? 3 : 5;
  }
  if (samplePrice !== null && samplePrice !== undefined && Number.isFinite(samplePrice) && samplePrice > 0 && samplePrice < 10) {
    return 4;
  }
  return 2;
}

export function daysForTimeframe(tf: string): number {
  return ALL_TIMEFRAMES.find((x) => x.id === tf)?.days ?? 365;
}

/**
 * Human label for an instrument that never repeats the symbol twice.
 * When the provider name is missing, the registry sometimes falls back to the
 * symbol, which used to render as "GC=F · GC=F" during a cold/loading state.
 */
export function instrumentLabel(display: string | null | undefined, symbol: string): string {
  const name = (display ?? '').trim();
  const sym = (symbol ?? '').trim();
  if (!name || name === sym) return sym;
  return `${name} · ${sym}`;
}

/** Poll cadence for the public chart: never faster than the server cache TTL. */
export function publicPollMs(interval: string): number {
  return interval === '1H' ? 60_000 : 300_000;
}

export function groupInstruments(items: MarketInstrument[]): Map<string, MarketInstrument[]> {
  const map = new Map<string, MarketInstrument[]>();
  for (const g of GROUP_ORDER) map.set(g, []);
  for (const inst of items) {
    const key = String(inst.group);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(inst);
  }
  return map;
}

export function quoteBySymbol(items: MarketQuote[]): Map<string, MarketQuote> {
  return new Map(items.map((q) => [q.symbol, q]));
}

export function topGainers(items: MarketQuote[], n = 5): MarketQuote[] {
  return items
    .filter((q) => q.status === 'ok' && q.changePct !== null)
    .sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0))
    .slice(0, n);
}

export function topLosers(items: MarketQuote[], n = 5): MarketQuote[] {
  return items
    .filter((q) => q.status === 'ok' && q.changePct !== null)
    .sort((a, b) => (a.changePct ?? 0) - (b.changePct ?? 0))
    .slice(0, n);
}

export function mostActive(items: MarketQuote[], n = 5): MarketQuote[] {
  return items
    .filter((q) => q.status === 'ok' && q.volume !== null)
    .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
    .slice(0, n);
}

/** Display helpers for movement: color plus a text label for non-color users. */
export function movementDirection(q: MarketQuote): 'up' | 'down' | 'flat' | 'unknown' {
  if (q.status !== 'ok' || q.changePct === null) return 'unknown';
  if (q.changePct > 0) return 'up';
  if (q.changePct < 0) return 'down';
  return 'flat';
}

/** Freshness: how old the latest bar is, in whole days (UTC). */
export function barAgeDays(asOf: string | null): number | null {
  if (!asOf) return null;
  const d = new Date(asOf);
  if (Number.isNaN(d.getTime())) return null;
  const now = Date.now();
  return Math.max(0, Math.floor((now - d.getTime()) / 86_400_000));
}

/** A symbol is stale when its latest bar is older than the expected cadence
 * for its asset class (crypto trades daily; equities skip weekends). */
export function isStale(q: MarketQuote): boolean {
  const age = barAgeDays(q.asOf);
  if (q.status !== 'ok' || age === null) return false;
  if (q.group === 'crypto') return age > 1;
  return age > 4;
}
