/** App-wide constants. APP_NAME is the single rename point for the working name. */
export const APP_NAME = 'BacktestLab';
export const MOCK_LATENCY_MS = 600;
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';
export const RISK_DISCLAIMER_KEY = 'disclaimer.historical';
export const SUPPORT_EMAIL = 'support@backtestlab.app';
export const FREE_DAILY_LIMIT = 3;
export const PRO_DAILY_LIMIT = 100;
export const OVERFITTING_TRADE_THRESHOLD = 30;
