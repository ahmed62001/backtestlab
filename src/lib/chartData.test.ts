import { describe, expect, it } from 'vitest';
import {
  alignEquitySeries,
  applyTickToBars,
  buildChartRows,
  chartLabel,
  getBucketTimestamp,
  rowBoundary,
} from './chartData';
import type { MarketBar } from '../types/market';
import type { StreamTick } from '../hooks/useMarketStream';

const bar = (t: string, o = 100, h = 105, l = 95, c = 102, v = 10): MarketBar => ({ t, o, h, l, c, v });

describe('buildChartRows', () => {
  it('returns an empty result for empty input (no fake line)', () => {
    expect(buildChartRows([], '1D')).toEqual({ rows: [], received: 0, rejected: 0 });
    expect(buildChartRows(null, '1D').rows).toEqual([]);
  });

  it('drops rows with invalid timestamps or non-finite OHLC values', () => {
    const rows = buildChartRows(
      [
        bar('2026-01-02T00:00:00Z'),
        bar('not-a-date'),
        bar('2026-01-03T00:00:00Z', 100, Number.NaN, 95, 102),
        bar('2026-01-04T00:00:00Z', 100, 105, 95, Number.POSITIVE_INFINITY),
      ],
      '1D',
    );
    expect(rows.received).toBe(4);
    expect(rows.rejected).toBe(3);
    expect(rows.rows).toHaveLength(1);
    expect(rows.rows[0].t).toBe('2026-01-02T00:00:00.000Z');
  });

  it('sorts unsorted input ascending', () => {
    const rows = buildChartRows(
      [bar('2026-01-03T00:00:00Z'), bar('2026-01-01T00:00:00Z'), bar('2026-01-02T00:00:00Z')],
      '1D',
    ).rows;
    expect(rows.map((r) => r.t)).toEqual([
      '2026-01-01T00:00:00.000Z',
      '2026-01-02T00:00:00.000Z',
      '2026-01-03T00:00:00.000Z',
    ]);
  });

  it('keeps the last observation for a duplicate timestamp', () => {
    const rows = buildChartRows(
      [bar('2026-01-02T00:00:00Z', 100, 105, 95, 101), bar('2026-01-02T00:00:00Z', 100, 106, 95, 104)],
      '1D',
    ).rows;
    expect(rows).toHaveLength(1);
    expect(rows[0].c).toBe(104);
  });

  it('rejects an inverted high/low candle instead of plotting an invalid one', () => {
    const result = buildChartRows([bar('2026-01-02T00:00:00Z', 100, 90, 110, 102)], '1D');
    expect(result.rejected).toBe(1);
    expect(result.rows).toHaveLength(0);
  });

  it('labels daily bars in UTC regardless of the host timezone', () => {
    // 00:00Z is the previous day in America/New_York; UTC formatting keeps it stable.
    expect(chartLabel('2026-01-01T00:00:00Z', '1D', 'en')).toBe('Jan 1, 2026');
    expect(chartLabel('2026-03-08T00:00:00Z', '1D', 'en')).toBe('Mar 8, 2026');
    expect(chartLabel('2026-03-09T00:00:00Z', '1D', 'en')).toBe('Mar 9, 2026');
  });

  it('includes the time of day for intraday bars', () => {
    const label = chartLabel('2026-01-01T14:30:00Z', '1H', 'en');
    expect(label).toContain('Jan 1');
    expect(label).toMatch(/14:30/);
  });

  it('reports first/last boundaries of the plotted rows', () => {
    const rows = buildChartRows(
      [bar('2026-01-03T00:00:00Z'), bar('2026-01-01T00:00:00Z')],
      '1D',
    ).rows;
    expect(rowBoundary(rows, 'first')).toBe('2026-01-01T00:00:00.000Z');
    expect(rowBoundary(rows, 'last')).toBe('2026-01-03T00:00:00.000Z');
    expect(rowBoundary([], 'first')).toBeNull();
  });
});

describe('alignEquitySeries', () => {
  const points = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      date: new Date(Date.UTC(2024, 10, 18) + i * 86_400_000).toISOString(),
      strategy: 10_000 + i,
      benchmark: 0,
      drawdown: 0,
    }));

  it('keeps every persisted point of a 499-point curve (no 150-point truncation)', () => {
    const aligned = alignEquitySeries(points(499), points(499));
    expect(aligned.rows).toHaveLength(499);
    expect(aligned.countA).toBe(499);
    expect(aligned.countB).toBe(499);
    expect(aligned.rows[0].a).toBe(10_000);
    expect(aligned.rows[498].a).toBe(10_498);
  });

  it('uses the union of both ranges and leaves true gaps as null', () => {
    const a = [points(2)[0]];
    const b = [points(2)[1]];
    const aligned = alignEquitySeries(a, b);
    expect(aligned.rows).toHaveLength(2);
    expect(aligned.rows[0].b).toBeNull();
    expect(aligned.rows[1].a).toBeNull();
    expect(aligned.first).toBe(a[0].date);
    expect(aligned.last).toBe(b[0].date);
  });

  it('ignores non-finite equity values instead of inventing them', () => {
    const aligned = alignEquitySeries(
      [{ date: '2026-01-01T00:00:00Z', strategy: Number.NaN }],
      [{ date: '2026-01-01T00:00:00Z', strategy: 100 }],
    );
    expect(aligned.countA).toBe(0);
    expect(aligned.rows[0].a).toBeNull();
    expect(aligned.rows[0].b).toBe(100);
  });
});

describe('getBucketTimestamp', () => {
  it('correctly floors timestamps for 1m interval', () => {
    // 2026-11-20T14:32:45.123Z -> 2026-11-20T14:32:00.000Z
    const timeMs = Date.parse('2026-11-20T14:32:45.123Z');
    const bucket = getBucketTimestamp(timeMs, '1m');
    expect(bucket).toBe('2026-11-20T14:32:00.000Z');
  });

  it('correctly floors timestamps for 5m interval', () => {
    // 2026-11-20T14:37:45.123Z -> 2026-11-20T14:35:00.000Z
    const timeMs = Date.parse('2026-11-20T14:37:45.123Z');
    const bucket = getBucketTimestamp(timeMs, '5m');
    expect(bucket).toBe('2026-11-20T14:35:00.000Z');
  });

  it('correctly floors timestamps for 1H interval', () => {
    // 2026-11-20T14:45:00.000Z -> 2026-11-20T14:00:00.000Z
    const timeMs = Date.parse('2026-11-20T14:45:00.000Z');
    const bucket = getBucketTimestamp(timeMs, '1H');
    expect(bucket).toBe('2026-11-20T14:00:00.000Z');
  });

  it('correctly floors timestamps for 1D interval in UTC', () => {
    // 2026-11-20T23:59:59.000Z -> 2026-11-20T00:00:00.000Z
    const timeMs = Date.parse('2026-11-20T23:59:59.000Z');
    const bucket = getBucketTimestamp(timeMs, '1D');
    expect(bucket).toBe('2026-11-20T00:00:00.000Z');
  });
});

describe('applyTickToBars', () => {
  const tick = (price: number, providerTimestamp: string): StreamTick => ({
    symbol: 'AAPL',
    price,
    currency: 'USD',
    exchange: 'NASDAQ',
    source: 'twelvedata',
    providerTimestamp,
    receivedAt: providerTimestamp,
  });

  it('handles empty or null bars correctly', () => {
    expect(applyTickToBars([], undefined, '1D')).toEqual([]);
    expect(applyTickToBars(null, undefined, '1D')).toEqual([]);

    // When valid tick arrives with empty bars, initializes first active candle
    const res = applyTickToBars([], tick(150, '2026-11-20T15:00:00Z'), '1D');
    expect(res).toHaveLength(1);
    expect(res[0].c).toBe(150);
    expect(res[0].o).toBe(150);
    expect(res[0].v).toBe(0);
  });

  it('ignores tick if tick price is invalid or non-positive', () => {
    const bars: MarketBar[] = [bar('2026-11-20T00:00:00Z', 100, 105, 95, 102, 500)];
    const result = applyTickToBars(bars, tick(Number.NaN, '2026-11-20T15:00:00Z'), '1D');
    expect(result).toEqual(bars);

    const result2 = applyTickToBars(bars, tick(-10, '2026-11-20T15:00:00Z'), '1D');
    expect(result2).toEqual(bars);
  });

  it('updates current active candle close, expands high/low, and preserves open & volume', () => {
    const bars: MarketBar[] = [
      bar('2026-11-19T00:00:00.000Z', 90, 95, 88, 92, 1000),
      bar('2026-11-20T00:00:00.000Z', 100, 105, 95, 102, 500),
    ];

    // Tick higher than current high
    const higherTick = tick(109, '2026-11-20T15:30:00.000Z');
    const res1 = applyTickToBars(bars, higherTick, '1D');
    expect(res1).toHaveLength(2);
    expect(res1[0]).toEqual(bars[0]); // Historical bar preserved
    expect(res1[1].o).toBe(100);       // Open preserved
    expect(res1[1].h).toBe(109);       // High expanded to 109
    expect(res1[1].l).toBe(95);        // Low unchanged
    expect(res1[1].c).toBe(109);       // Close updated to 109
    expect(res1[1].v).toBe(500);       // Volume preserved (never corrupted with day_volume)

    // Subsequent tick lower than current low
    const lowerTick = tick(91, '2026-11-20T15:35:00.000Z');
    const res2 = applyTickToBars(res1, lowerTick, '1D');
    expect(res2[1].o).toBe(100);
    expect(res2[1].h).toBe(109);
    expect(res2[1].l).toBe(91);        // Low expanded to 91
    expect(res2[1].c).toBe(91);
    expect(res2[1].v).toBe(500);
  });

  it('rolls over and appends a new candle when tick falls into a new interval bucket', () => {
    const bars: MarketBar[] = [
      bar('2026-11-20T14:00:00.000Z', 100, 105, 95, 102, 500),
    ];

    // New 1H bar at 15:00
    const newBarTick = tick(107.5, '2026-11-20T15:05:00.000Z');
    const result = applyTickToBars(bars, newBarTick, '1H');

    expect(result).toHaveLength(2);
    expect(result[0]).toEqual(bars[0]); // Previous candle completed and unchanged
    const newCandle = result[1];
    expect(newCandle.t).toBe('2026-11-20T15:00:00.000Z');
    expect(newCandle.o).toBe(107.5);
    expect(newCandle.h).toBe(107.5);
    expect(newCandle.l).toBe(107.5);
    expect(newCandle.c).toBe(107.5);
    expect(newCandle.v).toBe(0); // Live volume initialized to 0, not fabricated
  });

  it('safely rejects out-of-order historical ticks', () => {
    const bars: MarketBar[] = [
      bar('2026-11-20T14:00:00.000Z', 100, 105, 95, 102, 500),
      bar('2026-11-20T15:00:00.000Z', 102, 106, 101, 104, 300),
    ];

    // Out-of-order tick from 14:30 when current active candle is 15:00
    const staleTick = tick(99, '2026-11-20T14:30:00.000Z');
    const result = applyTickToBars(bars, staleTick, '1H');
    expect(result).toEqual(bars);
  });
});
