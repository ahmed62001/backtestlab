import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
import { render } from '../../test/render';
import type { PublicMarketInstrumentsResponse, PublicSeriesResponse } from '../../types';
import type { PublicMarketError } from '../../api';

const state = vi.hoisted(() => ({
  instruments: {} as Record<string, unknown>,
  series: {} as Record<string, unknown>,
}));

vi.mock('../../hooks/usePublicMarket', () => ({
  usePublicMarketInstruments: () => state.instruments,
  usePublicMarketSeries: () => state.series,
}));

vi.mock('./PriceChart', () => ({
  PriceChart: (props: { bars: unknown[]; showTimeframes?: boolean }) => (
    <div data-testid="price-chart" data-bars={props.bars.length} data-show-tf={String(props.showTimeframes)} />
  ),
}));

import { PublicMarketChart } from './PublicMarketChart';

const instruments: PublicMarketInstrumentsResponse = {
  items: [
    { symbol: 'GC=F', displayName: 'Gold futures', assetClass: 'commodity', currency: 'USD', intervals: ['1D', '1H'] },
    { symbol: 'AAPL', displayName: 'Apple Inc.', assetClass: 'equity', currency: 'USD', intervals: ['1D'] },
  ],
  defaultSymbol: 'GC=F',
  provider: 'yfinance',
};

function series(overrides: Partial<PublicSeriesResponse> = {}): PublicSeriesResponse {
  return {
    symbol: 'GC=F',
    displayName: 'Gold futures',
    assetClass: 'commodity',
    currency: 'USD',
    provider: 'yfinance',
    interval: '1D',
    candles: [
      { t: '2026-11-14T00:00:00+00:00', o: 100, h: 110, l: 99, c: 105, v: 1000 },
      { t: '2026-11-15T00:00:00+00:00', o: 105, h: 112, l: 104, c: 110, v: 1200 },
    ],
    lastCandleTime: '2026-11-15T00:00:00+00:00',
    retrievedAt: '2026-11-16T00:00:00+00:00',
    dataStatus: 'delayed',
    cacheAgeSeconds: 0,
    ...overrides,
  };
}

function apiError(overrides: Partial<PublicMarketError> = {}): PublicMarketError {
  const e = new Error('boom') as PublicMarketError;
  e.code = 'UPSTREAM_UNAVAILABLE';
  e.retryable = true;
  e.status = 503;
  return Object.assign(e, overrides);
}

function baseHooks(overrides: {
  instruments?: Partial<Record<string, unknown>>;
  series?: Partial<Record<string, unknown>>;
} = {}) {
  state.instruments = {
    items: instruments.items,
    defaultSymbol: 'GC=F',
    provider: 'yfinance',
    loading: false,
    error: null,
    retry: vi.fn(),
    ...overrides.instruments,
  };
  state.series = {
    data: series(),
    loading: false,
    error: null,
    retry: vi.fn(),
    ...overrides.series,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  baseHooks();
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('PublicMarketChart states', () => {
  it('renders real candle count and a truthful delayed badge', () => {
    const r = render(<PublicMarketChart />);
    const chart = r.container.querySelector('[data-testid="price-chart"]');
    expect(chart?.getAttribute('data-bars')).toBe('2');
    expect(chart?.getAttribute('data-show-tf')).toBe('false');
    expect(r.text()).toContain('Gold futures');
    expect(r.text()).toContain('Delayed / end-of-day');
    expect(r.text()).toContain('yfinance');
    r.unmount();
  });

  it('shows a loading skeleton without claiming data', () => {
    baseHooks({ series: { data: null, loading: true } });
    const r = render(<PublicMarketChart />);
    expect(r.container.querySelector('[data-testid="price-chart"]')).toBeNull();
    expect(r.text()).not.toContain('Delayed / end-of-day');
    r.unmount();
  });

  it('distinguishes a provider failure from an application error', () => {
    baseHooks({ series: { data: null, loading: false, error: apiError() } });
    const r = render(<PublicMarketChart />);
    expect(r.text()).toContain('provider is temporarily unavailable');
    expect(r.text()).toContain('UPSTREAM_UNAVAILABLE');
    r.unmount();
  });

  it('renders a rate-limit message with the wait time and retry', () => {
    baseHooks({
      series: {
        data: null,
        loading: false,
        error: apiError({ code: 'RATE_LIMITED', status: 429, retryAfterSeconds: 42 }),
      },
    });
    const r = render(<PublicMarketChart />);
    expect(r.text()).toContain('42');
    expect(r.text().toLowerCase()).toContain('retry');
    r.unmount();
  });

  it('marks invalid public input distinctly', () => {
    baseHooks({
      series: { data: null, loading: false, error: apiError({ code: 'UNKNOWN_SYMBOL', status: 404 }) },
    });
    const r = render(<PublicMarketChart />);
    expect(r.text()).toContain('not available on the public chart');
    r.unmount();
  });

  it('shows an empty state with a retry action when no candles are returned', () => {
    baseHooks({ series: { data: series({ candles: [], lastCandleTime: null }) } });
    const r = render(<PublicMarketChart />);
    expect(r.text()).toContain('No candles were returned');
    expect(r.text().toLowerCase()).toContain('retry');
    expect(r.container.querySelector('[data-testid="price-chart"]')).toBeNull();
    r.unmount();
  });

  it('labels stale data with the stale timestamp', () => {
    baseHooks({
      series: {
        data: series({
          dataStatus: 'stale',
          cacheAgeSeconds: 400,
          staleSince: '2026-11-15T00:00:00+00:00',
        }),
      },
    });
    const r = render(<PublicMarketChart />);
    expect(r.text()).toContain('Stale since');
    expect(r.text()).toContain('Showing last known data');
    r.unmount();
  });

  it('does not duplicate the symbol when the display name equals the symbol', () => {
    baseHooks({
      series: { data: series({ displayName: 'GC=F' }) },
    });
    const r = render(<PublicMarketChart />);
    expect(r.text()).not.toContain('GC=F · GC=F');
    r.unmount();
  });
});
