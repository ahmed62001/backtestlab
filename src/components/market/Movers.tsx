import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { mostActive, topGainers, topLosers } from '../../lib/market';
import type { MarketQuote } from '../../types';
import { Card, CardTitle, EmptyState, ValueDelta } from '../ui';

function MoverList({ items, valueMode }: { items: MarketQuote[]; valueMode: 'pct' | 'volume' }) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  if (items.length === 0) return <EmptyState title={t('market.empty')} />;
  return (
    <ul className="flex flex-col divide-y divide-line">
      {items.map((q) => (
        <li key={q.symbol} className="flex items-center gap-3 py-2.5">
          <div className="min-w-0 flex-1">
            <Link
              to={`/app/asset/${encodeURIComponent(q.symbol)}`}
              className="fin block truncate text-sm font-bold hover:underline"
            >
              {q.symbol}
            </Link>
            <span className="block truncate text-[12px] text-mutedink">{q.display}</span>
          </div>
          <span className="fin text-[13px] text-mutedink">
            {q.price !== null ? formatNumber(q.price, lang, 2) : '—'}
          </span>
          {valueMode === 'pct' ? (
            <ValueDelta value={q.changePct} />
          ) : (
            <span className="fin text-[13px] font-semibold">{q.volume !== null ? formatNumber(q.volume, lang, 0) : '—'}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Market movers: top gainers, top losers, most active. */
export function Movers({ quotes }: { quotes: MarketQuote[] }) {
  const { t } = useTranslation();
  return (
    <section aria-label={t('market.movers')} className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardTitle className="mb-2">{t('market.gainers')}</CardTitle>
        <MoverList items={topGainers(quotes)} valueMode="pct" />
      </Card>
      <Card>
        <CardTitle className="mb-2">{t('market.losers')}</CardTitle>
        <MoverList items={topLosers(quotes)} valueMode="pct" />
      </Card>
      <Card>
        <CardTitle className="mb-2">{t('market.active')}</CardTitle>
        <MoverList items={mostActive(quotes)} valueMode="volume" />
      </Card>
    </section>
  );
}
