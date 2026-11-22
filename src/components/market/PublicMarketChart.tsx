import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, AlertTriangle, Clock, RefreshCw } from 'lucide-react';
import { Badge, Card, EmptyState, Skeleton } from '../ui';
import { PriceChart } from './PriceChart';
import { usePublicMarketInstruments, usePublicMarketSeries } from '../../hooks/usePublicMarket';
import { useStreamedQuotes } from '../../hooks/useMarketStream';
import { applyTickToBars } from '../../lib/chartData';
import { formatDate, formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { instrumentLabel } from '../../lib/market';
import type { PublicDataStatus } from '../../types';
import type { PublicMarketError } from '../../api';

function StatusBadge({
  status,
  isLive,
  staleLabel,
}: {
  status: PublicDataStatus;
  isLive?: boolean;
  staleLabel?: string;
}) {
  const { t } = useTranslation();
  if (isLive) {
    return (
      <span role="status" aria-live="polite">
        <Badge tone="gain">
          <Activity size={12} aria-hidden />
          {t('publicChart.status.live')}
        </Badge>
      </span>
    );
  }
  const map: Record<PublicDataStatus, { tone: 'gain' | 'warn' | 'neutral'; key: string }> = {
    live: { tone: 'gain', key: 'publicChart.status.live' },
    delayed: { tone: 'warn', key: 'publicChart.status.delayed' },
    cached: { tone: 'neutral', key: 'publicChart.status.cached' },
    stale: { tone: 'warn', key: 'publicChart.status.stale' },
  };
  const m = map[status] ?? map.delayed;
  return (
    <span role="status" aria-live="polite">
      <Badge tone={m.tone}>
        {status === 'stale' ? <Clock size={12} aria-hidden /> : <RefreshCw size={12} aria-hidden />}
        {status === 'stale' && staleLabel ? staleLabel : t(m.key)}
      </Badge>
    </span>
  );
}

function errorMessage(err: PublicMarketError, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (err.code === 'RATE_LIMITED' || err.status === 429) {
    return t('publicChart.rateLimited', { seconds: err.retryAfterSeconds ?? 60 });
  }
  if (err.status === 400 || err.status === 404) return t('publicChart.invalid');
  if (err.status >= 500 || err.retryable) return t('publicChart.providerError');
  return t('publicChart.appError');
}
/**
 * Real, provider-backed market chart for the public landing page.
 * Renders only what the public endpoint actually returns — never synthetic
 * points. The chart canvas keeps a left-to-right time axis while the
 * surrounding controls mirror with the page direction.
 */
export function PublicMarketChart() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const instruments = usePublicMarketInstruments();
  const [symbol, setSymbol] = useState('');
  const [interval, setIntervalValue] = useState('1D');

  useEffect(() => {
    if (!symbol && instruments.defaultSymbol) setSymbol(instruments.defaultSymbol);
  }, [instruments.defaultSymbol, symbol]);

  const current = useMemo(
    () => instruments.items.find((i) => i.symbol === symbol),
    [instruments.items, symbol],
  );

  useEffect(() => {
    if (current && !current.intervals.includes(interval)) {
      setIntervalValue(current.intervals[0] ?? '1D');
    }
  }, [current, interval]);

  const series = usePublicMarketSeries(symbol, interval);
  const stream = useStreamedQuotes(symbol ? [symbol] : []);
  const liveTick = symbol ? stream.liveTicks.get(symbol) : undefined;

  const data = series.data;
  const displayName = data?.displayName ?? current?.displayName ?? symbol;
  const currency = data?.currency ?? current?.currency ?? null;
  const provider = data?.provider ?? instruments.provider ?? null;
  const err = series.error;

  const displayBars = useMemo(() => {
    if (!data?.candles) return [];
    return applyTickToBars(data.candles, liveTick, interval, current?.assetClass);
  }, [data?.candles, liveTick, interval, current?.assetClass]);

  const staleLabel = data?.staleSince
    ? t('publicChart.status.staleSince', { time: formatDate(data.staleSince, lang) })
    : undefined;

  return (
    <Card className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{t('publicChart.title')}</h2>
          <p className="mt-0.5 truncate text-[13px] text-mutedink">
            <bdi>{instrumentLabel(displayName, symbol)}</bdi>
            {liveTick && (
              <span className="fin font-semibold text-gain"> · {formatNumber(liveTick.price, lang, 2)}</span>
            )}
            {currency ? <span className="fin"> · {currency}</span> : null}
            {provider ? (
              <>
                {' · '}
                {t('publicChart.source')}: <span className="fin">{provider === 'twelvedata' ? 'Twelve Data' : provider}</span>
              </>
            ) : null}
          </p>
        </div>
        {data && <StatusBadge status={data.dataStatus} isLive={Boolean(liveTick)} staleLabel={staleLabel} />}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-[13px] font-medium text-mutedink">
          {t('publicChart.symbol')}
          <select
            className="min-h-[40px] w-full min-w-0 rounded-lg border border-line bg-card px-3 text-sm text-ink"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            disabled={instruments.loading || instruments.items.length === 0}
            aria-label={t('publicChart.symbol')}
          >
            {instruments.items.length === 0 && <option value="">{t('publicChart.loading')}</option>}
            {instruments.items.map((it) => (
              <option key={it.symbol} value={it.symbol}>
                {it.symbol} — {it.displayName}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[13px] font-medium text-mutedink">
          {t('publicChart.interval')}
          <select
            className="fin min-h-[40px] w-full min-w-0 rounded-lg border border-line bg-card px-3 text-sm text-ink"
            value={interval}
            onChange={(e) => setIntervalValue(e.target.value)}
            disabled={!current}
            aria-label={t('publicChart.interval')}
          >
            {(current?.intervals ?? ['1D']).map((iv) => (
              <option key={iv} value={iv}>
                {iv}
              </option>
            ))}
          </select>
        </label>
        {data?.lastCandleTime && (
          <p className="text-[12px] text-mutedink">
            {t('publicChart.lastCandle')}:{' '}
            <span className="fin">{formatDate(data.lastCandleTime, lang)}</span>
          </p>
        )}
      </div>

      <div
        data-testid="chart-public-state"
        data-chart-state={
          instruments.loading
            ? 'loading'
            : instruments.error
              ? 'error'
              : !data
                ? series.error
                  ? 'error'
                  : 'loading'
                : data.candles.length === 0
                  ? 'empty'
                  : 'ready'
        }
      >
      {instruments.loading ? (
        <Skeleton className="h-[360px] w-full" />
      ) : instruments.error ? (
        <div role="alert" className="flex flex-col items-center gap-3 rounded-xl2 border border-loss/30 bg-loss-bg px-6 py-8 text-center">
          <p className="text-sm text-ink">{errorMessage(instruments.error, t as unknown as (k: string, o?: Record<string, unknown>) => string)}</p>
          <button
            type="button"
            onClick={instruments.retry}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-line bg-card px-4 text-sm font-semibold text-ink hover:bg-bg"
          >
            <RefreshCw size={15} aria-hidden />
            {t('publicChart.retry')}
          </button>
        </div>
      ) : !symbol ? (
        <EmptyState title={t('publicChart.empty')} action={<RetryButton onRetry={instruments.retry} />} />
      ) : err?.code === 'UNSUPPORTED_INSTRUMENT' ? (
        <div role="alert" className="flex flex-col items-center gap-3 rounded-xl2 border border-warn/40 bg-warn-bg px-6 py-8 text-center">
          <AlertTriangle className="size-8 text-warn" aria-hidden />
          <p className="text-sm font-semibold text-ink">
            {err.message || (symbol === 'GC=F'
              ? 'Gold Futures (GC=F) is not supported by the Twelve Data market data plan. Gold Spot (XAU/USD) is available.'
              : t('publicChart.invalid'))}
          </p>
          {instruments.items.some((i) => i.symbol === 'XAU/USD') && (
            <button
              type="button"
              onClick={() => setSymbol('XAU/USD')}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:opacity-90"
            >
              Switch to Gold Spot (XAU/USD)
            </button>
          )}
        </div>
      ) : err ? (
        <div role="alert" className="flex flex-col items-center gap-3 rounded-xl2 border border-loss/30 bg-loss-bg px-6 py-8 text-center">
          <p className="text-sm text-ink">{errorMessage(err, t as unknown as (k: string, o?: Record<string, unknown>) => string)}</p>
          <p className="fin text-[12px] text-mutedink">{err.code}</p>
          <RetryButton onRetry={series.retry} />
        </div>
      ) : series.loading && !data ? (
        <Skeleton className="h-[360px] w-full" />
      ) : data && data.candles.length === 0 ? (
        <EmptyState title={t('publicChart.empty')} action={<RetryButton onRetry={series.retry} />} />
      ) : data ? (
        <>
          {data.dataStatus === 'stale' && (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-[13px] text-warn">
              <AlertTriangle size={14} aria-hidden />
              {t('publicChart.staleNotice', {
                time: data.staleSince ? formatDate(data.staleSince, lang) : `${data.cacheAgeSeconds}s`,
              })}
            </p>
          )}
          <PriceChart
            bars={displayBars}
            loading={false}
            error={false}
            onRetry={series.retry}
            timeframe={interval}
            onTimeframeChange={setIntervalValue}
            availableTimeframes={current?.intervals ?? [interval]}
            showTimeframes={false}
            symbol={symbol}
            testId={`chart-public-${interval.toLowerCase()}`}
          />
        </>
      ) : (
        <Skeleton className="h-[360px] w-full" />
      )}
      </div>
    </Card>
  );
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onRetry}
      className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-line bg-card px-4 text-sm font-semibold text-ink hover:bg-bg"
    >
      <RefreshCw size={15} aria-hidden />
      {t('publicChart.retry')}
    </button>
  );
}
