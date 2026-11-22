import { OVERFITTING_TRADE_THRESHOLD } from '../../lib/constants';
import type { BacktestConfig, BacktestResult, MonthlyCell, TemplateId, Trade } from '../../types';
import { hashSeed, seededRandom, templateBias } from './seed';

export function buildEquity(seedStr: string, months: number, drift: number, vol: number, start: number) {
  const rand = seededRandom(hashSeed(seedStr));
  const pts = [];
  let s = start;
  let b = start;
  let peak = start;
  const base = new Date('2022-01-01T00:00:00Z').getTime();
  const steps = Math.max(months * 21, 60);
  for (let i = 0; i < steps; i += 1) {
    s *= 1 + drift + (rand() - 0.5) * 2 * vol;
    b *= 1 + 0.0005 + (rand() - 0.5) * 2 * 0.012;
    peak = Math.max(peak, s);
    pts.push({
      date: new Date(base + i * 86400000).toISOString().slice(0, 10),
      strategy: Math.round(s * 100) / 100,
      benchmark: Math.round(b * 100) / 100,
      drawdown: Math.round(((s - peak) / peak) * 10000) / 100,
    });
  }
  return pts;
}

export function buildMonthly(seedStr: string): MonthlyCell[] {
  const rand = seededRandom(hashSeed('m' + seedStr));
  const cells: MonthlyCell[] = [];
  for (const year of [2022, 2023]) {
    for (let m = 0; m < 12; m += 1) {
      cells.push({ year, month: m, value: rand() < 0.06 ? null : Math.round((rand() - 0.44) * 10 * 100) / 100 });
    }
  }
  return cells;
}

export function buildTrades(seedStr: string, n: number): Trade[] {
  const rand = seededRandom(hashSeed('t' + seedStr));
  const trades: Trade[] = [];
  let price = 150;
  for (let i = 0; i < n; i += 1) {
    price *= 1 + (rand() - 0.48) * 0.06;
    const side = i % 2 === 0 ? 'buy' : 'sell';
    const pnl = side === 'sell' ? Math.round((rand() - 0.42) * 400 * 100) / 100 : null;
    trades.push({
      id: 'tr-' + (i + 1),
      date: new Date(Date.now() - (n - i) * 7 * 86400000).toISOString().slice(0, 10),
      side,
      price: Math.round(price * 100) / 100,
      qty: 1 + Math.floor(rand() * 10),
      pnl,
      returnPct: pnl === null ? null : Math.round((pnl / 1000) * 100) / 100,
    });
  }
  return trades;
}

export function mockResult(id: string, seedStr: string, cfg?: Partial<BacktestConfig>): BacktestResult {
  const rand = seededRandom(hashSeed(seedStr + id));
  const templateId = (cfg?.templateId ?? 'ma-crossover') as TemplateId;
  const bias = templateBias[templateId];
  const capital = cfg?.initialCapital ?? 10000;
  const equity = buildEquity(seedStr + id, 24, bias.drift, bias.vol, capital);
  const endS = equity[equity.length - 1].strategy;
  const endB = equity[equity.length - 1].benchmark;
  const tradesCount = templateId === 'buy-hold' ? 2 : 18 + Math.floor(rand() * 60);
  const tradesList = buildTrades(seedStr + id, tradesCount);
  const wins = tradesList.filter((t) => (t.pnl ?? 0) > 0).length;
  return {
    id,
    name: (cfg?.asset ?? 'AAPL') + ' / ' + templateId,
    templateId,
    asset: cfg?.asset ?? 'AAPL',
    dataProvider: cfg?.dataProvider ?? 'local',
    status: 'done',
    createdAt: new Date(Date.now() - Math.floor(rand() * 20) * 86400000).toISOString(),
    totalReturnPct: Math.round(((endS - capital) / capital) * 100 * 100) / 100,
    maxDrawdownPct: Math.round(Math.min(...equity.map((p) => p.drawdown)) * 100) / 100,
    sharpe: Math.round((0.4 + rand() * 1.4) * 100) / 100,
    winRatePct: tradesList.length ? Math.round((wins / tradesList.length) * 1000) / 10 : 0,
    trades: tradesCount,
    vsBuyHoldPct: Math.round(((endS - endB) / endB) * 100 * 100) / 100,
    config: {
      templateId,
      asset: cfg?.asset ?? 'AAPL',
      from: cfg?.from ?? '2022-01-01',
      to: cfg?.to ?? '2023-12-31',
      initialCapital: capital,
      feePct: cfg?.feePct ?? 0.1,
      params: (cfg?.params ?? {}) as Record<string, number | string>,
      dataProvider: cfg?.dataProvider ?? 'local',
    },
    equity,
    monthly: buildMonthly(seedStr + id),
    tradesList,
    overfitting: tradesCount < OVERFITTING_TRADE_THRESHOLD,
    disclaimer: 'Historical results do not guarantee future performance.',
    warnings: [{ code: 'DATA_DEV_SOURCE' }, { code: 'COSTS_ASSUMED' }],
    provenance: {
      provider: cfg?.dataProvider ?? 'local',
      symbol: cfg?.asset ?? 'AAPL',
      interval: '1D',
      start: cfg?.from ?? '2022-01-01',
      end: cfg?.to ?? '2023-12-31',
      bars: equity.length,
      rows: equity.length,
      dataHash: hashSeed(seedStr + id).toString(16).padStart(16, '0').padEnd(64, '0'),
      timezone: 'UTC',
      adjusted: null,
      license_class: 'dev_only',
      fetched_at: new Date().toISOString(),
      cache: 'miss',
      cacheDir: '/tmp/btlab_cache',
      warnings: [{ code: 'DATA_DEV_SOURCE' }, { code: 'COSTS_ASSUMED' }],
    },
    engine: {
      mode: 'local',
      engineName: 'Mock backtest engine',
      vendorCommit: null,
      vendorVersionOrRef: null,
    },
    costs: {
      feePct: cfg?.feePct ?? 0.1,
      estimatedFees: 0,
      note: 'Mock estimated per-trade fee.',
    },
  };
}
