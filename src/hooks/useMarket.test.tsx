import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act } from 'react';
import { useMarketQuotes, useMarketSeries } from './useMarket';
import { render } from '../test/render';
import type { MarketBar } from '../types';

const apiGetMarketQuotes = vi.fn();
const apiGetMarketSeries = vi.fn();
vi.mock('../api', () => ({
  apiGetMarketQuotes: (...args: unknown[]) => apiGetMarketQuotes(...args),
  apiGetMarketUniverse: vi.fn(),
  apiGetMarketSeries: (...args: unknown[]) => apiGetMarketSeries(...args),
  apiGetDataProviders: vi.fn(),
}));

function Probe({ symbols }: { symbols: string[] }) {
  const state = useMarketQuotes(symbols);
  return (
    <span>
      {state.loading ? 'loading' : 'ready'}:{state.list.length}:{state.error ? 'error' : 'ok'}
    </span>
  );
}

function SeriesProbe({ symbol, timeframe }: { symbol: string; timeframe: string }) {
  const state = useMarketSeries(symbol, timeframe);
  return (
    <span>
      {state.loading ? 'loading' : 'ready'}:{state.bars.map((b) => b.c).join(',')}:
      {state.error ? 'error' : 'ok'}
    </span>
  );
}

const bar = (c: number): MarketBar => ({ t: '2026-01-02T00:00:00Z', o: c, h: c, l: c, c, v: 1 });

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe('useMarketQuotes', () => {
  beforeEach(() => {
    apiGetMarketQuotes.mockReset();
  });

  it('does not request quotes for an empty watchlist (avoids 422 noise)', () => {
    const view = render(<Probe symbols={[]} />);
    expect(apiGetMarketQuotes).not.toHaveBeenCalled();
    expect(view.text()).toBe('ready:0:ok');
    view.unmount();
  });

  it('requests quotes once a watchlist exists', () => {
    apiGetMarketQuotes.mockResolvedValue({ items: [], demo: false });
    const view = render(<Probe symbols={['AAPL']} />);
    expect(apiGetMarketQuotes).toHaveBeenCalledWith(['AAPL']);
    view.unmount();
  });
});

describe('useMarketSeries stale-response guard', () => {
  beforeEach(() => {
    apiGetMarketSeries.mockReset();
  });

  it('never lets a late response for the previous symbol overwrite the new one', async () => {
    const slowA = deferred<{ bars: MarketBar[]; provider: string; provenance: object }>();
    const fastB = deferred<{ bars: MarketBar[]; provider: string; provenance: object }>();
    apiGetMarketSeries.mockImplementation((symbol: string) =>
      symbol === 'AAPL' ? slowA.promise : fastB.promise,
    );

    const view = render(<SeriesProbe symbol="AAPL" timeframe="1D" />);
    // Rapid switch A -> B before A resolves.
    view.rerender(<SeriesProbe symbol="BTC-USD" timeframe="1D" />);

    await act(async () => {
      fastB.resolve({ bars: [bar(200)], provider: 'yfinance', provenance: {} });
      await fastB.promise;
    });
    expect(view.text()).toContain('200');

    // The stale A response arrives afterwards and must be discarded.
    await act(async () => {
      slowA.resolve({ bars: [bar(100)], provider: 'yfinance', provenance: {} });
      await slowA.promise;
    });
    expect(view.text()).toContain('200');
    expect(view.text()).not.toContain('100');
    view.unmount();
  });

  it('clears the previous asset immediately on symbol change', async () => {
    apiGetMarketSeries.mockResolvedValueOnce({ bars: [bar(100)], provider: 'yfinance', provenance: {} });
    const view = render(<SeriesProbe symbol="AAPL" timeframe="1D" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(view.text()).toContain('100');

    const pending = deferred<{ bars: MarketBar[]; provider: string; provenance: object }>();
    apiGetMarketSeries.mockImplementation(() => pending.promise);
    view.rerender(<SeriesProbe symbol="BTC-USD" timeframe="1D" />);
    // Loading state must not display AAPL's bars under the BTC-USD selection.
    expect(view.text()).toContain('loading');
    expect(view.text()).not.toContain('100');
    view.unmount();
  });
});
