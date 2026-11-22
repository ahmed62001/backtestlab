import type {
  CandlestickData,
  HistogramData,
  LineData,
  SeriesMarker,
  UTCTimestamp,
  WhitespaceData,
} from 'lightweight-charts';
import type { MarketBar } from '../types/market';
import type { Trade } from '../types/backtest';
import type { EquityPointLike, AlignedEquityRow } from './chartData';

/**
 * Convert any valid ISO timestamp, epoch milliseconds, or Date to a TradingView UTCTimestamp (seconds).
 */
export function toUTCTimestamp(ts: string | number | Date): UTCTimestamp | null {
  const d = ts instanceof Date ? ts : new Date(ts);
  const ms = d.getTime();
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000) as UTCTimestamp;
}

function finite(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * Convert MarketBar[] to strictly ascending, validated CandlestickData for TradingView.
 * Ensures open, high, low, close are valid numbers, high >= max(open, close),
 * and low <= min(open, close). Deduplicates identical timestamps (keeps last).
 */
export function barsToCandlestickData(
  bars: readonly MarketBar[] | null | undefined,
): CandlestickData<UTCTimestamp>[] {
  if (!bars || bars.length === 0) return [];

  const byTime = new Map<UTCTimestamp, CandlestickData<UTCTimestamp>>();
  for (const b of bars) {
    const time = toUTCTimestamp(b.t);
    if (time === null || !finite(b.o) || !finite(b.h) || !finite(b.l) || !finite(b.c)) {
      continue;
    }
    if (b.h < b.l) continue;
    const high = Math.max(b.h, b.o, b.c);
    const low = Math.min(b.l, b.o, b.c);
    byTime.set(time, {
      time,
      open: b.o,
      high,
      low,
      close: b.c,
    });
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert MarketBar[] to LineData for line/area chart mode.
 */
export function barsToLineData(
  bars: readonly MarketBar[] | null | undefined,
): LineData<UTCTimestamp>[] {
  if (!bars || bars.length === 0) return [];

  const byTime = new Map<UTCTimestamp, LineData<UTCTimestamp>>();
  for (const b of bars) {
    const time = toUTCTimestamp(b.t);
    if (time === null || !finite(b.c)) continue;
    byTime.set(time, {
      time,
      value: b.c,
    });
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert MarketBar[] to HistogramData for volume histogram.
 */
export function barsToVolumeData(
  bars: readonly MarketBar[] | null | undefined,
  gainColor: string,
  lossColor: string,
): HistogramData<UTCTimestamp>[] {
  if (!bars || bars.length === 0) return [];

  const byTime = new Map<UTCTimestamp, HistogramData<UTCTimestamp>>();
  for (const b of bars) {
    const time = toUTCTimestamp(b.t);
    if (time === null) continue;
    const vol = finite(b.v) ? Math.max(0, b.v) : 0;
    const isUp = b.c >= b.o;
    byTime.set(time, {
      time,
      value: vol,
      color: isUp ? gainColor : lossColor,
    });
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert backtest EquityPoint[] to LineData for strategy, benchmark, or drawdown.
 */
export function equityToLineData(
  points: readonly EquityPointLike[] | null | undefined,
  field: 'strategy' | 'benchmark' | 'drawdown',
): LineData<UTCTimestamp>[] {
  if (!points || points.length === 0) return [];

  const byTime = new Map<UTCTimestamp, LineData<UTCTimestamp>>();
  for (const p of points) {
    const time = toUTCTimestamp(p.date);
    if (time === null) continue;
    const val = p[field];
    if (!finite(val)) continue;
    byTime.set(time, {
      time,
      value: val,
    });
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert aligned equity comparison rows to TradingView series data.
 * When a value is null, whitespace data is emitted to preserve real gaps.
 */
export function alignedToSeriesData(
  rows: readonly AlignedEquityRow[] | null | undefined,
  seriesKey: 'a' | 'b',
): (LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] {
  if (!rows || rows.length === 0) return [];

  const byTime = new Map<UTCTimestamp, LineData<UTCTimestamp> | WhitespaceData<UTCTimestamp>>();
  for (const r of rows) {
    const time = toUTCTimestamp(r.date);
    if (time === null) continue;
    const val = r[seriesKey];
    if (val !== null && finite(val)) {
      byTime.set(time, { time, value: val });
    } else {
      byTime.set(time, { time });
    }
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert backtest trades to TradingView series markers.
 */
export function tradesToMarkers(
  trades: readonly Trade[] | null | undefined,
  gainColor: string,
  lossColor: string,
): SeriesMarker<UTCTimestamp>[] {
  if (!trades || trades.length === 0) return [];

  const markers: SeriesMarker<UTCTimestamp>[] = [];
  for (const tr of trades) {
    const time = toUTCTimestamp(tr.date);
    if (time === null) continue;
    const isBuy = tr.side === 'buy';
    const color = isBuy ? gainColor : lossColor;
    const position = isBuy ? 'belowBar' : 'aboveBar';
    const shape = isBuy ? 'arrowUp' : 'arrowDown';
    const label = isBuy
      ? `BUY @ ${tr.price.toFixed(2)}`
      : `SELL @ ${tr.price.toFixed(2)}${tr.returnPct != null ? ` (${tr.returnPct > 0 ? '+' : ''}${tr.returnPct.toFixed(1)}%)` : ''}`;

    markers.push({
      time,
      position,
      color,
      shape,
      text: label,
    });
  }

  // TradingView markers must be sorted ascending by time
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

/**
 * Convert macro observations ({ date: string, value: number | null }) to LineData.
 */
export function macroToLineData(
  observations: readonly { date: string; value: number | null }[] | null | undefined,
): LineData<UTCTimestamp>[] {
  if (!observations || observations.length === 0) return [];

  const byTime = new Map<UTCTimestamp, LineData<UTCTimestamp>>();
  for (const o of observations) {
    const time = toUTCTimestamp(o.date);
    if (time === null || o.value === null || !finite(o.value)) continue;
    byTime.set(time, {
      time,
      value: o.value,
    });
  }

  return [...byTime.values()].sort((a, b) => (a.time as number) - (b.time as number));
}
