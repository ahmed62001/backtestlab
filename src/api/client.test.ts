import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSession, readSession, writeSession } from './mock/session';
import type { User } from '../types';

// Force the real HTTP client path: the app default is mock-on.
vi.mock('../lib/constants', () => ({ USE_MOCK: false }));

/**
 * Phase 1 remediation regressions:
 *  - D-PH1-01 Settings save must PATCH /auth/me and keep the session token.
 *  - D-PH1-02 History must fetch every page, not just the first 50.
 *  - D-PH1-05 a 401 must refresh the access token and retry once.
 */

const user: User = {
  id: 'u-1',
  name: 'Old Name',
  email: 'u1@example.com',
  plan: 'free',
  language: 'en',
  createdAt: '2026-01-01T00:00:00.000Z',
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.stubEnv('VITE_USE_MOCK', 'false');
  localStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  clearSession();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('real API client Phase 1 defects', () => {
  it('D-PH1-01 PATCHes /auth/me without corrupting the token', async () => {
    writeSession('real-token', user, 'refresh-1');
    const fetchMock = vi.fn(async () =>
      json({ ...user, name: 'New Name' }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { apiUpdateMe } = await import('./client');
    const updated = await apiUpdateMe('New Name');

    expect(updated.name).toBe('New Name');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain('/api/v1/auth/me');
    expect(init.method).toBe('PATCH');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer real-token');
    expect(JSON.parse(String(init.body))).toEqual({ name: 'New Name' });
    expect(readSession()?.token).toBe('real-token');
    expect(readSession()?.refreshToken).toBe('refresh-1');
  });

  it('D-PH1-02 fetches every page of backtests', async () => {
    writeSession('real-token', user, 'refresh-1');
    const page1 = Array.from({ length: 200 }, (_, i) => ({ id: `bt-${i}` }));
    const page2 = Array.from({ length: 5 }, (_, i) => ({ id: `bt-${200 + i}` }));
    const offsets: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      const u = new URL(String(url));
      const offset = u.searchParams.get('offset') ?? '';
      offsets.push(offset);
      return json(offset === '0' ? { items: page1, total: 205 } : { items: page2, total: 205 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiListBacktests } = await import('./client');
    const out = await apiListBacktests();

    expect(out).toHaveLength(205);
    expect(offsets).toEqual(['0', '200']);
  });

  it('D-PH1-05 refreshes on 401 and retries with the new token', async () => {
    writeSession('expired-token', user, 'refresh-1');
    const seen: Array<{ url: string; auth: string | undefined }> = [];
    let backtestsCalls = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
      seen.push({ url: String(url), auth });
      if (String(url).includes('/api/v1/auth/refresh')) {
        return json({ token: 'new-token', refresh_token: 'refresh-2' });
      }
      backtestsCalls += 1;
      if (backtestsCalls === 1) return json({}, 401);
      return json({ items: [], total: 0 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiListBacktests } = await import('./client');
    await apiListBacktests();

    const retried = seen.filter((s) => s.url.includes('/api/v1/backtests'));
    expect(retried).toHaveLength(2);
    expect(retried[0].auth).toBe('Bearer expired-token');
    expect(retried[1].auth).toBe('Bearer new-token');
    expect(readSession()?.token).toBe('new-token');
    expect(readSession()?.refreshToken).toBe('refresh-2');
  });
});
