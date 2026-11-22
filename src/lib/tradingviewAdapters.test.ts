import { describe, expect, it } from 'vitest';
import { lightTokens } from './tokens';
import {
  toUTCTimestamp,
  barsToCandlestickData,
  barsToLineData,
  barsToVolumeData,
  equityToLineData,
  alignedToSeriesData,
  tradesToMarkers,
  macroToLineData,
} from './tradingviewAdapters';
import type { MarketBar } from '../types/market';
import type { EquityPointLike, AlignedEquityRow } from './chartData';
import type { Trade } from '../types/backtest';

describe('tradingviewAdapters', () => {
  describe('toUTCTimestamp', () => {
    it('converts an ISO string to UTC seconds', () => {
      const ts = toUTCTimestamp('2026-03-01T00:00:00Z');
      expect(ts).toBe(1772323200);
    });

    it('converts a Date instance', () => {
      const d = new Date('2026-03-01T12:00:00Z');
      const ts = toUTCTimestamp(d);
      expect(ts).toBe(1772366400);
    });

    it('returns null on invalid date strings', () => {
      expect(toUTCTimestamp('invalid')).toBeNull();
    });
  });

  describe('barsToCandlestickData', () => {
    it('normalizes, deduplicates, and sorts bars ascending by time', () => {
      const bars: MarketBar[] = [
        { t: '2026-03-02T00:00:00Z', o: 105, h: 110, l: 104, c: 108, v: 500 },
        { t: '2026-03-01T00:00:00Z', o: 100, h: 106, l: 98, c: 105, v: 400 },
        // duplicate of 2026-03-02 (keeps last)
        { t: '2026-03-02T00:00:00Z', o: 105, h: 112, l: 104, c: 109, v: 600 },
      ];

      const candles = barsToCandlestickData(bars);
      expect(candles).toHaveLength(2);
      expect(candles[0].time).toBe(1772323200);
      expect(candles[0].open).toBe(100);
      expect(candles[0].close).toBe(105);

      expect(candles[1].time).toBe(1772409600);
      expect(candles[1].close).toBe(109);
      expect(candles[1].high).toBe(112);
    });

    it('filters out invalid or corrupt OHLC values', () => {
      const bars: MarketBar[] = [
        { t: '2026-03-01T00:00:00Z', o: 100, h: 105, l: 95, c: 102, v: 100 },
        { t: '2026-03-02T00:00:00Z', o: NaN, h: 105, l: 95, c: 102, v: 100 },
        { t: '2026-03-03T00:00:00Z', o: 100, h: 90, l: 105, c: 102, v: 100 }, // inverted h < l
      ];

      const candles = barsToCandlestickData(bars);
      expect(candles).toHaveLength(1);
      expect(candles[0].open).toBe(100);
    });

    it('returns empty array on empty or null input', () => {
      expect(barsToCandlestickData(null)).toEqual([]);
      expect(barsToCandlestickData([])).toEqual([]);
    });
  });

  describe('barsToLineData', () => {
    it('converts bars to close values with timestamps', () => {
      const bars: MarketBar[] = [
        { t: '2026-03-01T00:00:00Z', o: 100, h: 105, l: 95, c: 103, v: 100 },
        { t: '2026-03-02T00:00:00Z', o: 103, h: 108, l: 102, c: 107, v: 150 },
      ];

      const line = barsToLineData(bars);
      expect(line).toHaveLength(2);
      expect(line[0].value).toBe(103);
      expect(line[1].value).toBe(107);
    });
  });

  describe('barsToVolumeData', () => {
    it('assigns gain color to up bars and loss color to down bars', () => {
      const bars: MarketBar[] = [
        { t: '2026-03-01T00:00:00Z', o: 100, h: 105, l: 95, c: 103, v: 1000 }, // up
        { t: '2026-03-02T00:00:00Z', o: 103, h: 104, l: 98, c: 99, v: 1500 }, // down
      ];

      const vol = barsToVolumeData(bars, lightTokens.gain, lightTokens.loss);
      expect(vol).toHaveLength(2);
      expect(vol[0].value).toBe(1000);
      expect(vol[0].color).toBe(lightTokens.gain);
      expect(vol[1].value).toBe(1500);
      expect(vol[1].color).toBe(lightTokens.loss);
    });
  });

  describe('equityToLineData', () => {
    it('extracts strategy, benchmark, and drawdown curves', () => {
      const points: EquityPointLike[] = [
        { date: '2026-03-01T00:00:00Z', strategy: 10000, benchmark: 10000, drawdown: 0 },
        { date: '2026-03-02T00:00:00Z', strategy: 10500, benchmark: 10100, drawdown: 0 },
        { date: '2026-03-03T00:00:00Z', strategy: 10200, benchmark: 10050, drawdown: -2.86 },
      ];

      const strat = equityToLineData(points, 'strategy');
      expect(strat).toHaveLength(3);
      expect(strat[1].value).toBe(10500);

      const dd = equityToLineData(points, 'drawdown');
      expect(dd).toHaveLength(3);
      expect(dd[2].value).toBe(-2.86);
    });
  });

  describe('alignedToSeriesData', () => {
    it('preserves null gaps as WhitespaceData without interpolating values', () => {
      const rows: AlignedEquityRow[] = [
        { date: '2026-03-01T00:00:00Z', a: 100, b: 200 },
        { date: '2026-03-02T00:00:00Z', a: null, b: 205 }, // gap in series A
        { date: '2026-03-03T00:00:00Z', a: 108, b: 210 },
      ];

      const seriesA = alignedToSeriesData(rows, 'a');
      expect(seriesA).toHaveLength(3);
      expect('value' in seriesA[0]).toBe(true);
      expect('value' in seriesA[1]).toBe(false); // WhitespaceData gap
      expect('value' in seriesA[2]).toBe(true);
    });
  });

  describe('tradesToMarkers', () => {
    it('creates arrowUp belowBar for buys and arrowDown aboveBar for sells', () => {
      const trades: Trade[] = [
        { id: '1', date: '2026-03-01T10:00:00Z', side: 'buy', price: 100, qty: 10, pnl: null, returnPct: null },
        { id: '2', date: '2026-03-02T15:00:00Z', side: 'sell', price: 110, qty: 10, pnl: 100, returnPct: 10 },
      ];

      const markers = tradesToMarkers(trades, lightTokens.gain, lightTokens.loss);
      expect(markers).toHaveLength(2);
      expect(markers[0].position).toBe('belowBar');
      expect(markers[0].shape).toBe('arrowUp');
      expect(markers[0].color).toBe(lightTokens.gain);
      expect(markers[0].text).toContain('BUY @ 100.00');

      expect(markers[1].position).toBe('aboveBar');
      expect(markers[1].shape).toBe('arrowDown');
      expect(markers[1].color).toBe(lightTokens.loss);
      expect(markers[1].text).toContain('SELL @ 110.00 (+10.0%)');
    });
  });

  describe('macroToLineData', () => {
    it('extracts valid macroeconomic observations', () => {
      const obs = [
        { date: '2026-01-01', value: 4.5 },
        { date: '2026-02-01', value: null },
        { date: '2026-03-01', value: 4.25 },
      ];

      const data = macroToLineData(obs);
      expect(data).toHaveLength(2);
      expect(data[0].value).toBe(4.5);
      expect(data[1].value).toBe(4.25);
    });
  });
});
