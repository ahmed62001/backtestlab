import { FREE_DAILY_LIMIT, PRO_DAILY_LIMIT } from '../../lib/constants';
import type { Asset, ForgotInput, LoginInput, RegisterInput, ResetInput, StrategyTemplate, Usage, User } from '../../types';
import { mockAssets, mockTemplates } from './seed';
import { mockResult } from './engine';

export const delay = (ms = 600) => new Promise((r) => setTimeout(r, ms));

const SESSION_KEY = 'bl_session';
const USAGE_KEY = 'bl_usage';
const DELETED_BACKTESTS_KEY = 'bl_deleted_backtests';

function readDeletedBacktests(): string[] {
  try {
    const raw = localStorage.getItem(DELETED_BACKTESTS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export function readSession(): { token: string; refreshToken?: string; user: User } | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as { token: string; refreshToken?: string; user: User }) : null;
  } catch {
    return null;
  }
}
export function writeSession(token: string, user: User, refreshToken?: string) {
  const prev = readSession();
  const nextRefresh = refreshToken ?? prev?.refreshToken;
  localStorage.setItem(SESSION_KEY, JSON.stringify({ token, refreshToken: nextRefresh, user }));
}
export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function readUsage() {
  try {
    const raw = localStorage.getItem(USAGE_KEY);
    if (raw) return JSON.parse(raw) as Usage;
  } catch {
    /* default below */
  }
  return { usedToday: 1, dailyLimit: FREE_DAILY_LIMIT, plan: 'free', periodStart: new Date().toISOString() } as Usage;
}

export async function mockLogin(input: LoginInput) {
  await delay();
  if (!input.email.includes('@')) throw { code: 'invalid_email', messageKey: 'auth.errors.invalidEmail' };
  if (input.password.length < 8) throw { code: 'weak_password', messageKey: 'auth.errors.weakPassword' };
  const user: User = {
    id: 'u-1',
    name: input.email.split('@')[0] ?? 'Trader',
    email: input.email,
    plan: 'free',
    language: document.documentElement.lang === 'ar' ? 'ar' : 'en',
    createdAt: new Date().toISOString(),
  };
  return { token: 'mock-token', refresh_token: 'mock-refresh-token', user };
}

export async function mockRegister(input: RegisterInput) {
  await delay();
  if (input.name.trim().length < 2) throw { code: 'invalid_name', messageKey: 'auth.errors.invalidName' };
  return mockLogin({ email: input.email, password: input.password });
}

export async function mockForgot(input: ForgotInput): Promise<{ ok: true }> {
  await delay();
  if (!input.email.includes('@')) throw { code: 'invalid_email', messageKey: 'auth.errors.invalidEmail' };
  // Mock flow: always succeed so the message never reveals whether the account exists.
  return { ok: true };
}

export async function mockReset(input: ResetInput): Promise<{ ok: true }> {
  await delay();
  if (!input.token || input.token.trim().length < 6) {
    throw { code: 'invalid_token', messageKey: 'auth.errors.invalidToken' };
  }
  if (input.password.length < 8) throw { code: 'weak_password', messageKey: 'auth.errors.weakPassword' };
  return { ok: true };
}

export async function mockGetTemplates(): Promise<StrategyTemplate[]> {
  await delay(300);
  return mockTemplates;
}
export async function mockGetAssets(): Promise<Asset[]> {
  await delay(300);
  return mockAssets;
}

export async function mockListBacktests() {
  await delay();
  const deleted = new Set(readDeletedBacktests());
  const seeds = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta'];
  return seeds
    .map((s, i) =>
      mockResult('bt-' + (i + 1), s, {
        templateId: mockTemplates[i % mockTemplates.length].id,
        asset: mockAssets[i % mockAssets.length].ticker,
      }),
    )
    .filter((b) => !deleted.has(b.id));
}

/**
 * Mock equivalent of `DELETE /api/v1/backtests/{id}`. The demo has no server
 * database, so deletion is recorded locally and survives a list refresh —
 * matching the real endpoint's observable contract.
 */
export async function mockDeleteBacktest(id: string): Promise<{ ok: true }> {
  await delay(300);
  const ids = readDeletedBacktests();
  if (!ids.includes(id)) ids.push(id);
  localStorage.setItem(DELETED_BACKTESTS_KEY, JSON.stringify(ids));
  return { ok: true };
}

/**
 * Mock equivalent of `DELETE /api/v1/auth/me`. Mock mode keeps the account
 * only in local storage, so clearing the session is the demo's real deletion;
 * the UI still waits for `{ok:true}` before logging out.
 */
export async function mockDeleteAccount(): Promise<{ ok: true }> {
  await delay(300);
  clearSession();
  return { ok: true };
}

export async function mockGetBacktest(id: string) {
  await delay();
  return mockResult(id, id + '-detail', { asset: 'AAPL' });
}

export async function mockRunBacktest(cfg: Parameters<typeof mockResult>[2] & { asset: string }) {
  await delay(1800);
  const usage = readUsage();
  const limit = usage.plan === 'pro' ? PRO_DAILY_LIMIT : FREE_DAILY_LIMIT;
  if (usage.usedToday >= limit) throw { code: 'limit', messageKey: 'run.errors.limitReached' };
  localStorage.setItem(USAGE_KEY, JSON.stringify({ ...usage, usedToday: usage.usedToday + 1 }));
  return mockResult('bt-' + Date.now(), JSON.stringify(cfg), cfg);
}

export async function mockGetUsage(): Promise<Usage> {
  await delay(250);
  return readUsage();
}

export async function mockGetPlans() {
  await delay(250);
  return [
    { id: 'free' as const, monthlyPrice: 0, yearlyPrice: 0, available: true },
    { id: 'pro' as const, monthlyPrice: 19, yearlyPrice: 182, available: false },
  ];
}

export async function mockGetInvoices() {
  await delay(250);
  return [
    { id: 'INV-2026-001', date: '2026-09-01', amount: 19, status: 'paid' as const },
    { id: 'INV-2026-002', date: '2026-10-01', amount: 19, status: 'paid' as const },
  ];
}

export async function mockGetNotifications() {
  await delay(250);
  return [
    {
      id: 'n1',
      read: false,
      createdAt: new Date().toISOString(),
      titleKey: 'notif.backtestDone.title',
      bodyKey: 'notif.backtestDone.body',
    },
    {
      id: 'n2',
      read: true,
      createdAt: new Date().toISOString(),
      titleKey: 'notif.planReminder.title',
      bodyKey: 'notif.planReminder.body',
    },
  ];
}

export async function mockGetDataProviders() {
  await delay(300);
  return {
    items: [
      {
        id: 'yfinance',
        nameEn: 'Yahoo Finance (yfinance)',
        nameAr: 'ياهو فاينانس',
        category: 'equities',
        markets: ['us_equity', 'global_equity', 'crypto'],
        intervals: ['1D', '1H', '1W', '1M'],
        assetClasses: ['equity', 'crypto'],
        supportsAdjusted: true,
        requiresKey: false,
        requiresPackage: 'yfinance',
        requiresKeyEnv: null,
        rateLimitPerMinute: 60,
        descriptionEn: 'Yahoo Finance public API via yfinance package',
        descriptionAr: 'ياهو فاينانس عبر حزمة yfinance',
        available: false,
        availableDetail: 'yfinance package not installed',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'stooq',
        nameEn: 'Stooq (free EOD, US)',
        nameAr: 'Stooq (أسعار إغلاق أمريكية مجانية)',
        category: 'equities',
        markets: ['us_equity'],
        intervals: ['1D'],
        assetClasses: ['equity'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: 'stooq',
        requiresKeyEnv: null,
        rateLimitPerMinute: 30,
        descriptionEn: 'Stooq free end-of-day US equity data',
        descriptionAr: 'بيانات إغلاق مجانية للأسهم الأمريكية من Stooq',
        available: false,
        availableDetail: 'network restricted in demo',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'ccxt',
        nameEn: 'Crypto exchanges (ccxt, public)',
        nameAr: 'منصات العملات الرقمية (عام فقط)',
        category: 'crypto',
        markets: ['crypto'],
        intervals: ['1D', '1H', '4H', '1W'],
        assetClasses: ['crypto'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: 'ccxt',
        requiresKeyEnv: null,
        rateLimitPerMinute: 120,
        descriptionEn: 'Public crypto exchange data via CCXT',
        descriptionAr: 'بيانات منصات العملات الرقمية العامة عبر CCXT',
        available: false,
        availableDetail: 'ccxt package not installed',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'alphavantage',
        nameEn: 'Alpha Vantage (keyed)',
        nameAr: 'ألفا فانتاج (يتطلب مفتاح)',
        category: 'equities',
        markets: ['us_equity'],
        intervals: ['1D'],
        assetClasses: ['equity'],
        supportsAdjusted: true,
        requiresKey: true,
        requiresPackage: null,
        requiresKeyEnv: 'ALPHAVANTAGE_API_KEY',
        rateLimitPerMinute: 5,
        descriptionEn: 'Alpha Vantage keyed API for US equities',
        descriptionAr: 'ألفا فانتاج بواجهة مفتاح للأسهم الأمريكية',
        available: false,
        availableDetail: 'ALPHAVANTAGE_API_KEY not set',
        licenseClass: 'keyed_free_tier',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'binance_public',
        nameEn: 'Binance Public (spot)',
        nameAr: 'بينانس العام (فوري)',
        category: 'crypto',
        markets: ['crypto'],
        intervals: ['1D', '1H', '4H', '1W', '1M'],
        assetClasses: ['crypto'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 1200,
        descriptionEn: 'Binance public spot market data',
        descriptionAr: 'بيانات السوق الفوري العامة من بينانس',
        available: true,
        availableDetail: '',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'coingecko',
        nameEn: 'CoinGecko (public)',
        nameAr: 'كوين جيكو (عام)',
        category: 'crypto',
        markets: ['crypto'],
        intervals: ['1D'],
        assetClasses: ['crypto'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 50,
        descriptionEn: 'CoinGecko public crypto market data',
        descriptionAr: 'بيانات سوق العملات الرقمية العامة من كوين جيكو',
        available: true,
        availableDetail: '',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'frankfurter',
        nameEn: 'Frankfurter (FX rates)',
        nameAr: 'فرانكفورتر (أسعار صرف)',
        category: 'fx',
        markets: ['fx'],
        intervals: ['1D'],
        assetClasses: ['fx'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 30,
        descriptionEn: 'Frankfurter.app free FX rates (ECB source)',
        descriptionAr: 'أسعار صرف مجانية من Frankfurter.app (مصدر البنك المركزي الأوروبي)',
        available: true,
        availableDetail: '',
        licenseClass: 'public_free',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'fred',
        nameEn: 'FRED (US macro)',
        nameAr: 'فريد (المؤشرات الأمريكية)',
        category: 'macro',
        markets: ['macro'],
        intervals: ['1D', '1W', '1M'],
        assetClasses: ['macro'],
        supportsAdjusted: false,
        requiresKey: true,
        requiresPackage: null,
        requiresKeyEnv: 'FRED_API_KEY',
        rateLimitPerMinute: 120,
        descriptionEn: 'FRED US macroeconomic data (requires key)',
        descriptionAr: 'بيانات الاقتصاد الكلي الأمريكية من FRED (يتطلب مفتاح)',
        available: false,
        availableDetail: 'FRED_API_KEY not set',
        licenseClass: 'keyed_free_tier',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'tiingo',
        nameEn: 'Tiingo (keyed)',
        nameAr: 'تينجو (يتطلب مفتاح)',
        category: 'equities',
        markets: ['us_equity', 'crypto'],
        intervals: ['1D', '1H'],
        assetClasses: ['equity', 'crypto'],
        supportsAdjusted: true,
        requiresKey: true,
        requiresPackage: null,
        requiresKeyEnv: 'TIINGO_API_KEY',
        rateLimitPerMinute: 60,
        descriptionEn: 'Tiingo keyed API for equities and crypto',
        descriptionAr: 'تينجو بواجهة مفتاح للأسهم والعملات الرقمية',
        available: false,
        availableDetail: 'TIINGO_API_KEY not set',
        licenseClass: 'keyed_free_tier',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'twelvedata',
        nameEn: 'Twelve Data (keyed)',
        nameAr: 'تويليف داتا (يتطلب مفتاح)',
        category: 'equities',
        markets: ['us_equity', 'global_equity', 'crypto', 'fx'],
        intervals: ['1D', '1H', '1W', '1M'],
        assetClasses: ['equity', 'crypto', 'fx'],
        supportsAdjusted: true,
        requiresKey: true,
        requiresPackage: null,
        requiresKeyEnv: 'TWELVEDATA_API_KEY',
        rateLimitPerMinute: 800,
        descriptionEn: 'Twelve Data keyed API for multiple asset classes',
        descriptionAr: 'تويليف داتا بواجهة مفتاح لعدة فئات أصول',
        available: false,
        availableDetail: 'TWELVEDATA_API_KEY not set',
        licenseClass: 'keyed_free_tier',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'polygon',
        nameEn: 'Massive (formerly Polygon.io — keyed)',
        nameAr: 'Massive (سابقًا Polygon.io — يتطلب مفتاح)',
        category: 'equities',
        markets: ['us_equity', 'crypto', 'fx'],
        intervals: ['1D', '1H', '1W', '1M'],
        assetClasses: ['equity', 'crypto', 'fx'],
        supportsAdjusted: true,
        requiresKey: true,
        requiresPackage: null,
        requiresKeyEnv: 'MASSIVE_API_KEY',
        rateLimitPerMinute: 300,
        descriptionEn: 'Massive (formerly Polygon.io) keyed API for equities, crypto, FX',
        descriptionAr: 'واجهة Massive (سابقًا Polygon.io) للأسهم والعملات الرقمية والفوركس',
        available: false,
        availableDetail: 'MASSIVE_API_KEY not set',
        licenseClass: 'keyed_free_tier',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'csv_upload',
        nameEn: 'Uploaded CSV',
        nameAr: 'ملف CSV مرفوع',
        category: 'upload',
        markets: ['equity', 'crypto'],
        intervals: ['1D'],
        assetClasses: ['equity', 'crypto'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 0,
        descriptionEn: 'User-uploaded OHLCV CSV files',
        descriptionAr: 'ملفات CSV مرفوعة من المستخدم لبيانات OHLCV',
        available: true,
        availableDetail: '',
        licenseClass: 'user_supplied',
        enabled: true,
        isDefault: false,
      },
      {
        id: 'local',
        nameEn: 'Local fixtures (dev)',
        nameAr: 'ملفات محلية (تطوير)',
        category: 'local',
        markets: ['equity'],
        intervals: ['1D'],
        assetClasses: ['equity'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 0,
        descriptionEn: 'Local fixture files for development',
        descriptionAr: 'ملفات محلية للتطوير',
        available: true,
        availableDetail: '',
        licenseClass: 'dev_only',
        enabled: true,
        isDefault: true,
      },
      {
        id: 'synthetic',
        nameEn: 'Synthetic (seeded GBM, dev)',
        nameAr: 'اصطناعي (تطوير فقط)',
        category: 'synthetic',
        markets: ['equity'],
        intervals: ['1D'],
        assetClasses: ['equity'],
        supportsAdjusted: false,
        requiresKey: false,
        requiresPackage: null,
        requiresKeyEnv: null,
        rateLimitPerMinute: 0,
        descriptionEn: 'Seeded GBM synthetic data for development',
        descriptionAr: 'بيانات اصطناعية GBM مطورة للتطوير',
        available: true,
        availableDetail: '',
        licenseClass: 'dev_only',
        enabled: true,
        isDefault: false,
      },
    ],
    default: 'local',
    enabled: ['yfinance', 'stooq', 'ccxt', 'alphavantage', 'binance_public', 'coingecko', 'frankfurter', 'fred', 'tiingo', 'twelvedata', 'polygon', 'csv_upload', 'local', 'synthetic'],
  };
}


export async function mockCsvUpload(symbol: string, csv: string) {
  await delay(600);
  const lines = csv.trim().split('\n');
  return {
    ok: true,
    symbol: symbol.toUpperCase(),
    rows: Math.max(lines.length - 1, 0),
    start: '2022-01-03',
    end: '2022-01-19',
    largeGaps: 0,
    path: `/tmp/btlab_uploads/${symbol.toUpperCase()}.csv`,
  };
}
