import { USE_MOCK } from '../lib/constants';
import type { BacktestConfig, ForgotInput, LoginInput, RegisterInput, ResetInput } from '../types';
import {
  mockDeleteAccount,
  mockDeleteBacktest,
  mockForgot,
  mockGetAssets,
  mockGetBacktest,
  mockGetInvoices,
  mockGetNotifications,
  mockGetPlans,
  mockGetTemplates,
  mockGetUsage,
  mockListBacktests,
  mockLogin,
  mockRegister,
  mockReset,
  mockRunBacktest,
} from './mock/session';
import { readSession, writeSession, clearSession } from './mock/session';

/**
 * Typed API layer. Mock while VITE_USE_MOCK=true, real HTTP otherwise.
 * Real backend base: VITE_API_BASE, default same-origin (nginx proxies /api).
 * Development uses the Vite proxy in vite.config.ts; set VITE_API_BASE only
 * when the API lives on a different origin.
 */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function token(): string | null {
  try {
    return readSession()?.token ?? null;
  } catch {
    return null;
  }
}

export function getCsrfToken(): string | null {
  try {
    if (typeof document === 'undefined' || !document.cookie) return null;
    const match = document.cookie.match(/(?:^|;\s*)btlab_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  } catch {
    return null;
  }
}

async function req<T>(path: string, init?: RequestInit, allowRefresh = true): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  const method = (init?.method ?? 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  });
  if (res.status === 401 && allowRefresh) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return req<T>(path, init, false);
    clearSession();
    throw { code: 'unauthorized', messageKey: 'auth.errors.sessionExpired' };
  }
  if (res.status === 429) {
    const body = await res.json().catch(() => ({}));
    throw { code: body?.code ?? 'limit', messageKey: 'run.errors.limitReached' };
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // Extract provider name from error message if present (format: "data provider 'X': ...")
    let provider = '';
    const msg = body?.message ?? '';
    const match = msg.match(/data provider '([^']+)'/);
    if (match) provider = match[1];
    const code = (body?.code ?? 'request_failed').toLowerCase();
    throw { code, messageKey: 'run.errors.' + code, provider };
  }
  return res.json() as Promise<T>;
}

/** Exchange the stored refresh token (or HttpOnly refresh cookie) for a new access token. */
async function refreshAccessToken(): Promise<string | null> {
  const s = readSession();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const csrf = getCsrfToken();
  if (csrf) headers['X-CSRF-Token'] = csrf;
  try {
    const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: s?.refreshToken ? JSON.stringify({ refresh_token: s.refreshToken }) : undefined,
    });
    if (!res.ok) return null;
    const d = (await res.json()) as { token?: string; refresh_token?: string };
    if (s && d?.token) {
      writeSession(d.token, s.user, d.refresh_token ?? s.refreshToken);
    }
    return d?.token ?? 'cookie';
  } catch {
    return null;
  }
}

const unwrap = <T>(d: { items: T[] } | T[]): T[] => (Array.isArray(d) ? d : d.items);

export async function apiLogin(input: LoginInput) {
  if (USE_MOCK) return mockLogin(input);
  return req<{ token: string; access_token?: string; refresh_token?: string; user: import('../types').User }>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(input) });
}

export async function apiRegister(input: RegisterInput) {
  if (USE_MOCK) return mockRegister(input);
  return req<{ token: string; access_token?: string; refresh_token?: string; user: import('../types').User }>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(input) });
}

export async function apiForgot(input: ForgotInput) {
  if (USE_MOCK) return mockForgot(input);
  return req<{ ok: true }>('/api/v1/auth/forgot', { method: 'POST', body: JSON.stringify(input) });
}

export async function apiReset(input: ResetInput) {
  if (USE_MOCK) return mockReset(input);
  return req<{ ok: true }>('/api/v1/auth/reset', { method: 'POST', body: JSON.stringify(input) });
}

export async function apiGetTemplates() {
  if (USE_MOCK) return mockGetTemplates();
  return unwrap<import('../types').StrategyTemplate>(await req<{ items: import('../types').StrategyTemplate[] }>('/api/v1/templates'));
}

export async function apiGetAssets() {
  if (USE_MOCK) return mockGetAssets();
  return unwrap<import('../types').Asset>(await req<{ items: import('../types').Asset[] }>('/api/v1/assets'));
}

export async function apiListBacktests() {
  if (USE_MOCK) return mockListBacktests();
  // Fetch every page: the backend default page is 50, so a single request
  // would make older results unreachable in the UI (D-PH1-02).
  const all: import('../types').BacktestSummary[] = [];
  const limit = 200;
  let offset = 0;
  for (;;) {
    const page = await req<{ items: import('../types').BacktestSummary[]; total: number }>(
      `/api/v1/backtests?limit=${limit}&offset=${offset}`,
    );
    const items = page.items ?? [];
    all.push(...items);
    offset += items.length;
    if (items.length === 0 || all.length >= (page.total ?? all.length)) break;
  }
  return all;
}

export async function apiGetBacktest(id: string) {
  if (USE_MOCK) return mockGetBacktest(id);
  return req<import('../types').BacktestResult>(`/api/v1/backtests/${encodeURIComponent(id)}`);
}

export async function apiRunBacktest(cfg: BacktestConfig) {
  if (USE_MOCK) return mockRunBacktest(cfg);
  return req<import('../types').BacktestResult>('/api/v1/backtests', { method: 'POST', body: JSON.stringify(cfg) });
}

export async function apiGetDataProviders(): Promise<import('../types').DataProviderList> {
  if (USE_MOCK) {
    const { mockGetDataProviders } = await import('./mock/session');
    return mockGetDataProviders();
  }
  return req<{ items: import('../types').DataProviderInfo[]; default: string; enabled: string[] }>('/api/v1/data-providers');
}

export async function apiCsvUpload(symbol: string, csv: string): Promise<{ ok: boolean; symbol: string; rows: number; start: string; end: string; largeGaps: number; path: string }> {
  if (USE_MOCK) {
    const { mockCsvUpload } = await import('./mock/session');
    return mockCsvUpload(symbol, csv);
  }
  return req<{ ok: boolean; symbol: string; rows: number; start: string; end: string; largeGaps: number; path: string }>(
    '/api/v1/data-providers/csv-upload', { method: 'POST', body: JSON.stringify({ symbol, csv }) });
}

export async function apiGetUsage() {
  if (USE_MOCK) return mockGetUsage();
  return req<import('../types').Usage>('/api/v1/usage');
}

export async function apiGetPlans() {
  if (USE_MOCK) return mockGetPlans();
  return unwrap<import('../types').Plan>(await req<{ items: import('../types').Plan[] }>('/api/v1/plans'));
}

export async function apiGetInvoices() {
  if (USE_MOCK) return mockGetInvoices();
  return unwrap<import('../types').Invoice>(await req<{ items: import('../types').Invoice[] }>('/api/v1/invoices'));
}

export async function apiGetNotifications() {
  if (USE_MOCK) return mockGetNotifications();
  return unwrap<import('../types').AppNotification>(await req<{ items: import('../types').AppNotification[] }>('/api/v1/notifications'));
}

/**
 * Delete a backtest. The backend scopes the row to the caller (owner-only)
 * and returns `{ok:true}` only after the row is committed for deletion.
 * `signal` lets the caller abort a stale request on unmount.
 */
export async function apiDeleteBacktest(id: string, signal?: AbortSignal) {
  if (USE_MOCK) return mockDeleteBacktest(id);
  return req<{ ok: boolean }>(`/api/v1/backtests/${encodeURIComponent(id)}`, { method: 'DELETE', signal });
}

/**
 * Delete the authenticated account. `DELETE /api/v1/auth/me` removes the
 * user and every dependent row in one transaction; the caller must only
 * clear local session state after `{ok:true}` is confirmed.
 */
export async function apiDeleteAccount(): Promise<{ ok: boolean }> {
  if (USE_MOCK) return mockDeleteAccount();
  return req<{ ok: boolean }>('/api/v1/auth/me', { method: 'DELETE' });
}

export async function apiUpdateMe(name: string): Promise<import('../types').User> {
  if (USE_MOCK) {
    const s = readSession();
    const u = { ...(s?.user as import('../types').User), name };
    if (s) writeSession(s.token, u, s.refreshToken);
    return u;
  }
  return req<import('../types').User>('/api/v1/auth/me', {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
}

export async function apiChangePassword(currentPassword: string, newPassword: string) {
  if (USE_MOCK) return { ok: true };
  return req<{ ok: boolean }>('/api/v1/auth/password', {
    method: 'POST',
    body: JSON.stringify({ currentPassword, newPassword }),
  });
}

export async function apiGetMarketUniverse(): Promise<import('../types').UniverseResponse> {
  if (USE_MOCK) return { items: [] };
  return req<import('../types').UniverseResponse>('/api/v1/market/universe');
}

export async function apiGetMarketQuotes(symbols: string[]): Promise<import('../types').QuotesResponse> {
  if (USE_MOCK) {
    return {
      generatedAt: new Date().toISOString(),
      demo: true,
      items: symbols.map((symbol) => ({
        symbol,
        display: symbol,
        group: 'stocks',
        status: 'unavailable',
        price: null,
        change: null,
        changePct: null,
        prevClose: null,
        dayHigh: null,
        dayLow: null,
        volume: null,
        asOf: null,
        source: null,
        quality: 'unavailable',
        classification: 'UNAVAILABLE',
        transport: null,
        errorCode: 'DEMO_MODE',
      })),
    } as import('../types').QuotesResponse;
  }
  const q = encodeURIComponent(symbols.join(','));
  return req<import('../types').QuotesResponse>(`/api/v1/market/quotes?symbols=${q}`);
}

export async function apiGetMarketSeries(
  symbol: string,
  interval: string,
  days = 365,
  signal?: AbortSignal,
): Promise<import('../types').SeriesResponse> {
  if (USE_MOCK) {
    const e = new Error('Demo mode: market data is not available without a backend.') as Error & { code?: string };
    e.code = 'DEMO_MODE';
    throw e;
  }
  return req<import('../types').SeriesResponse>(
    `/api/v1/market/series?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&days=${days}`,
    signal ? { signal } : undefined,
  );
}

/* ---------------------------------------------------------------------------
 * Public (pre-login) market data.
 *
 * Deliberately NOT routed through `req`: the public chart must work without a
 * session, must never send an Authorization header, and needs the public
 * error contract ({code, message, retryable, retryAfterSeconds}).
 * ------------------------------------------------------------------------- */

export interface PublicMarketError extends Error {
  code: string;
  retryable: boolean;
  retryAfterSeconds?: number;
  status: number;
}

function publicError(body: unknown, status: number, res: Response): PublicMarketError {
  const b = (body ?? {}) as {
    code?: string;
    message?: string;
    retryable?: boolean;
    retryAfterSeconds?: number;
  };
  const headerRetry = Number(res.headers.get('retry-after') ?? '');
  const err = new Error(b.message || 'Public market request failed') as PublicMarketError;
  err.code = b.code || 'request_failed';
  err.retryable = Boolean(b.retryable);
  err.status = status;
  const retry = b.retryAfterSeconds ?? (Number.isFinite(headerRetry) ? headerRetry : undefined);
  if (retry !== undefined) err.retryAfterSeconds = retry;
  return err;
}

async function publicReq<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw publicError(body, res.status, res);
  return body as T;
}

export async function apiGetPublicMarketInstruments(
  signal?: AbortSignal,
): Promise<import('../types').PublicMarketInstrumentsResponse> {
  return publicReq<import('../types').PublicMarketInstrumentsResponse>(
    '/api/v1/public/market/instruments',
    signal,
  );
}

export async function apiGetPublicMarketSeries(
  symbol: string,
  interval: string,
  limit = 250,
  signal?: AbortSignal,
): Promise<import('../types').PublicSeriesResponse> {
  const q = `symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}`;
  return publicReq<import('../types').PublicSeriesResponse>(
    `/api/v1/public/market/series?${q}`,
    signal,
  );
}

export async function apiGetMe(): Promise<import('../types').User> {
  if (USE_MOCK) {
    const s = readSession();
    if (!s?.user) throw { code: 'unauthorized', messageKey: 'auth.errors.sessionExpired' };
    return s.user;
  }
  return req<import('../types').User>('/api/v1/auth/me');
}

export async function apiLogout(): Promise<{ ok: boolean }> {
  if (USE_MOCK) {
    clearSession();
    return { ok: true };
  }
  const res = await req<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' }, false).catch(() => ({ ok: true }));
  clearSession();
  return res;
}

export interface JobStatusResponse {
  jobId: string;
  backtestId: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'canceled';
  progress?: number;
  error?: string | null;
  result?: import('../types').BacktestResult;
}

export async function apiGetJob(jobId: string): Promise<JobStatusResponse> {
  return req<JobStatusResponse>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
}

export async function apiCancelJob(jobId: string): Promise<{ ok: boolean; status: string }> {
  return req<{ ok: boolean; status: string }>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  });
}

export interface MacroSeriesResponse {
  series_id: string;
  title?: string;
  units?: string;
  frequency?: string;
  notes?: string;
  source?: string;
  observations: Array<{ date: string; value: number | null; realtime_start?: string }>;
}

export async function apiGetMacroSeries(
  seriesId: string,
  start = '',
  end = '',
  limit = 200,
): Promise<MacroSeriesResponse> {
  if (USE_MOCK) {
    return {
      series_id: seriesId,
      title: `${seriesId} (Demo)`,
      units: 'Percent',
      frequency: 'Monthly',
      source: 'FRED (Demo)',
      observations: [
        { date: '2025-01-01', value: 4.33 },
        { date: '2025-02-01', value: 4.33 },
        { date: '2025-03-01', value: 4.25 },
      ],
    };
  }
  const q = new URLSearchParams({ series_id: seriesId, limit: String(limit) });
  if (start) q.set('start', start);
  if (end) q.set('end', end);
  return req<MacroSeriesResponse>(`/api/v1/macro/series?${q.toString()}`);
}

