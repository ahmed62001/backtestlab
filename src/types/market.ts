export type MarketGroup = 'indices' | 'metals' | 'commodities' | 'stocks' | 'forex' | 'crypto';

export type QuoteQuality = 'eod' | 'reference' | 'unavailable';
export type QuoteStatus = 'ok' | 'unavailable';

/** Data classification, tracked separately from delivery transport. */
export type MarketClassification =
  | 'REAL_TIME'
  | 'DELAYED'
  | 'END_OF_DAY'
  | 'REFERENCE'
  | 'UNAVAILABLE'
  | null;

/** How the update reached the backend. */
export type MarketTransport = 'WEBSOCKET' | 'REST_POLLING' | 'REST_SNAPSHOT' | 'CACHE' | null;

export interface MarketInstrument {
  symbol: string;
  display: string;
  group: MarketGroup | string;
  assetClass: string;
  quoteCurrency: string | null;
  baseCurrency: string | null;
  exchange: string | null;
  backtestEligible: boolean;
  intervals: string[];
  providers: string[];
}

export interface MarketQuote {
  symbol: string;
  display: string;
  group: MarketGroup | string;
  status: QuoteStatus;
  price: number | null;
  change: number | null;
  changePct: number | null;
  prevClose: number | null;
  dayHigh: number | null;
  dayLow: number | null;
  volume: number | null;
  asOf: string | null;
  source: string | null;
  quality: QuoteQuality;
  classification: MarketClassification;
  transport: MarketTransport;
  errorCode: string | null;
}

export interface QuotesResponse {
  generatedAt: string;
  items: MarketQuote[];
  demo?: boolean;
}

export interface UniverseResponse {
  items: MarketInstrument[];
}

export interface MarketBar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface SeriesProvenance {
  provider?: string;
  symbol?: string;
  interval?: string;
  fetched_at?: string;
  cache?: string;
  adjusted?: boolean;
  license_class?: string;
  [key: string]: unknown;
}

export interface SeriesResponse {
  symbol: string;
  display: string;
  interval: string;
  provider: string;
  bars: MarketBar[];
  provenance: SeriesProvenance;
  generatedAt: string;
  freshness?: SeriesFreshness;
}

/* ---- Freshness contract (Phase 3) ---- */

export type SeriesDataStatus = 'fresh' | 'delayed' | 'stale' | 'incomplete' | 'unavailable';

export interface SeriesFreshness {
  provider: string;
  interval: string;
  /** Open time (UTC ISO-8601) of the newest candle returned, in-progress included. */
  last_candle_timestamp: string | null;
  /** Open time of the newest candle whose window has fully completed. */
  last_completed_candle_timestamp: string | null;
  /** When the upstream provider response was obtained (not when the cache was read). */
  fetched_at: string | null;
  cache_age_seconds: number;
  served_from_cache: boolean;
  data_status: SeriesDataStatus;
  /** Derived from data_status; never an independent source of truth. */
  is_stale: boolean;
  /** Session calendar used for the staleness decision. */
  session: string;
  session_open: boolean;
  expected_completed_open?: string | null;
  detail?: string | null;
}


/* ---- Public (pre-login) market chart contract ---- */

export type PublicDataStatus = 'live' | 'delayed' | 'cached' | 'stale';

export interface PublicCandle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface PublicMarketInstrument {
  symbol: string;
  displayName: string;
  assetClass: string;
  currency: string | null;
  intervals: string[];
}

export interface PublicMarketInstrumentsResponse {
  items: PublicMarketInstrument[];
  defaultSymbol: string | null;
  provider: string;
}

export interface PublicSeriesResponse {
  symbol: string;
  displayName: string;
  assetClass: string;
  currency: string | null;
  provider: string;
  interval: string;
  candles: PublicCandle[];
  lastCandleTime: string | null;
  retrievedAt: string;
  dataStatus: PublicDataStatus;
  cacheAgeSeconds: number;
  staleSince?: string;
}
