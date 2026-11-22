import type { MarketBar } from '../types/market';
import type { StreamTick } from '../hooks/useMarketStream';
import type { AppLang } from './format';
import { NUMBERING_SYSTEM } from './format';

/**
 * Chart data transformation shared by every price chart.
 *
 * These are pure functions so the same rows object is used both for the
 * plotted series and for the `data-*` readiness attributes. That is the
 * single-source-of-truth requirement of the chart readiness contract: the
 * attributes can never disagree with what Recharts receives.
 */

export interface ChartRow extends MarketBar {
  label: string;
  priceRange: [number, number];
}

export interface ChartRowsResult {
  /** Valid, sorted, de-duplicated rows actually bound to the chart. */
  rows: ChartRow[];
  /** Rows present in the API payload. */
  received: number;
  /** Rows rejected because a timestamp or OHLC value was invalid. */
  rejected: number;
}

/** Intraday intervals get a time-of-day label; daily+ keep the date only. */
export function isIntradayInterval(interval: string): boolean {
  return /^\d+m$/.test(interval) || /^\d+H$/.test(interval);
}

function localeFor(lang: AppLang): string {
  // Intl numbering system keeps Western digits, matching the rest of the app.
  return `${lang === 'ar' ? 'ar' : 'en'}-u-nu-${NUMBERING_SYSTEM}`;
}

/**
 * Format a market timestamp in **UTC**.
 *
 * Market bars are stored as UTC instants. Formatting them in the browser's
 * local zone shifts a 00:00Z daily bar to the previous day west of UTC (and
 * to the next day east of it), which silently mislabels daily charts. Using
 * an explicit `timeZone: 'UTC'` makes the axis identical in every zone and
 * removes the DST sensitivity.
 */
export function chartLabel(
  ts: string | number | Date,
  interval: string,
  lang: AppLang = 'en',
): string {
  const d = ts instanceof Date ? ts : new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  const opts: Intl.DateTimeFormatOptions = isIntradayInterval(interval)
    ? {
        timeZone: 'UTC',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }
    : { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric' };
  return new Intl.DateTimeFormat(localeFor(lang), opts).format(d);
}

function finite(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * Convert API bars into chart rows.
 *
 * - invalid/NaN OHLC rows are dropped (never plotted as fake values)
 * - input is sorted ascending by timestamp
 * - duplicate timestamps keep the last observation (providers repeat the
 *   in-progress candle)
 * - the output order is stable, so `data-first-ts`/`data-last-ts` describe
 *   exactly the plotted series
 */
export function buildChartRows(
  bars: readonly MarketBar[] | null | undefined,
  interval: string,
  lang: AppLang = 'en',
): ChartRowsResult {
  const received = bars ? bars.length : 0;
  let rejected = 0;
  if (!bars || bars.length === 0) return { rows: [], received, rejected };

  const byTs = new Map<number, ChartRow>();
  for (const b of bars) {
    const ms = new Date(b.t).getTime();
    if (!Number.isFinite(ms) || !finite(b.o) || !finite(b.h) || !finite(b.l) || !finite(b.c)) {
      rejected += 1;
      continue;
    }
    // Guard against inverted ranges from a malformed provider payload: keep
    // the row only when its high/low bound the open/close.
    if (b.h < b.l) {
      rejected += 1;
      continue;
    }
    const high = Math.max(b.h, b.o, b.c);
    const low = Math.min(b.l, b.o, b.c);
    byTs.set(ms, {
      ...b,
      t: new Date(ms).toISOString(),
      h: high,
      l: low,
      v: finite(b.v) ? b.v : 0,
      label: chartLabel(ms, interval, lang),
      priceRange: [low, high],
    });
  }
  const rows = [...byTs.values()].sort(
    (a, b) => new Date(a.t).getTime() - new Date(b.t).getTime(),
  );
  return { rows, received, rejected };
}

/** ISO-8601 UTC boundary of the first/last plotted row. */
export function rowBoundary(rows: readonly ChartRow[], edge: 'first' | 'last'): string | null {
  if (rows.length === 0) return null;
  return edge === 'first' ? rows[0].t : rows[rows.length - 1].t;
}

export interface EquityPointLike {
  date: string;
  strategy: number;
  benchmark?: number;
  drawdown?: number;
}

export interface AlignedEquityRow {
  date: string;
  a: number | null;
  b: number | null;
}

export interface AlignedEquity {
  rows: AlignedEquityRow[];
  countA: number;
  countB: number;
  first: string | null;
  last: string | null;
}

function equityKey(date: string): number | null {
  const ms = new Date(date).getTime();
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Align two equity curves on the union of their timestamps.
 *
 * Semantics (Phase 2): the X domain is the union of both series' ranges.
 * Where one run has no observation at a timestamp the value stays `null`
 * (a true gap) — never forward-filled or interpolated, because inventing an
 * equity value would falsify the strategy's actual performance.
 */
export function alignEquitySeries(
  a: readonly EquityPointLike[] | null | undefined,
  b: readonly EquityPointLike[] | null | undefined,
): AlignedEquity {
  const mapA = new Map<number, number>();
  const mapB = new Map<number, number>();
  for (const p of a ?? []) {
    const k = equityKey(p.date);
    if (k !== null && Number.isFinite(p.strategy)) mapA.set(k, p.strategy);
  }
  for (const p of b ?? []) {
    const k = equityKey(p.date);
    if (k !== null && Number.isFinite(p.strategy)) mapB.set(k, p.strategy);
  }
  const keys = [...new Set([...mapA.keys(), ...mapB.keys()])].sort((x, y) => x - y);
  const rows = keys.map((k) => ({
    date: new Date(k).toISOString(),
    a: mapA.has(k) ? (mapA.get(k) as number) : null,
    b: mapB.has(k) ? (mapB.get(k) as number) : null,
  }));
  return {
    rows,
    countA: mapA.size,
    countB: mapB.size,
    first: keys.length ? new Date(keys[0]).toISOString() : null,
    last: keys.length ? new Date(keys[keys.length - 1]).toISOString() : null,
  };
}

/**
 * Given a timestamp and interval, compute the ISO-8601 string representing
 * the start of the interval bucket in UTC.
 */
export function getBucketTimestamp(timeMs: number, interval: string): string {
  const d = new Date(timeMs);
  if (interval === '1m') {
    d.setUTCSeconds(0, 0);
    return d.toISOString();
  }
  if (interval === '5m') {
    const mins = Math.floor(d.getUTCMinutes() / 5) * 5;
    d.setUTCMinutes(mins, 0, 0);
    return d.toISOString();
  }
  if (interval === '15m') {
    const mins = Math.floor(d.getUTCMinutes() / 15) * 15;
    d.setUTCMinutes(mins, 0, 0);
    return d.toISOString();
  }
  if (interval === '30m') {
    const mins = Math.floor(d.getUTCMinutes() / 30) * 30;
    d.setUTCMinutes(mins, 0, 0);
    return d.toISOString();
  }
  if (interval === '1H') {
    d.setUTCMinutes(0, 0, 0);
    return d.toISOString();
  }
  if (interval === '4H') {
    const hours = Math.floor(d.getUTCHours() / 4) * 4;
    d.setUTCHours(hours, 0, 0, 0);
    return d.toISOString();
  }
  if (interval === '1D') {
    d.setUTCHours(0, 0, 0, 0);
    return d.toISOString();
  }
  if (interval === '1W') {
    const day = d.getUTCDay();
    const diff = (day === 0 ? -6 : 1) - day;
    d.setUTCDate(d.getUTCDate() + diff);
    d.setUTCHours(0, 0, 0, 0);
    return d.toISOString();
  }
  if (interval === '1M') {
    d.setUTCDate(1);
    d.setUTCHours(0, 0, 0, 0);
    return d.toISOString();
  }
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString();
}

/**
 * Safely update the latest candle or create a new active candle with a streaming tick.
 * - Preserves candle open
 * - Updates close, high, low
 * - Never fabricates or uses day_volume as bar volume
 * - Drops out-of-order ticks
 * - Prevents duplicate timestamps
 */
export function applyTickToBars(
  bars: readonly MarketBar[] | null | undefined,
  tick: StreamTick | undefined,
  interval: string,
  _assetClass?: string,
): MarketBar[] {
  if (!bars || bars.length === 0) {
    if (!tick || !tick.price || tick.price <= 0) return [];
    const tickTime = new Date(tick.providerTimestamp).getTime();
    if (Number.isNaN(tickTime)) return [];
    const bucketTs = getBucketTimestamp(tickTime, interval);
    return [
      {
        t: bucketTs,
        o: tick.price,
        h: tick.price,
        l: tick.price,
        c: tick.price,
        v: 0,
      },
    ];
  }

  if (!tick || !tick.price || tick.price <= 0 || !tick.providerTimestamp) {
    return [...bars];
  }

  const tickTime = new Date(tick.providerTimestamp).getTime();
  if (Number.isNaN(tickTime)) return [...bars];

  const lastBar = bars[bars.length - 1];
  const lastBarTime = new Date(lastBar.t).getTime();
  if (Number.isNaN(lastBarTime)) return [...bars];

  // Discard ticks older than the last bar timestamp
  if (tickTime < lastBarTime) {
    return [...bars];
  }

  const tickBucket = getBucketTimestamp(tickTime, interval);
  const lastBucket = getBucketTimestamp(lastBarTime, interval);

  const tickBucketTime = new Date(tickBucket).getTime();
  const lastBucketTime = new Date(lastBucket).getTime();

  if (tickBucketTime === lastBucketTime) {
    // Same bucket: update the active candle
    const updatedLast: MarketBar = {
      ...lastBar,
      c: tick.price,
      h: Math.max(lastBar.h, tick.price),
      l: Math.min(lastBar.l, tick.price),
      // open is preserved
      // volume is preserved (never overwrite with day_volume or fake volume)
    };
    return [...bars.slice(0, -1), updatedLast];
  }

  if (tickBucketTime > lastBucketTime) {
    // New bucket started: previous candle is now complete, form a new active candle
    const newCandle: MarketBar = {
      t: tickBucket,
      o: tick.price,
      h: tick.price,
      l: tick.price,
      c: tick.price,
      v: 0, // volume integrity: live candle volume is 0/unavailable until closed
    };
    return [...bars, newCandle];
  }

  return [...bars];
}
