import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import { Badge } from '../components/ui';
import { QuoteTable } from '../components/market/QuoteTable';
import { useMarketQuotes, useMarketUniverse } from '../hooks/useMarket';
import { useStreamedQuotes } from '../hooks/useMarketStream';
import { STREAM_PRIORITY } from '../lib/market';

/** Markets: full watchlist across every asset class. */
export function Markets() {
  const { t } = useTranslation();
  const universe = useMarketUniverse();
  const symbols = useMemo(() => universe.items.map((i) => i.symbol), [universe.items]);
  const quotes = useMarketQuotes(symbols.length ? symbols : [], { pollMs: 60_000 });
  const assetClassBySymbol = useMemo(
    () => new Map(universe.items.map((i) => [i.symbol, i.assetClass])),
    [universe.items],
  );
  const streamSymbols = useMemo(
    () => STREAM_PRIORITY.filter((s) => symbols.includes(s)),
    [symbols],
  );
  const { liveTicks, now } = useStreamedQuotes(streamSymbols, assetClassBySymbol);

  return (
    <div className="flex flex-col gap-4">
      <header className="bento-card flex flex-wrap items-center justify-between gap-3 rounded-xl2 border border-line/80 px-5 py-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">{t('market.title')}</h1>
          <p className="mt-0.5 text-sm text-mutedink">{t('market.subtitle')}</p>
        </div>
        <Badge tone="gain" dot>
          <Info size={13} aria-hidden />
          {t('market.delayedNote')}
        </Badge>
      </header>
      {quotes.demo && (
        <p role="status" className="rounded-lg border border-warn/40 bg-warn-bg px-4 py-3 text-sm text-warn">
          {t('market.demoNote')}
        </p>
      )}
      <QuoteTable instruments={universe.items} quotes={quotes.quotes ?? new Map()} loading={universe.loading || quotes.loading} liveTicks={liveTicks} now={now} />
    </div>
  );
}
