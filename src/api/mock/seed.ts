import type { Asset, StrategyTemplate, TemplateId } from '../../types';

export function seededRandom(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export function hashSeed(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export const mockAssets: Asset[] = [
  { ticker: 'AAPL', nameKey: 'assets.aapl', market: 'NASDAQ', halalScreened: false },
  { ticker: 'MSFT', nameKey: 'assets.msft', market: 'NASDAQ', halalScreened: false },
  { ticker: 'NVDA', nameKey: 'assets.nvda', market: 'NASDAQ', halalScreened: false },
  { ticker: 'TSLA', nameKey: 'assets.tsla', market: 'NASDAQ', halalScreened: false },
  { ticker: 'AMD', nameKey: 'assets.amd', market: 'NASDAQ', halalScreened: false },
  { ticker: '2222.SR', nameKey: 'assets.saudiaramco', market: 'Tadawul', halalScreened: true },
  { ticker: '1120.SR', nameKey: 'assets.alrajhi', market: 'Tadawul', halalScreened: true },
  { ticker: 'BTC-USD', nameKey: 'assets.btc', market: 'Crypto', halalScreened: false },
  { ticker: 'ETH-USD', nameKey: 'assets.eth', market: 'Crypto', halalScreened: false },
  { ticker: 'SPY', nameKey: 'assets.spy', market: 'NYSE', halalScreened: false },
];

export const mockTemplates: StrategyTemplate[] = [
  {
    id: 'ma-crossover',
    difficulty: 'beginner',
    riskLabel: 'medium',
    defaultParams: { fastPeriod: 20, slowPeriod: 50 },
    paramSpecs: [
      { key: 'fastPeriod', min: 5, max: 100, step: 1, default: 20 },
      { key: 'slowPeriod', min: 20, max: 200, step: 1, default: 50 },
    ],
  },
  {
    id: 'rsi',
    difficulty: 'beginner',
    riskLabel: 'medium',
    defaultParams: { rsiPeriod: 14, oversold: 30, overbought: 70 },
    paramSpecs: [
      { key: 'rsiPeriod', min: 2, max: 30, step: 1, default: 14 },
      { key: 'oversold', min: 10, max: 40, step: 1, default: 30 },
      { key: 'overbought', min: 60, max: 90, step: 1, default: 70 },
    ],
  },
  {
    id: 'breakout',
    difficulty: 'intermediate',
    riskLabel: 'higher',
    defaultParams: { lookback: 20, bufferPct: 0.5 },
    paramSpecs: [
      { key: 'lookback', min: 5, max: 100, step: 1, default: 20 },
      { key: 'bufferPct', min: 0, max: 5, step: 0.1, default: 0.5 },
    ],
  },
  {
    id: 'mean-reversion',
    difficulty: 'intermediate',
    riskLabel: 'higher',
    defaultParams: { lookback: 20, zEntry: 2, zExit: 0.5 },
    paramSpecs: [
      { key: 'lookback', min: 5, max: 100, step: 1, default: 20 },
      { key: 'zEntry', min: 0.5, max: 4, step: 0.1, default: 2 },
      { key: 'zExit', min: 0, max: 2, step: 0.1, default: 0.5 },
    ],
  },
  {
    id: 'buy-hold',
    difficulty: 'beginner',
    riskLabel: 'lower',
    defaultParams: {},
    paramSpecs: [],
  },
];

export const templateBias: Record<TemplateId, { drift: number; vol: number }> = {
  'ma-crossover': { drift: 0.0009, vol: 0.016 },
  rsi: { drift: 0.0006, vol: 0.014 },
  breakout: { drift: 0.0011, vol: 0.022 },
  'mean-reversion': { drift: 0.0004, vol: 0.012 },
  'buy-hold': { drift: 0.0005, vol: 0.013 },
};
