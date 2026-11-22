import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, FlaskConical } from 'lucide-react';
import { Badge, Card, CardTitle, EmptyState, Skeleton, ValueDelta } from '../components/ui';
import { MarketLiveStatusBadge, SeriesFreshnessDetails } from '../components/market/FreshnessBadge';
import { PriceChart } from '../components/market/PriceChart';
import { useMarketQuotes, useMarketSeries, useMarketUniverse, useProviderIntervals } from '../hooks/useMarket';
import { formatDate, formatNumber } from '../lib/format';
import type { AppLang } from '../lib/format';
import { priceDecimals } from '../lib/market';
import { useDraft } from '../stores/draft';
import { ageLabel, useStreamedQuotes } from '../hooks/useMarketStream';
import { applyTickToBars, isIntradayInterval } from '../lib/chartData';
import type { BacktestConfig, MarketBar } from '../types';

/** Asset details: chart, statistics, provenance, related instruments. */
export function Asset() {
  const { symbol = '' } = useParams();
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const navigate = useNavigate();
  const setDraft = useDraft((s) => s.set);
  const [timeframe, setTimeframe] = useState('1D');

  const universe = useMarketUniverse();
  const instrument = useMemo(() => {
    if (!symbol) return undefined;
    const clean = symbol.trim();
    const dash = clean.replace('/', '-');
    const slash = clean.replace('-', '/');
    return universe.items.find(
      (i) => i.symbol === clean || i.symbol === dash || i.symbol === slash,
    );
  }, [universe.items, symbol]);

  const activeSymbol = instrument?.symbol ?? symbol;
  const canStream = Boolean(instrument?.providers.includes('twelvedata'));
  const streamSymbols = useMemo(
    () => (canStream && activeSymbol ? [...new Set([activeSymbol, symbol].filter(Boolean))] : []),
    [canStream, activeSymbol, symbol],
  );
  const assetClassMap = useMemo(() => {
    const m = new Map<string, string>();
    if (instrument) {
      m.set(instrument.symbol, instrument.assetClass);
      if (symbol) m.set(symbol, instrument.assetClass);
    }
    return m;
  }, [instrument, symbol]);

  const stream = useStreamedQuotes(streamSymbols, assetClassMap, { priority: 'high' });
  const tick = stream.liveTicks.get(activeSymbol) ?? stream.liveTicks.get(symbol);
  const subscriptionError = canStream
    ? (stream.snapshot.subscriptionErrors.get(activeSymbol) ?? stream.snapshot.subscriptionErrors.get(symbol))
    : undefined;
  const streamConnected = stream.snapshot.status === 'connected';

  // Poll quotes every 20s whenever there is no active WebSocket tick (covers FX REST, commodities, indices, metals)
  const quotes = useMarketQuotes(activeSymbol ? [activeSymbol] : [], { pollMs: tick ? 0 : 20_000 });
  const quote = quotes.quotes?.get(activeSymbol);
  // Refresh intraday candles every 30s so 1m/5m/15m/1H/4H stay current even without WS
  const series = useMarketSeries(activeSymbol, timeframe, {
    pollMs: isIntradayInterval(timeframe) ? 30_000 : 0,
  });

  const displayBars: MarketBar[] = useMemo(() => {
    return applyTickToBars(series.bars, tick, timeframe, instrument?.assetClass);
  }, [series.bars, tick, timeframe, instrument?.assetClass]);

  const livePrice = tick?.price ?? quote?.price ?? null;
  const dec = priceDecimals(activeSymbol, instrument?.assetClass ?? instrument?.group, livePrice);
  const prevClose = quote?.prevClose ?? null;
  const liveChange =
    livePrice !== null && prevClose !== null && prevClose > 0
      ? livePrice - prevClose
      : (quote?.change ?? null);
  const liveChangePct =
    livePrice !== null && prevClose !== null && prevClose > 0
      ? ((livePrice - prevClose) / prevClose) * 100
      : (quote?.changePct ?? null);
  const liveHigh =
    tick && quote?.dayHigh ? Math.max(quote.dayHigh, tick.price) : (quote?.dayHigh ?? tick?.price ?? null);
  const liveLow =
    tick && quote?.dayLow ? Math.min(quote.dayLow, tick.price) : (quote?.dayLow ?? tick?.price ?? null);

  const providerIntervals = useProviderIntervals(instrument?.providers ?? []);
  const available = useMemo(() => {
    const instIvs = instrument?.intervals ?? ['1D'];
    if (!providerIntervals.length) return instIvs;
    const shared = instIvs.filter((iv) => providerIntervals.includes(iv));
    return shared.length ? shared : instIvs;
  }, [instrument?.intervals, providerIntervals]);
  const related = useMemo(
    () => (instrument ? universe.items.filter((i) => i.group === instrument.group && i.symbol !== instrument.symbol).slice(0, 5) : []),
    [universe.items, instrument],
  );

  const backtestThisAsset = () => {
    setDraft({ asset: symbol } as Partial<BacktestConfig>);
    navigate('/app/new');
  };

  return (
    <div className="flex flex-col gap-5">
      <Link to="/app" className="inline-flex min-h-[44px] items-center gap-1 font-semibold text-brand hover:underline">
        <ArrowLeft size={16} aria-hidden />
        {t('market.backToMarkets')}
      </Link>

      {universe.loading ? (
        <Skeleton className="h-10 w-64" />
      ) : !instrument ? (
        <EmptyState title={t('market.unknownSymbol')} body={symbol} />
      ) : (
        <>
          <header className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-bold">
                <span className="fin">{symbol}</span>
                <span className="ms-3 text-lg font-semibold text-mutedink">{instrument.display}</span>
              </h1>
              <p className="mt-1 text-sm text-mutedink">
                {t(`market.groups.${String(instrument.group)}`)}
                {instrument.exchange ? ` · ${instrument.exchange}` : ''}
                {' · '}
                {t('market.stat.source')}: <span className="fin">{series.provider || quote?.source || '—'}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              <MarketLiveStatusBadge
                tick={tick}
                quote={quote}
                freshness={series.freshness ?? undefined}
                now={stream.now}
                streamConnected={streamConnected}
                subscriptionError={subscriptionError}
              />
              {instrument.backtestEligible && (
                <button
                  type="button"
                  onClick={backtestThisAsset}
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
                >
                  <FlaskConical size={16} aria-hidden />
                  {t('market.backtestAsset')}
                </button>
              )}
            </div>
          </header>

          {subscriptionError && quote?.status !== 'ok' && (
            <div role="status" className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-bg px-4 py-3 text-sm text-warn">
              <AlertTriangle size={16} aria-hidden />
              <span>{t('market.stream.unavailableForInstrument')}</span>
            </div>
          )}

          {livePrice !== null ? (
            <Card>
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="fin text-4xl font-bold">{formatNumber(livePrice, lang, dec)}</span>
                <ValueDelta value={liveChangePct} />
                <span className="fin text-sm text-mutedink">
                  {liveChange !== null && liveChange !== undefined
                    ? `${liveChange > 0 ? '+' : ''}${formatNumber(liveChange, lang, dec)}`
                    : ''}
                </span>
                {tick ? (
                  <span className="text-[12px] text-gain">
                    {t('market.stream.live')} · {t('market.stream.updatedAgo', { age: ageLabel(tick.providerTimestamp, stream.now) })}
                  </span>
                ) : quote?.asOf ? (
                  <span className="text-[13px] text-mutedink">
                    {t('market.stat.asOf')}: <span className="fin">{formatDate(quote.asOf, lang)}</span>
                  </span>
                ) : null}
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                {(
                  [
                    [t('market.stat.prevClose'), prevClose, dec],
                    [t('market.stat.high'), liveHigh, dec],
                    [t('market.stat.low'), liveLow, dec],
                    [t('market.stat.volume'), quote?.volume, 0],
                  ] as const
                ).map(([label, v, precision]) => (
                  <div key={label} className="rounded-lg bg-bg px-3 py-2">
                    <dt className="text-[12px] text-mutedink">{label}</dt>
                    <dd className="fin font-semibold">{v !== null && v !== undefined ? formatNumber(v, lang, precision) : '—'}</dd>
                  </div>
                ))}
              </dl>
              {tick && (
                <p className="mt-3 text-[12px] text-mutedink">{t('market.stream.partialCandle')}</p>
              )}
            </Card>
          ) : quotes.loading ? (
            <Skeleton className="h-24" />
          ) : (
            <Card>
              <p className="text-sm text-mutedink">
                {t('market.unavailable')}
                {quote?.errorCode ? ` (${quote.errorCode})` : ''}
              </p>
            </Card>
          )}

          <Card>
            {tick && (
              <p className="mb-2 text-[12px] font-semibold text-gain">{t('market.stream.live')} · {t('market.stream.partialCandle')}</p>
            )}
            <CardTitle className="mb-3">{t('market.chartTitle')}</CardTitle>
            <PriceChart
              bars={displayBars}
              loading={series.loading}
              error={series.error}
              onRetry={series.retry}
              timeframe={timeframe}
              onTimeframeChange={setTimeframe}
              availableTimeframes={available}
              symbol={activeSymbol}
              assetClass={instrument.assetClass}
              testId={`chart-price-${timeframe.toLowerCase()}`}
            />
            {series.freshness && <SeriesFreshnessDetails freshness={series.freshness} />}
            {series.provenance && (
              <dl className="mt-4 grid grid-cols-2 gap-2 text-[13px] text-mutedink sm:grid-cols-4">
                <div>
                  <dt>{t('market.stat.provider')}</dt>
                  <dd className="fin font-semibold text-ink">{String(series.provenance.provider ?? '—')}</dd>
                </div>
                {series.provenance.fetched_at && (
                  <div>
                    <dt>{t('market.stat.fetchedAt')}</dt>
                    <dd className="fin font-semibold text-ink">{formatDate(String(series.provenance.fetched_at), lang)}</dd>
                  </div>
                )}
                {series.provenance.cache && (
                  <div>
                    <dt>{t('market.stat.cache')}</dt>
                    <dd className="fin font-semibold text-ink">{String(series.provenance.cache)}</dd>
                  </div>
                )}
                {series.provenance.license_class && (
                  <div>
                    <dt>{t('market.stat.license')}</dt>
                    <dd className="fin font-semibold text-ink">{String(series.provenance.license_class)}</dd>
                  </div>
                )}
              </dl>
            )}
          </Card>

          {related.length > 0 && (
            <Card>
              <CardTitle className="mb-2">{t('market.related')}</CardTitle>
              <ul className="flex flex-col divide-y divide-line">
                {related.map((r) => (
                  <li key={r.symbol}>
                    <Link
                      to={`/app/asset/${encodeURIComponent(r.symbol)}`}
                      className="flex min-h-[44px] items-center gap-3 py-2 hover:bg-bg"
                    >
                      <span className="fin font-bold">{r.symbol}</span>
                      <span className="min-w-0 flex-1 truncate text-mutedink">{r.display}</span>
                      <Badge tone="neutral">{t(`market.groups.${String(r.group)}`)}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
