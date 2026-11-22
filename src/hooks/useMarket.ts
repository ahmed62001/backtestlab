import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGetDataProviders, apiGetMarketQuotes, apiGetMarketSeries, apiGetMarketUniverse } from '../api';
import { daysForTimeframe } from '../lib/market';
import type { DataProviderInfo, MarketBar, MarketInstrument, MarketQuote, SeriesFreshness, SeriesProvenance } from '../types';

/** Data hooks for the market layer. All errors are surfaced; no fabricated data. */

export function useMarketUniverse() {
  const [items, setItems] = useState<MarketInstrument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    apiGetMarketUniverse()
      .then((res) => setItems(res.items))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  return { items, loading, error, retry: load };
}

export function useMarketQuotes(symbols: string[], options?: { pollMs?: number }) {
  const key = symbols.join(',');
  const pollMs = options?.pollMs ?? 0;
  const [bySymbol, setBySymbol] = useState<Map<string, MarketQuote> | null>(null);
  const [list, setList] = useState<MarketQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [demo, setDemo] = useState(false);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const fetchQuotes = useCallback(
    (silent: boolean) => {
      const syms = key ? key.split(',').filter(Boolean) : [];
      if (syms.length === 0) {
        // No instrument takes part in the watchlist yet (e.g. a page waiting for
        // the universe). Do not call `/market/quotes?symbols=` — the API rejects
        // an empty list with 422 and the console noise is not a real error.
        setBySymbol(new Map());
        setList([]);
        setError(false);
        setLoading(false);
        setGeneratedAt(new Date().toISOString());
        return;
      }
      if (!silent) {
        setLoading(true);
        setError(false);
      }
      // The backend caps quotes at 40 symbols per call; chunk larger
      // watchlists so full-universe pages (90 assets) do not 422.
      const chunks: string[][] = [];
      for (let i = 0; i < syms.length; i += 40) chunks.push(syms.slice(i, i + 40));
      // Progressive: apply each chunk as it lands so the tape/priority assets
      // render immediately while larger universes fill in (provider rate-limit
      // spacing can make a cold full-universe sweep take minutes).
      const promises = chunks.map((c) =>
        apiGetMarketQuotes(c)
          .then((r) => ({ items: r.items, demo: Boolean(r.demo) }))
          .catch(() => ({ items: [] as import('../types').MarketQuote[], demo: false })),
      );
      promises.forEach((p) => {
        void p.then(({ items, demo }) => {
          if (demo) setDemo(true);
          if (items.length === 0) return;
          setBySymbol((prev) => {
            const next = new Map(prev ?? []);
            for (const q of items) next.set(q.symbol, q);
            return next;
          });
          setList((prev) => {
            const bySym = new Map(prev.map((q) => [q.symbol, q]));
            for (const q of items) bySym.set(q.symbol, q);
            return [...bySym.values()];
          });
        });
      });
      Promise.all(promises)
        .then((parts) => {
          const items = parts.flatMap((p) => p.items);
          if (items.length === 0 && syms.length > 0 && !silent) setError(true);
          setGeneratedAt(new Date().toISOString());
        })
        .finally(() => {
          if (!silent) setLoading(false);
        });
    },
    [key],
  );
  const load = useCallback(() => fetchQuotes(false), [fetchQuotes]);
  useEffect(load, [load]);

  useEffect(() => {
    if (!pollMs || pollMs < 5000 || !key) return;
    const id = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      fetchQuotes(true);
    }, pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, key, fetchQuotes]);

  return { quotes: bySymbol, list, loading, error, retry: load, demo, generatedAt };
}

export function useMarketSeries(symbol: string, timeframe: string, options?: { pollMs?: number }) {
  const pollMs = options?.pollMs ?? 0;
  const [bars, setBars] = useState<MarketBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [provider, setProvider] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<SeriesProvenance | null>(null);
  const [freshness, setFreshness] = useState<SeriesFreshness | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Monotonic request id: a response is only applied when it belongs to the
  // newest (symbol, timeframe) selection. Without this, a slow response for
  // the previous asset could overwrite the chart after a fast symbol switch
  // (the classic A -> B -> A stale-response race).
  const reqId = useRef(0);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    if (!symbol) {
      setBars([]);
      setLoading(false);
      setError(false);
      return;
    }
    const id = ++reqId.current;
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    setError(false);
    // Never keep the previous asset's bars visible while a different symbol
    // is being fetched — the chart must not show stale data under a new name.
    setBars([]);
    setProvider(null);
    setProvenance(null);
    setFreshness(null);
    apiGetMarketSeries(symbol, timeframe, daysForTimeframe(timeframe), controller.signal)
      .then((res) => {
        if (!alive || id !== reqId.current) return;
        setBars(res.bars ?? []);
        setProvider(res.provider);
        setProvenance(res.provenance);
        setFreshness(res.freshness ?? null);
      })
      .catch((err: unknown) => {
        if (!alive || id !== reqId.current) return;
        if ((err as { name?: string })?.name === 'AbortError') return;
        setError(true);
      })
      .finally(() => {
        if (!alive || id !== reqId.current) return;
        setLoading(false);
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [symbol, timeframe, reloadKey]);

  // Optional silent background refresh for intraday charts (no loading flash)
  useEffect(() => {
    if (!pollMs || pollMs < 10_000 || !symbol) return;
    let activeController: AbortController | null = null;
    const id = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      const expectedReqId = reqId.current;
      activeController?.abort();
      activeController = new AbortController();
      apiGetMarketSeries(symbol, timeframe, daysForTimeframe(timeframe), activeController.signal)
        .then((res) => {
          if (expectedReqId !== reqId.current) return;
          if (res.bars && res.bars.length > 0) {
            setBars(res.bars);
            setProvider(res.provider);
            setProvenance(res.provenance);
            setFreshness(res.freshness ?? null);
            setError(false);
          }
        })
        .catch(() => {
          /* silent background poll preserves last good bars */
        });
    }, pollMs);
    return () => {
      window.clearInterval(id);
      activeController?.abort();
    };
  }, [pollMs, symbol, timeframe]);

  return { bars, loading, error, retry, provider, provenance, freshness };
}

/** Union of intervals supported by the given providers (catalog-backed). */
export function useProviderIntervals(providerIds: string[]): string[] {
  const [intervals, setIntervals] = useState<string[]>([]);
  const key = providerIds.join(',');
  const reqId = useRef(0);
  useEffect(() => {
    let alive = true;
    apiGetDataProviders()
      .then((list: { items: DataProviderInfo[] }) => {
        if (!alive) return;
        const wanted = key.split(',').filter(Boolean);
        const merged = new Set<string>();
        for (const p of list.items) {
          if (wanted.includes(p.id)) for (const iv of p.intervals) merged.add(iv);
        }
        setIntervals([...merged]);
      })
      .catch(() => {
        if (alive) setIntervals([]);
      });
    return () => {
      alive = false;
      reqId.current += 1;
    };
  }, [key]);
  return intervals;
}
