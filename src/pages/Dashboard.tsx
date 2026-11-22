import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowRight, FlaskConical, GraduationCap } from 'lucide-react';
import { useEffect } from 'react';
import { apiGetUsage, apiGetTemplates, apiListBacktests } from '../api';
import {
  Badge,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  Skeleton,
  ValueDelta,
} from '../components/ui';
import { MarketLiveStatusBadge, SeriesFreshnessDetails } from '../components/market/FreshnessBadge';
import { Movers } from '../components/market/Movers';
import { PriceChart } from '../components/market/PriceChart';
import { useMarketQuotes, useMarketSeries, useMarketUniverse, useProviderIntervals } from '../hooks/useMarket';
import { ageLabel, useStreamedQuotes } from '../hooks/useMarketStream';
import { FEATURED_SYMBOL, GROUP_ORDER, TAPE_STREAM_SYMBOLS, TAPE_SYMBOLS, groupInstruments, instrumentLabel, priceDecimals } from '../lib/market';
import { applyTickToBars, isIntradayInterval } from '../lib/chartData';
import { formatDate, formatNumber } from '../lib/format';
import type { AppLang } from '../lib/format';
import { useAuth } from '../stores/auth';
import type { BacktestSummary, StrategyTemplate, Usage } from '../types';

/**
 * Overview: live market dashboard (featured asset, market overview, movers)
 * above the preserved backtest portfolio widgets (usage, recent runs,
 * strategy starters). Market data is delayed/end-of-day — never presented
 * as real-time.
 */
export function Dashboard() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const user = useAuth((s) => s.user);

  const [usage, setUsage] = useState<Usage | null>(null);
  const [templates, setTemplates] = useState<StrategyTemplate[] | null>(null);
  const [recent, setRecent] = useState<BacktestSummary[] | null>(null);
  const [portfolioError, setPortfolioError] = useState(false);
  const loadPortfolio = () => {
    setPortfolioError(false);
    Promise.all([apiGetUsage(), apiGetTemplates(), apiListBacktests()])
      .then(([u, tp, list]) => {
        setUsage(u);
        setTemplates(tp.slice(0, 3));
        setRecent(list.slice(0, 5));
      })
      .catch(() => setPortfolioError(true));
  };
  useEffect(loadPortfolio, []);

  const universe = useMarketUniverse();
  const dashboardSymbols = useMemo(() => {
    if (!universe.items.length) return [FEATURED_SYMBOL, ...TAPE_SYMBOLS];
    const syms = new Set<string>([FEATURED_SYMBOL, ...TAPE_SYMBOLS]);
    const grps = groupInstruments(universe.items);
    for (const g of GROUP_ORDER) {
      const items = grps.get(g) ?? [];
      for (const item of items.slice(0, 6)) {
        syms.add(item.symbol);
      }
    }
    return [...syms];
  }, [universe.items]);
  const quotes = useMarketQuotes(dashboardSymbols, { pollMs: 45_000 });
  const [timeframe, setTimeframe] = useState('1D');
  const series = useMarketSeries(FEATURED_SYMBOL, timeframe, {
    pollMs: isIntradayInterval(timeframe) ? 30_000 : 0,
  });
  const featuredInst = universe.items.find((i) => i.symbol === FEATURED_SYMBOL || i.symbol === 'BTC-USD');
  const featuredProviders = useMemo(() => {
    return featuredInst?.providers ?? ['twelvedata'];
  }, [featuredInst]);
  const featuredIntervals = useProviderIntervals(featuredProviders);
  const featuredQuote = quotes.quotes?.get(FEATURED_SYMBOL);
  const assetClassBySymbol = useMemo(
    () => new Map(universe.items.map((i) => [i.symbol, i.assetClass])),
    [universe.items],
  );
  const featuredStream = useStreamedQuotes([...TAPE_STREAM_SYMBOLS], assetClassBySymbol);
  const featuredTick = featuredStream.liveTicks.get(FEATURED_SYMBOL) ?? featuredStream.liveTicks.get('BTC-USD');
  const groups = useMemo(() => groupInstruments(universe.items), [universe.items]);

  const displayBars = useMemo(
    () => applyTickToBars(series.bars, featuredTick, timeframe, featuredInst?.assetClass),
    [series.bars, featuredTick, timeframe, featuredInst?.assetClass],
  );

  const featuredPrice = featuredTick?.price ?? featuredQuote?.price ?? null;
  const featuredPrevClose = featuredQuote?.prevClose ?? null;
  const featuredChange =
    featuredPrice !== null && featuredPrevClose !== null && featuredPrevClose > 0
      ? featuredPrice - featuredPrevClose
      : (featuredQuote?.change ?? null);
  const featuredChangePct =
    featuredPrice !== null && featuredPrevClose !== null && featuredPrevClose > 0
      ? ((featuredPrice - featuredPrevClose) / featuredPrevClose) * 100
      : (featuredQuote?.changePct ?? null);

  const portfolioReady = usage && templates && recent;

  return (
    <div className="flex flex-col gap-6 animate-fade-in-up">
      {/* Top Header & Telemetry */}
      <header className="bento-card flex flex-wrap items-center justify-between gap-4 rounded-xl2 border border-line/80 px-5 py-4 sm:px-6">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl text-ink">{t('dashboard.title')}</h1>
            <Badge tone="gain" dot>
              {t('market.stream.live', 'Live Feed')}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-mutedink">{t('dashboard.welcome', { name: user?.name ?? 'Trader' })}</p>
        </div>

        {/* Quick Action Bar */}
        <div className="flex flex-wrap items-center gap-2.5">
          <Link
            to="/app/new"
            className="brand-gradient inline-flex min-h-[42px] items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all"
          >
            <FlaskConical size={16} aria-hidden />
            <span>{t('nav.newBacktest')}</span>
          </Link>
          <Link
            to="/app/markets"
            className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl border border-line bg-surface/60 px-4 py-2 text-sm font-semibold text-ink hover:bg-surface hover:border-brand/45 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all"
          >
            <Activity size={16} aria-hidden className="text-brand" />
            <span>{t('nav.markets')}</span>
          </Link>
        </div>
      </header>

      {quotes.demo && (
        <p role="status" className="rounded-lg border border-warn/40 bg-warn-bg px-4 py-3 text-sm text-warn">
          {t('market.demoNote')}
        </p>
      )}
      {universe.error && (
        <p role="alert" className="rounded-lg border border-loss/40 bg-loss-bg px-4 py-3 text-sm">
          {t('market.unavailable')}{' '}
          <button type="button" onClick={universe.retry} className="font-semibold text-brand hover:underline">
            {t('common.retry')}
          </button>
        </p>
      )}

      {/* Featured asset */}
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="fin text-sm font-bold tracking-wide text-brand">
              <Link to={`/app/asset/${encodeURIComponent(FEATURED_SYMBOL)}`} className="hover:underline">
                {instrumentLabel(featuredInst?.display, FEATURED_SYMBOL)}
              </Link>
            </p>
            {featuredPrice !== null ? (
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <p className="fin mt-1 text-4xl font-bold leading-none">{formatNumber(featuredPrice, lang, 2)}</p>
                <span className="inline-flex align-middle">
                  <ValueDelta value={featuredChangePct} />
                </span>
                {featuredChange !== null && (
                  <span className="fin text-sm text-mutedink">
                    {featuredChange > 0 ? '+' : ''}
                    {formatNumber(featuredChange, lang, 2)}
                  </span>
                )}
              </div>
            ) : quotes.loading ? (
              <Skeleton className="mt-2 h-10 w-48" />
            ) : (
              <p className="mt-1 text-xl font-semibold text-mutedink">—</p>
            )}
            <p className="mt-1 text-[12px] text-mutedink">
              {featuredTick ? (
                <span className="text-gain">
                  {t('market.stream.live')} · {t('market.stream.updatedAgo', { age: ageLabel(featuredTick.providerTimestamp, featuredStream.now) })}
                </span>
              ) : featuredQuote?.asOf ? (
                <>
                  {t('market.stat.asOf')}: <span className="fin">{formatDate(featuredQuote.asOf, lang)}</span>
                </>
              ) : null}
              {' · '}
              {t('market.stat.source')}: <span className="fin">{series.provider || 'Twelve Data'}</span>
            </p>
          </div>
          <MarketLiveStatusBadge
            tick={featuredTick}
            quote={featuredQuote}
            freshness={series.freshness ?? undefined}
            now={featuredStream.now}
            streamConnected={featuredStream.snapshot.status === 'connected'}
            subscriptionError={featuredStream.snapshot.subscriptionErrors.get(FEATURED_SYMBOL)}
          />
        </div>
        <PriceChart
          bars={displayBars}
          loading={series.loading}
          error={series.error}
          onRetry={series.retry}
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          availableTimeframes={featuredIntervals.length ? featuredIntervals : (featuredInst?.intervals ?? ['1D'])}
          symbol={FEATURED_SYMBOL}
          assetClass={featuredInst?.assetClass}
          testId={`chart-dashboard-${timeframe.toLowerCase()}`}
        />
        {series.freshness && <SeriesFreshnessDetails freshness={series.freshness} />}
        {featuredQuote?.status === 'ok' && (
          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[
              [t('market.stat.prevClose'), featuredQuote.prevClose],
              [t('market.stat.high'), featuredQuote.dayHigh],
              [t('market.stat.low'), featuredQuote.dayLow],
              [t('market.stat.volume'), featuredQuote.volume],
            ].map(([label, v]) => (
              <div key={String(label)} className="rounded-lg bg-bg px-3 py-2">
                <dt className="text-[12px] text-mutedink">{label}</dt>
                <dd className="fin font-semibold">
                  {v !== null && v !== undefined ? formatNumber(Number(v), lang, v === featuredQuote.volume ? 0 : 2) : '—'}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      {/* Market overview by group */}
      {universe.loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : (
        <section aria-label={t('market.overview')} className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {GROUP_ORDER.map((g) => {
            const items = groups.get(g) ?? [];
            if (items.length === 0) return null;
            return (
              <Card key={g} interactive>
                <div className="mb-2 flex items-center justify-between">
                  <CardTitle>{t(`market.groups.${g}`)}</CardTitle>
                  <Link to="/app/markets" className="text-[13px] font-semibold text-brand hover:underline">
                    {t('common.viewAll')}
                  </Link>
                </div>
                <ul className="flex flex-col divide-y divide-line">
                  {items.slice(0, 6).map((inst) => {
                    const q = quotes.quotes?.get(inst.symbol);
                    const tick = featuredStream.liveTicks.get(inst.symbol);
                    const shownPrice = tick?.price ?? (q?.status === 'ok' ? q.price : null);
                    const ok = shownPrice !== null && shownPrice !== undefined;
                    const prevClose = q?.prevClose ?? null;
                    const changePct =
                      ok && prevClose !== null && prevClose > 0
                        ? ((shownPrice - prevClose) / prevClose) * 100
                        : (q?.changePct ?? null);
                    const dec = priceDecimals(inst.symbol, inst.group, shownPrice);
                    const unsupported =
                      q?.errorCode === 'UNSUPPORTED_INSTRUMENT' || q?.errorCode === 'PROVIDER_NOT_ENTITLED';
                    return (
                      <li key={inst.symbol} className="flex items-center gap-3 py-2">
                        <div className="min-w-0 flex-1">
                          <Link
                            to={`/app/asset/${encodeURIComponent(inst.symbol)}`}
                            className="fin flex items-center gap-1.5 truncate text-sm font-bold hover:underline"
                          >
                            {tick && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-gain" aria-hidden />}
                            <span className="truncate">{inst.symbol}</span>
                          </Link>
                          <span className="block truncate text-[12px] text-mutedink">{inst.display}</span>
                        </div>
                        <span className="fin text-[13px] font-semibold">
                          {ok ? (
                            formatNumber(shownPrice, lang, dec)
                          ) : unsupported ? (
                            <span className="text-[11px] font-normal text-mutedink">{t('market.unsupported')}</span>
                          ) : (
                            '—'
                          )}
                        </span>
                        {ok ? <ValueDelta value={changePct} /> : <span className="text-mutedink">—</span>}
                      </li>
                    );
                  })}
                </ul>
              </Card>
            );
          })}
        </section>
      )}

      {quotes.loading && quotes.list.length === 0 ? (
        <div className="grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <Skeleton className="mb-2 h-6 w-24" />
              <Skeleton className="h-32 w-full" />
            </Card>
          ))}
        </div>
      ) : (
        <Movers quotes={quotes.list} />
      )}

      {/* Backtest portfolio (preserved widgets) */}
      <section aria-label={t('dashboard.quickStart')} className="flex flex-col gap-4">
        <h2 className="flex items-center gap-2 text-lg font-bold">
          {t('dashboard.quickStart')}
          <Link
            to="/app/new"
            className="ms-auto inline-flex min-h-[44px] items-center gap-1 text-sm font-semibold text-brand hover:underline"
          >
            {t('dashboard.startCta')}
            <ArrowRight size={16} aria-hidden />
          </Link>
        </h2>
        {portfolioError ? (
          <ErrorState onRetry={loadPortfolio} />
        ) : !portfolioReady ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        ) : (
          <>
            <Card>
              <div className="mb-2 flex items-center justify-between gap-2">
                <CardTitle>{t('dashboard.usage')}</CardTitle>
                <span className="fin text-sm font-semibold text-mutedink">
                  <bdi>
                    {usage.usedToday} / {usage.dailyLimit}
                  </bdi>
                </span>
              </div>
              <div
                role="progressbar"
                aria-valuenow={usage.usedToday}
                aria-valuemin={0}
                aria-valuemax={usage.dailyLimit}
                aria-label={t('dashboard.usage')}
                className="h-2.5 overflow-hidden rounded-full bg-bg"
              >
                <div
                  className={`h-full rounded-full ${
                    usage.usedToday >= usage.dailyLimit
                      ? 'bg-loss'
                      : usage.usedToday >= usage.dailyLimit - 1
                        ? 'bg-warn'
                        : 'bg-brand'
                  }`}
                  style={{ width: `${Math.round(Math.min(usage.usedToday / usage.dailyLimit, 1) * 100)}%` }}
                />
              </div>
              {usage.usedToday >= usage.dailyLimit && (
                <p role="alert" className="mt-2 text-[13px] font-medium text-loss">
                  {t('dashboard.usageDone')}{' '}
                  <Link to="/app/billing" className="font-semibold text-brand hover:underline">
                    {t('billing.upgrade')}
                  </Link>
                </p>
              )}
              {usage.usedToday >= usage.dailyLimit - 1 && usage.usedToday < usage.dailyLimit && (
                <p role="status" className="mt-2 flex items-center gap-1.5 text-[13px] text-warn">
                  <AlertTriangle size={14} aria-hidden />
                  {t('dashboard.usageNear')}
                </p>
              )}
            </Card>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((tp) => (
                <Card key={tp.id} interactive className="flex flex-col justify-between">
                  <div>
                    <div className="mb-3 flex size-10 items-center justify-center rounded-lg bg-brand/10 text-brand">
                      <FlaskConical size={20} aria-hidden />
                    </div>
                    <h3 className="mb-1 text-base font-semibold">{t(`templates.${tp.id}.name`)}</h3>
                    <p className="mb-3 text-sm text-mutedink">{t(`templates.${tp.id}.desc`)}</p>
                  </div>
                  <Link
                    to={`/app/new?template=${tp.id}`}
                    className="inline-flex min-h-[44px] items-center gap-1 font-semibold text-brand hover:underline"
                  >
                    <span>{t('dashboard.startCta')}</span>
                    <ArrowRight size={15} aria-hidden className="rtl:rotate-180" />
                  </Link>
                </Card>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="min-w-0">
                <div className="mb-2 flex items-center justify-between">
                  <CardTitle>{t('dashboard.recent')}</CardTitle>
                  <Link to="/app/history" className="text-sm font-semibold text-brand hover:underline">
                    {t('common.viewAll')}
                  </Link>
                </div>
                {recent.length === 0 ? (
                  <EmptyState
                    title={t('dashboard.emptyRecent')}
                    action={
                      <Link
                        to="/app/new"
                        className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
                      >
                        {t('dashboard.startCta')}
                      </Link>
                    }
                  />
                ) : (
                  <ul className="flex flex-col divide-y divide-line">
                    {recent.map((r) => (
                      <li key={r.id} className="flex items-center gap-3 py-2.5">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold">
                            <bdi dir="ltr">{r.asset}</bdi> · {t(`templates.${r.templateId}.name`)}
                          </p>
                          <p className="fin text-[13px] text-mutedink">{formatDate(r.createdAt, lang)}</p>
                        </div>
                        <ValueDelta value={r.totalReturnPct} />
                        <Link
                          to={`/app/results/${r.id}`}
                          className="shrink-0 text-[13px] font-semibold text-brand hover:underline"
                        >
                          {t('dashboard.viewResults')}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card className="min-w-0">
                <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
                  <GraduationCap size={18} aria-hidden className="text-brand" />
                  {t('dashboard.overfitTitle')}
                </h2>
                <p className="text-sm text-mutedink">{t('dashboard.overfitBody')}</p>
                <div className="mt-2">
                  <Badge tone="warn">n &lt; 30</Badge>
                </div>
              </Card>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
