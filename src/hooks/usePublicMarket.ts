import { useCallback, useEffect, useRef, useState } from 'react';
import {
  apiGetPublicMarketInstruments,
  apiGetPublicMarketSeries,
  type PublicMarketError,
} from '../api';
import { publicPollMs } from '../lib/market';
import type { PublicMarketInstrument, PublicSeriesResponse } from '../types';

/** Public, pre-login market data. No auth header is ever attached. */

function asPublicError(e: unknown): PublicMarketError {
  if (e instanceof Error && typeof (e as Partial<PublicMarketError>).code === 'string') {
    return e as PublicMarketError;
  }
  const err = new Error(e instanceof Error ? e.message : 'request failed') as PublicMarketError;
  err.code = 'request_failed';
  err.retryable = false;
  err.status = 0;
  return err;
}

export function usePublicMarketInstruments() {
  const [items, setItems] = useState<PublicMarketInstrument[]>([]);
  const [defaultSymbol, setDefaultSymbol] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<PublicMarketError | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    apiGetPublicMarketInstruments(ctrl.signal)
      .then((res) => {
        setItems(res.items ?? []);
        setDefaultSymbol(res.defaultSymbol ?? res.items?.[0]?.symbol ?? null);
        setProvider(res.provider ?? null);
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setError(asPublicError(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load]);

  return { items, defaultSymbol, provider, loading, error, retry: load };
}

export function usePublicMarketSeries(symbol: string, interval: string) {
  const [data, setData] = useState<PublicSeriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<PublicMarketError | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inflightRef = useRef(false);

  const fetchSeries = useCallback(
    (background = false) => {
      if (!symbol || !interval) return;
      if (background && inflightRef.current) return;
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      inflightRef.current = true;
      if (!background) {
        setLoading(true);
        setError(null);
      }
      apiGetPublicMarketSeries(symbol, interval, 250, ctrl.signal)
        .then((res) => {
          setData(res);
          setError(null);
        })
        .catch((e) => {
          if (ctrl.signal.aborted) return;
          const err = asPublicError(e);
          if (!background) setError(err);
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setLoading(false);
          inflightRef.current = false;
        });
    },
    [symbol, interval],
  );

  // Foreground load whenever the selection changes. The abort controller makes
  // sure a slower response for the previous instrument can never overwrite the
  // newer selection.
  useEffect(() => {
    setData(null);
    fetchSeries(false);
    return () => abortRef.current?.abort();
  }, [fetchSeries]);

  // Poll no faster than the server cache TTL and only while the tab is visible.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const tick = () => {
      if (document.visibilityState === 'visible') fetchSeries(true);
    };
    const id = window.setInterval(tick, publicPollMs(interval));
    const onVisible = () => {
      if (document.visibilityState === 'visible') fetchSeries(true);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [fetchSeries, interval]);

  return { data, loading, error, retry: () => fetchSeries(false) };
}
