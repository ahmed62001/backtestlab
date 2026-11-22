import type { BacktestResult, BacktestSummary } from './backtest';

export type { BacktestResult, BacktestSummary };

export interface ApiError {
  code: string;
  messageKey: string;
}

export interface ApiList<T> {
  items: T[];
  total: number;
}
