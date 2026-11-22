import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { GROUP_ORDER, priceDecimals } from '../../lib/market';
import type { MarketInstrument, MarketQuote } from '../../types';
import { EmptyState, Skeleton, ValueDelta } from '../ui';
import { FreshnessBadge, LiveIndicator } from './FreshnessBadge';
import type { StreamTick } from '../../hooks/useMarketStream';

/** Full market watchlist: search, group filter, per-row freshness. */
export function QuoteTable({
  instruments,
  quotes,
  loading,
  liveTicks,
  now,
}: {
  instruments: MarketInstrument[];
  quotes: Map<string, MarketQuote>;
  loading: boolean;
  liveTicks?: Map<string, StreamTick>;
  now?: number;
}) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const [query, setQuery] = useState('');
  const [group, setGroup] = useState<string | null>(null);

  const presentGroups = useMemo(() => {
    const set = new Set(instruments.map((i) => String(i.group)));
    return GROUP_ORDER.filter((g) => set.has(g));
  }, [instruments]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return instruments.filter((inst) => {
      if (group && String(inst.group) !== group) return false;
      if (!q) return true;
      return (
        inst.symbol.toLowerCase().includes(q) || inst.display.toLowerCase().includes(q)
      );
    });
  }, [instruments, group, query]);

  return (
    <section aria-label={t('market.watchlist')}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('market.search')}
          aria-label={t('market.search')}
          className="min-h-[44px] min-w-[200px] flex-1 rounded-lg border border-line bg-card px-3 text-sm"
        />
        <div className="flex flex-wrap gap-1" role="group" aria-label={t('market.groupFilter')}>
          <button
            type="button"
            onClick={() => setGroup(null)}
            aria-pressed={group === null}
            className={`min-h-[36px] rounded-md px-3 text-[13px] font-semibold ${
              group === null ? 'bg-brand text-white' : 'bg-card text-mutedink hover:text-ink'
            }`}
          >
            {t('market.all')}
          </button>
          {presentGroups.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => setGroup(g)}
              aria-pressed={group === g}
              className={`min-h-[36px] rounded-md px-3 text-[13px] font-semibold ${
                group === g ? 'bg-brand text-white' : 'bg-card text-mutedink hover:text-ink'
              }`}
            >
              {t(`market.groups.${g}`)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState title={t('market.emptySearch')} />
      ) : (
        <div className="overflow-x-auto rounded-xl2 border border-line bg-card">
          <table className="w-full min-w-[720px] text-start text-sm">
            <thead>
              <tr className="border-b border-line text-[12px] uppercase tracking-wide text-mutedink">
                <th className="px-4 py-3 text-start">{t('market.col.symbol')}</th>
                <th className="px-4 py-3 text-start">{t('market.col.name')}</th>
                <th className="px-4 py-3 text-end">{t('market.col.price')}</th>
                <th className="px-4 py-3 text-end">{t('market.col.change')}</th>
                <th className="px-4 py-3 text-end">{t('market.col.highLow')}</th>
                <th className="px-4 py-3 text-end">{t('market.col.volume')}</th>
                <th className="px-4 py-3 text-start">{t('market.col.status')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((inst) => {
                const q = quotes.get(inst.symbol);
                const tick = liveTicks?.get(inst.symbol);
                const restOk = q?.status === 'ok' && q.price !== null;
                const ok = restOk || tick !== undefined;
                const shownPrice = tick?.price ?? q?.price ?? null;
                const prevClose = q?.prevClose ?? null;
                const change =
                  shownPrice !== null && prevClose !== null && prevClose > 0
                    ? shownPrice - prevClose
                    : (q?.change ?? null);
                const changePct =
                  shownPrice !== null && prevClose !== null && prevClose > 0
                    ? ((shownPrice - prevClose) / prevClose) * 100
                    : (q?.changePct ?? null);
                const dayHigh =
                  tick && q?.dayHigh !== null && q?.dayHigh !== undefined
                    ? Math.max(q.dayHigh, tick.price)
                    : (q?.dayHigh ?? null);
                const dayLow =
                  tick && q?.dayLow !== null && q?.dayLow !== undefined
                    ? Math.min(q.dayLow, tick.price)
                    : (q?.dayLow ?? null);
                const dec = priceDecimals(inst.symbol, inst.group, shownPrice);

                return (
                  <tr key={inst.symbol} className="hover:bg-bg">
                    <td className="px-4 py-3">
                      <Link
                        to={`/app/asset/${encodeURIComponent(inst.symbol)}`}
                        className="fin font-bold text-brand hover:underline"
                      >
                        {inst.symbol}
                      </Link>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-3 text-mutedink">{inst.display}</td>
                    <td className="fin px-4 py-3 text-end font-semibold">
                      {ok && shownPrice !== null ? formatNumber(shownPrice, lang, dec) : '—'}
                    </td>
                    <td className="px-4 py-3 text-end">
                      {changePct !== null ? (
                        <span className="flex flex-col items-end gap-0.5">
                          <ValueDelta value={changePct} />
                          <span className="fin text-[12px] text-mutedink">
                            {change !== null && change !== undefined
                              ? `${change > 0 ? '+' : ''}${formatNumber(change, lang, dec)}`
                              : ''}
                          </span>
                        </span>
                      ) : (
                        <span className="text-mutedink">—</span>
                      )}
                    </td>
                    <td className="fin px-4 py-3 text-end text-[13px] text-mutedink">
                      {dayHigh !== null && dayLow !== null
                        ? `${formatNumber(dayHigh, lang, dec)} / ${formatNumber(dayLow, lang, dec)}`
                        : '—'}
                    </td>
                    <td className="fin px-4 py-3 text-end text-[13px] text-mutedink">
                      {restOk && q.volume !== null ? formatNumber(q.volume, lang, 0) : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {tick && now !== undefined ? (
                        <LiveIndicator tick={tick} now={now} />
                      ) : q ? (
                        <span className="flex flex-col items-start gap-1">
                          <FreshnessBadge quote={q} compact />
                          {ok && q.asOf && (
                            <span className="text-[12px] text-mutedink">
                              {t('market.stat.asOf')}: <span className="fin">{formatDate(q.asOf, lang)}</span>
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-mutedink">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
