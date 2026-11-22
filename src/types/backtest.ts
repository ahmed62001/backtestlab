import type { PlanId } from './auth';
export type TemplateId = 'ma-crossover' | 'rsi' | 'breakout' | 'mean-reversion' | 'buy-hold';

export interface StrategyTemplate {
  id: TemplateId;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  riskLabel: 'lower' | 'medium' | 'higher';
  defaultParams: Record<string, number | string>;
  paramSpecs: ParamSpec[];
}

export interface ParamSpec {
  key: string;
  min?: number;
  max?: number;
  step?: number;
  default: number | string;
}

export interface Asset {
  ticker: string;
  nameKey: string;
  market: string;
  halalScreened: boolean;
}

export type BacktestStatus = 'queued' | 'running' | 'done' | 'failed';

export type BacktestInterval = '1m' | '5m' | '15m' | '30m' | '1H' | '4H' | '1D' | '1W' | '1M';

export interface StopLossConfig {
  mode: 'none' | 'fixed_pct' | 'risk_based';
  pct?: number;
}

export interface TakeProfitConfig {
  mode: 'none' | 'fixed_pct';
  pct?: number;
}

export interface PositionSizingConfig {
  mode: 'pct_equity' | 'fixed_amount' | 'risk_based';
  value?: number;
  maxAllocationPct?: number;
}

export interface ValidationConfig {
  mode: 'none' | 'split';
  inSamplePct?: number;
  splitDate?: string;
}

export interface BacktestConfig {
  templateId: TemplateId;
  asset: string;
  from: string;
  to: string;
  interval?: BacktestInterval;
  initialCapital: number;
  feePct: number;
  commissionPct?: number;
  slippagePct?: number;
  spreadPct?: number;
  stopLoss?: StopLossConfig;
  takeProfit?: TakeProfitConfig;
  positionSizing?: PositionSizingConfig;
  validation?: ValidationConfig;
  params: Record<string, number | string>;
  dataProvider?: string;
}

export interface DataProviderInfo {
  id: string;
  nameEn: string;
  nameAr: string;
  category: string;
  markets: string[];
  intervals: string[];
  assetClasses: string[];
  supportsAdjusted: boolean;
  requiresKey: boolean;
  requiresPackage: string | null;
  requiresKeyEnv: string | null;
  rateLimitPerMinute: number;
  descriptionEn: string;
  descriptionAr: string;
  available: boolean;
  availableDetail: string;
  licenseClass: string;
  enabled: boolean;
  isDefault: boolean;
}

export interface DataProviderList {
  items: DataProviderInfo[];
  default: string;
  enabled: string[];
}

export interface BacktestSummary {
  id: string;
  name: string;
  templateId: TemplateId;
  asset: string;
  dataProvider: string;
  status: BacktestStatus;
  createdAt: string;
  totalReturnPct: number;
  maxDrawdownPct: number;
  sharpe: number;
  winRatePct: number;
  trades: number;
  vsBuyHoldPct: number;
}

export interface EquityPoint {
  date: string;
  strategy: number;
  benchmark: number;
  drawdown: number;
}

export interface MonthlyCell {
  year: number;
  month: number;
  value: number | null;
}

export interface Trade {
  id: string;
  date: string;
  side: 'buy' | 'sell';
  direction?: 'long' | 'short';
  entryPrice?: number;
  price: number;
  qty: number;
  pnl: number | null;
  returnPct: number | null;
  exitReason?: string;
}

export interface ValidationSplitMetrics {
  totalReturnPct: number;
  annualizedReturnPct: number;
  volatilityPct: number;
  sharpe: number;
  sortino: number | null;
  maxDrawdownPct: number;
  winRatePct: number;
  profitFactor: number | null;
  trades: number;
  benchmarkReturnPct: number;
  vsBuyHoldPct: number;
}

export interface BacktestResult extends BacktestSummary {
  interval?: string;
  annualizedReturnPct?: number;
  volatilityPct?: number;
  sortino?: number | null;
  profitFactor?: number | null;
  expectancy?: number;
  benchmarkReturnPct?: number;
  config: BacktestConfig;
  equity: EquityPoint[];
  monthly: MonthlyCell[];
  tradesList: Trade[];
  overfitting: boolean;
  disclaimer: string;
  warnings: { code: string; message?: string }[];
  strategyControls?: {
    stopLoss: StopLossConfig;
    takeProfit: TakeProfitConfig;
    positionSizing: PositionSizingConfig;
    validation: ValidationConfig;
  };
  validation?: {
    mode: string;
    splitDate: string;
    inSampleBars: number;
    outOfSampleBars: number;
    inSample: ValidationSplitMetrics;
    outOfSample: ValidationSplitMetrics;
  };
  provenance: {
    provider: string;
    symbol: string;
    interval: string;
    start: string;
    end: string;
    bars: number;
    rows: number;
    dataHash: string;
    timezone: string;
    adjusted: boolean | null;
    license_class: string;
    fetched_at?: string;
    cache?: string;
    cacheDir?: string;
    warnings?: { code: string; message?: string }[];
  };
  engine: {
    mode: string;
    engineName: string;
    vendorCommit?: string | null;
    vendorVersionOrRef?: string | null;
  };
  costs: {
    feePct: number;
    estimatedFees: number;
    note: string;
  };
}

export interface Usage {
  usedToday: number;
  dailyLimit: number;
  plan: PlanId;
  periodStart: string;
}

export interface Plan {
  id: PlanId;
  monthlyPrice: number;
  yearlyPrice: number;
  /** False when checkout is not configured on this deployment. */
  available?: boolean;
}

export interface Invoice {
  id: string;
  date: string;
  amount: number;
  status: 'paid' | 'pending';
}

export interface AppNotification {
  id: string;
  read: boolean;
  createdAt: string;
  titleKey: string;
  bodyKey: string;
}
