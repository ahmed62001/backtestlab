import { describe, it, expect } from 'vitest';
import {
  mockGetPlans,
  mockGetInvoices,
  mockGetTemplates,
  mockGetAssets,
  mockGetDataProviders,
  mockGetBacktest,
  mockListBacktests,
  mockGetUsage,
} from './session';

describe('mock API contract (shapes pages consume)', () => {
  it('mockGetPlans returns free + pro with prices', async () => {
    const plans = await mockGetPlans();
    expect(plans).toHaveLength(2);
    expect(plans.map((p) => p.id)).toContain('free');
    expect(plans.map((p) => p.id)).toContain('pro');
    const free = plans.find((p) => p.id === 'free');
    const pro = plans.find((p) => p.id === 'pro');
    expect(free?.monthlyPrice).toBe(0);
    expect(pro?.monthlyPrice).toBe(19);
    expect(pro?.yearlyPrice).toBe(182);
  });

  it('mockGetInvoices returns paid invoices with id/date/amount/status', async () => {
    const inv = await mockGetInvoices();
    expect(inv).toHaveLength(2);
    expect(inv.every((i) => i.status === 'paid')).toBe(true);
    expect(inv[0]).toMatchObject({ id: 'INV-2026-001', amount: 19 });
  });

  it('mockGetTemplates returns all 5 templates with id/defaultParams/paramSpecs', async () => {
    const tpls = await mockGetTemplates();
    expect(tpls).toHaveLength(5);
    const ids = tpls.map((t) => t.id);
    expect(ids).toEqual([
      'ma-crossover',
      'rsi',
      'breakout',
      'mean-reversion',
      'buy-hold',
    ]);
    tpls.forEach((t) => {
      expect(t).toHaveProperty('defaultParams');
      expect(t).toHaveProperty('paramSpecs');
      expect(Array.isArray(t.paramSpecs)).toBe(true);
    });
  });

  it('mockGetAssets returns assets with ticker/nameKey/market/halalScreened', async () => {
    const assets = await mockGetAssets();
    expect(assets.length).toBeGreaterThan(0);
    assets.forEach((a) => {
      expect(a).toHaveProperty('ticker');
      expect(a).toHaveProperty('nameKey');
      expect(a).toHaveProperty('market');
      expect(typeof a.halalScreened).toBe('boolean');
    });
  });

  it('mockListBacktests returns summaries with id/name/returns/drawdown', async () => {
    const list = await mockListBacktests();
    expect(list).toHaveLength(6);
    list.forEach((b) => {
      expect(b).toHaveProperty('id');
      expect(b).toHaveProperty('name');
      expect(b).toHaveProperty('templateId');
      expect(b).toHaveProperty('asset');
      expect(b).toHaveProperty('status');
      expect(b).toHaveProperty('totalReturnPct');
      expect(b).toHaveProperty('maxDrawdownPct');
      expect(b).toHaveProperty('sharpe');
      expect(b).toHaveProperty('winRatePct');
      expect(b).toHaveProperty('dataProvider');
      expect(b.status).toBe('done');
    });
  });

  it('mockGetDataProviders returns the backend provider catalog contract', async () => {
    const catalog = await mockGetDataProviders();
    expect(catalog.default).toBe('local');
    expect(catalog.enabled).toEqual(['yfinance', 'stooq', 'ccxt', 'alphavantage', 'binance_public', 'coingecko', 'frankfurter', 'fred', 'tiingo', 'twelvedata', 'polygon', 'csv_upload', 'local', 'synthetic']);
    expect(catalog.items.map((provider) => provider.id)).toEqual(catalog.enabled);
    expect(catalog.items.find((provider) => provider.id === catalog.default)).toMatchObject({
      available: true,
      isDefault: true,
    });
    // Verify all items have required new fields
    catalog.items.forEach((provider) => {
      expect(provider).toHaveProperty('category');
      expect(provider).toHaveProperty('assetClasses');
      expect(provider).toHaveProperty('supportsAdjusted');
      expect(provider).toHaveProperty('requiresPackage');
      expect(provider).toHaveProperty('requiresKeyEnv');
      expect(provider).toHaveProperty('rateLimitPerMinute');
      expect(provider).toHaveProperty('descriptionEn');
      expect(provider).toHaveProperty('descriptionAr');
    });
  });

  it('mockGetBacktest includes provenance, warnings, engine, and costs', async () => {
    const backtest = await mockGetBacktest('bt-contract');
    expect(backtest).toMatchObject({
      dataProvider: 'local',
      config: { dataProvider: 'local' },
      warnings: [{ code: 'DATA_DEV_SOURCE' }, { code: 'COSTS_ASSUMED' }],
      provenance: { provider: 'local', dataHash: expect.stringMatching(/^[a-f0-9]{64}$/) },
      engine: { mode: 'local', engineName: expect.any(String) },
      costs: { feePct: expect.any(Number), estimatedFees: expect.any(Number), note: expect.any(String) },
    });
  });

  it('mockGetUsage returns usage shape used by Billing/usage UI', async () => {
    const usage = await mockGetUsage();
    expect(usage).toHaveProperty('usedToday');
    expect(usage).toHaveProperty('dailyLimit');
    expect(usage).toHaveProperty('plan');
    expect(usage).toHaveProperty('periodStart');
    expect(['free', 'pro']).toContain(usage.plan);
  });
});