import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { apiGetMarketQuotes } from '../../api';
import { TAPE_STREAM_SYMBOLS, TAPE_SYMBOLS, movementDirection, priceDecimals, quoteBySymbol } from '../../lib/market';
import { useStreamedQuotes } from '../../hooks/useMarketStream';
import { formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import type { MarketQuote } from '../../types/market';
import { Skeleton } from '../ui';

/**
 * Secondary compact asset navigation bar: the ticker tape.
 * Horizontal scrolling, RTL-aware (scrolls from inline-start), shows the
 * latest available price per instrument with green/red movement indicators
 * plus accessible text labels. Items with no data show "—" and a
 * "unavailable" label — never fabricated prices.
 */
export function TickerTape() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const [quotes, setQuotes] = useState<Map<string, MarketQuote> | null>(null);
  const [demo, setDemo] = useState(false);
  const { liveTicks } = useStreamedQuotes([...TAPE_STREAM_SYMBOLS]);

  useEffect(() => {
    let alive = true;
    const load = () => {
      apiGetMarketQuotes([...TAPE_SYMBOLS])
        .then((res) => {
          if (!alive) return;
          setQuotes(quoteBySymbol(res.items));
          setDemo(Boolean(res.demo));
        })
        .catch(() => {
          if (alive) setQuotes((prev) => prev ?? new Map());
        });
    };
    load();
    const id = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      load();
    }, 45_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div
      className="border-t border-line/60 bg-surface/50 backdrop-blur-sm"
      role="region"
      aria-label={t('market.tapeLabel')}
      data-testid="ticker-tape"
    >
      <div className="tape-scroll mx-auto flex max-w-shell items-center gap-1.5 overflow-x-auto px-4 py-1.5 sm:px-6">
        {demo && (
          <span className="flex shrink-0 items-center rounded-full border border-warn/30 bg-warn-bg px-2.5 py-0.5 text-[11px] font-bold text-warn">
            {t('market.quality.demo')}
          </span>
        )}
        {liveTicks.size > 0 && (
          <span
            className="flex shrink-0 items-center gap-1.5 rounded-full border border-gain/30 bg-gain-bg px-2.5 py-0.5 text-[11px] font-bold text-gain"
            role="status"
          >
            <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-gain" />
            {t('market.stream.live')} · {liveTicks.size}
          </span>
        )}
        {TAPE_SYMBOLS.map((symbol) => {
          const q = quotes?.get(symbol);
          const display = q?.display ?? symbol;
          const dir = q ? movementDirection(q) : 'unknown';
          const tick = liveTicks.get(symbol);
          const ok = (q?.status === 'ok' && q.price !== null) || tick !== undefined;
          const shownPrice = tick?.price ?? q?.price ?? null;
          const dec = priceDecimals(symbol, q?.group, shownPrice);

          if (quotes === null && !ok) {
            return (
              <span key={symbol} className="flex shrink-0 items-center gap-2 px-3 py-1">
                <Skeleton className="h-4 w-24" />
              </span>
            );
          }

          return (
            <Link
              key={symbol}
              to={`/app/asset/${encodeURIComponent(symbol)}`}
              className="group flex shrink-0 items-center gap-2 rounded-lg border border-transparent px-2.5 py-1 transition-all duration-150 hover:border-line hover:bg-card"
              aria-label={`${display} ${symbol}: ${
                ok
                  ? `${formatNumber(shownPrice!, lang, dec)}, ${dir === 'up' ? t('market.up') : dir === 'down' ? t('market.down') : t('market.flat')}`
                  : t('market.quality.unavailable')
              }`}
            >
                  {liveTicks.has(symbol) && (
                    <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-gain" aria-hidden />
                  )}
                  <span className="fin text-[12px] font-bold tracking-wide">{symbol}</span>
                  {ok ? (
                    <>
                      <span className="fin text-[12px] text-mutedink">{formatNumber(shownPrice!, lang, dec)}</span>
                      <span
                        className={`fin text-[12px] font-semibold ${
                          dir === 'up' ? 'text-gain' : dir === 'down' ? 'text-loss' : 'text-mutedink'
                        }`}
                        aria-hidden
                      >
                        {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '—'}
                        {q?.changePct !== null && q?.changePct !== undefined
                          ? `${q.changePct > 0 ? '+' : ''}${formatNumber(q.changePct, lang, 2)}%`
                          : ''}
                      </span>
                      <span className="sr-only">
                        {dir === 'up' ? t('market.up') : dir === 'down' ? t('market.down') : t('market.flat')}
                      </span>
                    </>
                  ) : (
                    <span className="text-[12px] text-mutedink" aria-hidden>
                      —
                    </span>
                  )}
                </Link>
              );
            })}
      </div>
    </div>
  );
}
