import { describe, expect, it } from 'vitest';
import { barAgeDays, daysForTimeframe, groupInstruments, instrumentLabel, isStale, mostActive, movementDirection, priceDecimals, publicPollMs, topGainers, topLosers } from './market';
import type { MarketInstrument, MarketQuote } from '../types/market';

function quote(symbol: string, pct: number | null, vol: number | null, asOf: string | null, group = 'stocks'): MarketQuote {
  return {
    symbol,
    display: symbol,
    group,
    status: pct === null && vol === null ? 'unavailable' : 'ok',
    price: pct === null ? null : 100,
    change: pct,
    changePct: pct,
    prevClose: 100,
    dayHigh: 110,
    dayLow: 90,
    volume: vol,
    asOf,
    source: 'yfinance',
    quality: 'eod',
    classification: 'DELAYED' as const,
    transport: 'REST_POLLING' as const,
    errorCode: null,
  };
}

describe('market movers', () => {
  it('sorts gainers desc and losers asc, excluding unavailable', () => {
    const items = [quote('A', 5, 100, null), quote('B', -3, 200, null), quote('C', 9, 50, null), quote('D', null, null, null)];
    expect(topGainers(items).map((q) => q.symbol)).toEqual(['C', 'A', 'B']);
    expect(topLosers(items).map((q) => q.symbol)).toEqual(['B', 'A', 'C']);
    expect(mostActive(items).map((q) => q.symbol)).toEqual(['B', 'A', 'C']);
  });
});

describe('movement direction', () => {
  it('classifies up/down/flat/unknown with a11y text', () => {
    expect(movementDirection(quote('A', 1, 1, null))).toBe('up');
    expect(movementDirection(quote('A', -1, 1, null))).toBe('down');
    expect(movementDirection(quote('A', 0, 1, null))).toBe('flat');
    expect(movementDirection(quote('A', null, null, null))).toBe('unknown');
  });
});

describe('freshness', () => {
  it('flags stale equity quotes older than 4 days', () => {
    const old = new Date(Date.now() - 10 * 86_400_000).toISOString();
    const fresh = new Date(Date.now() - 86_400_000).toISOString();
    expect(isStale(quote('A', 1, 1, old))).toBe(true);
    expect(isStale(quote('A', 1, 1, fresh))).toBe(false);
    expect(isStale(quote('A', 1, 1, old, 'crypto'))).toBe(true);
  });
  it('computes bar age and timeframe days', () => {
    expect(barAgeDays(null)).toBeNull();
    expect(daysForTimeframe('1D')).toBe(365);
    expect(daysForTimeframe('9x')).toBe(365);
  });
});

describe('instrument labels', () => {
  it('never duplicates the symbol when the display name is the symbol', () => {
    expect(instrumentLabel('GC=F', 'GC=F')).toBe('GC=F');
    expect(instrumentLabel('', 'GC=F')).toBe('GC=F');
    expect(instrumentLabel(null, 'GC=F')).toBe('GC=F');
  });
  it('joins name and symbol once otherwise', () => {
    expect(instrumentLabel('Gold futures', 'GC=F')).toBe('Gold futures · GC=F');
  });
  it('keeps public poll cadence at or above the server cache TTL', () => {
    expect(publicPollMs('1H')).toBeGreaterThanOrEqual(60_000);
    expect(publicPollMs('1D')).toBeGreaterThanOrEqual(300_000);
  });
});

describe('grouping', () => {
  it('groups instruments in canonical order', () => {
    const inst = (symbol: string, group: string): MarketInstrument => ({
      symbol,
      display: symbol,
      group,
      assetClass: 'equity',
      quoteCurrency: 'USD',
      baseCurrency: null,
      exchange: 'NASDAQ',
      backtestEligible: true,
      intervals: ['1D'],
      providers: ['yfinance'],
    });
    const map = groupInstruments([inst('GC=F', 'metals'), inst('AAPL', 'stocks')]);
    expect(map.get('metals')?.map((i) => i.symbol)).toEqual(['GC=F']);
    expect(map.get('stocks')?.map((i) => i.symbol)).toEqual(['AAPL']);
  });
});

describe('priceDecimals and intraday lookbacks', () => {
  it('formats FX with 5 decimals (3 for JPY) and equities/gold with 2', () => {
    expect(priceDecimals('EURUSD', 'forex', 1.09678)).toBe(5);
    expect(priceDecimals('GBPUSD', 'fx', 1.30836)).toBe(5);
    expect(priceDecimals('USDJPY', 'forex', 158.557)).toBe(3);
    expect(priceDecimals('XAU/USD', 'metals', 3537.25)).toBe(2);
    expect(priceDecimals('AAPL', 'stocks', 225.5)).toBe(2);
    expect(priceDecimals('NG=F', 'commodities', 3.748)).toBe(4);
  });

  it('uses weekend-safe lookback windows for 1m/5m/15m timeframes', () => {
    expect(daysForTimeframe('1m')).toBeGreaterThanOrEqual(5);
    expect(daysForTimeframe('5m')).toBeGreaterThanOrEqual(7);
    expect(daysForTimeframe('15m')).toBeGreaterThanOrEqual(14);
    expect(daysForTimeframe('1H')).toBe(60);
    expect(daysForTimeframe('4H')).toBe(180);
  });
});
