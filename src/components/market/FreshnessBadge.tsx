import { Activity, AlertTriangle, Clock, Database, RefreshCw, WifiOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '../ui';
import type { MarketQuote, SeriesFreshness } from '../../types/market';
import { isStale } from '../../lib/market';
import { ageLabel, type StreamTick } from '../../hooks/useMarketStream';

/** Green LIVE marker shown only while a fresh provider tick exists. */
export function LiveIndicator({ tick, now }: { tick: StreamTick; now: number }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-gain/40 bg-gain-bg px-2.5 py-0.5 text-[12px] font-bold text-gain"
      role="status"
    >
      <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-gain" />
      <Activity size={12} aria-hidden />
      {t('market.stream.live')} · {t('market.stream.updatedAgo', { age: ageLabel(tick.providerTimestamp, now) })}
    </span>
  );
}

/**
 * Three-state market indicator meeting Section 8 requirements:
 * - LIVE: actual incoming WebSocket updates verified
 * - LAST AVAILABLE: historical/REST data available, but no active live ticks
 * - STALE: the latest data exceeds the defined freshness threshold
 */
export function MarketLiveStatusBadge({
  tick,
  quote,
  freshness,
  now,
  streamConnected = false,
  subscriptionError,
  compact = false,
}: {
  tick?: StreamTick;
  quote?: MarketQuote;
  freshness?: SeriesFreshness;
  now: number;
  streamConnected?: boolean;
  subscriptionError?: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();

  // 1. LIVE: verified incoming WebSocket updates
  if (tick && streamConnected) {
    const ageSec = Math.max(0, (now - new Date(tick.providerTimestamp).getTime()) / 1000);
    if (ageSec <= 1200) {
      return (
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-gain/40 bg-gain-bg px-2.5 py-0.5 text-[12px] font-bold text-gain"
          role="status"
        >
          <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-gain" />
          <Activity size={12} aria-hidden />
          {t('market.status.live')} · {ageLabel(tick.providerTimestamp, now)}
        </span>
      );
    }
  }

  // 1b. REAL_TIME REST polling (e.g. Forex pairs / Twelve Data REST when WS slot is not available)
  if (quote && quote.status === 'ok' && quote.classification === 'REAL_TIME') {
    return (
      <Badge tone="brand" className={compact ? 'text-[11px]' : ''}>
        <RefreshCw size={12} aria-hidden />
        {t('market.quality.realTimePolling')}
      </Badge>
    );
  }

  if (subscriptionError && (!quote || quote.status !== 'ok')) {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <AlertTriangle size={12} aria-hidden />
        {t('market.stream.unavailableForInstrument')}
      </Badge>
    );
  }

  // 2. STALE: latest data exceeds defined freshness threshold
  const isStaleData = (freshness && freshness.is_stale) || (quote && isStale(quote));
  if (isStaleData) {
    return (
      <Badge tone="loss" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.status.stale')}
      </Badge>
    );
  }

  // 3. LAST AVAILABLE: historical/REST data available, but no active live ticks
  if (quote && quote.status === 'ok') {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.status.lastAvailable')}
      </Badge>
    );
  }

  if (freshness && freshness.data_status) {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.status.lastAvailable')}
      </Badge>
    );
  }

  return (
    <Badge tone="loss" className={compact ? 'text-[11px]' : ''}>
      <WifiOff size={12} aria-hidden />
      {t('market.quality.unavailable')}
    </Badge>
  );
}
/** Honest data-freshness marker: real-time polling, delayed, end-of-day,
 * reference, stale, or unavailable.
 * Never claims real-time unless the backend's verified classification says so. */
export function FreshnessBadge({ quote, compact = false }: { quote: MarketQuote; compact?: boolean }) {
  const { t } = useTranslation();
  if (quote.status !== 'ok') {
    return (
      <Badge tone="loss" className={compact ? 'text-[11px]' : ''}>
        <WifiOff size={12} aria-hidden />
        {t('market.quality.unavailable')}
      </Badge>
    );
  }
  if (quote.transport === 'CACHE') {
    return (
      <Badge tone="neutral" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.quality.cached')}
      </Badge>
    );
  }
  if (quote.classification === 'REAL_TIME') {
    return (
      <Badge tone="brand" className={compact ? 'text-[11px]' : ''}>
        <RefreshCw size={12} aria-hidden />
        {t('market.quality.realTimePolling')}
      </Badge>
    );
  }
  if (quote.classification === 'DELAYED') {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.quality.delayed')}
      </Badge>
    );
  }
  if (quote.classification === 'REFERENCE') {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <Database size={12} aria-hidden />
        {t('market.quality.reference')}
      </Badge>
    );
  }
  if (isStale(quote)) {
    return (
      <Badge tone="warn" className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {t('market.stale')}
      </Badge>
    );
  }
  return (
    <Badge tone="neutral" className={compact ? 'text-[11px]' : ''}>
      <Clock size={12} aria-hidden />
      {t('market.quality.eod')}
    </Badge>
  );
}

/**
 * Honest marker for a chart series (Phase 3 freshness contract).
 *
 * `data_status` is produced by the backend from the actual provider payload and
 * the asset's session calendar. This component only renders it; it never
 * decides that data is "live".
 */
export function SeriesFreshnessBadge({
  freshness,
  compact = false,
}: {
  freshness: SeriesFreshness;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const status = freshness.data_status;
  const tone =
    status === 'fresh'
      ? 'gain'
      : status === 'unavailable'
        ? 'loss'
        : status === 'stale' || status === 'incomplete'
          ? 'warn'
          : 'neutral';
  const label =
    status === 'fresh'
      ? t('market.freshness.fresh')
      : status === 'delayed'
        ? t('market.freshness.delayed')
        : status === 'stale'
          ? t('market.freshness.stale')
          : status === 'incomplete'
            ? t('market.freshness.incomplete')
            : t('market.freshness.unavailable');
  return (
    <span data-testid="series-freshness" data-data-status={status} data-is-stale={String(freshness.is_stale)}>
      <Badge tone={tone} className={compact ? 'text-[11px]' : ''}>
        <Clock size={12} aria-hidden />
        {label}
        {freshness.served_from_cache && freshness.cache_age_seconds > 0
          ? ` · ${t('market.freshness.cachedAge', { age: `${freshness.cache_age_seconds}s` })}`
          : ''}
      </Badge>
    </span>
  );
}

/** Machine-readable freshness details shown under the chart. */
export function SeriesFreshnessDetails({ freshness }: { freshness: SeriesFreshness }) {
  const { t } = useTranslation();
  const rows: [string, string][] = [
    [t('market.freshness.lastCandle'), freshness.last_candle_timestamp ?? '—'],
    [t('market.freshness.lastCompleted'), freshness.last_completed_candle_timestamp ?? '—'],
    [t('market.freshness.expected'), freshness.expected_completed_open ?? '—'],
    [t('market.freshness.fetchedAt'), freshness.fetched_at ?? '—'],
    [
      t('market.freshness.session'),
      `${t(`market.freshness.sessions.${freshness.session}`)} · ${
        freshness.session_open
          ? t('market.freshness.sessionOpen')
          : t('market.freshness.sessionClosed')
      }`,
    ],
  ];
  return (
    <dl
      data-testid="series-freshness-details"
      className="mt-3 grid grid-cols-1 gap-2 rounded-lg bg-bg px-3 py-2 text-[12px] text-mutedink sm:grid-cols-2"
    >
      {rows.map(([k, v]) => (
        <div key={k} className="flex min-w-0 flex-col">
          <dt>{k}</dt>
          <dd className="fin truncate font-semibold text-ink" dir="ltr">
            {v}
          </dd>
        </div>
      ))}
      <p className="sm:col-span-2">{t('market.freshness.stalenessRule')}</p>
    </dl>
  );
}
