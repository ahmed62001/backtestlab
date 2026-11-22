import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { waitForChartReady, collectDiagnostics } from './chartReady.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '../..');
const EVID = process.env.EVID ?? path.join(REPO, 'final-release-evidence');
const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const API = process.env.API_URL ?? 'http://localhost:8000';

const email = fs.readFileSync('/tmp/opencode/email.txt', 'utf8').trim();
const password =
  process.env.QA_PASSWORD ??
  fs.readFileSync('/tmp/opencode/qa-password.txt', 'utf8').trim();
const res = await fetch(`${API}/api/v1/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password }),
});
const d = await res.json();
const session = { token: d.token ?? d.access_token, refreshToken: d.refresh_token, user: d.user };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
await ctx.addInitScript(
  ([s]) => {
    localStorage.setItem('bl_session', JSON.stringify(s));
    localStorage.setItem('bl_lang', 'en');
    localStorage.setItem('bl_theme', 'light');
  },
  [session],
);

const results = { generated_at: new Date().toISOString(), scenarios: [] };

function record(name, ok, detail) {
  results.scenarios.push({ name, verdict: ok ? 'PASS' : 'FAIL', detail });
  console.log(name, ok ? 'PASS' : 'FAIL', JSON.stringify(detail).slice(0, 400));
}

const page = await ctx.newPage();
const diag = collectDiagnostics(page);

// 1. Refresh persistence
{
  await page.goto(BASE + '/app/asset/AAPL', { waitUntil: 'domcontentloaded' });
  const first = await waitForChartReady(page, { testId: 'chart-price-1d' });
  const before = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-point-count');
  await page.reload({ waitUntil: 'domcontentloaded' });
  const second = await waitForChartReady(page, { testId: 'chart-price-1d' });
  const after = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-point-count');
  record('refresh-keeps-chart', first.ok && second.ok && before === after, { before, after });
}

// 2. Navigate away and back
{
  await page.goto(BASE + '/app', { waitUntil: 'domcontentloaded' });
  await waitForChartReady(page, { testId: 'chart-dashboard-1d' });
  await page.goto(BASE + '/app/history', { waitUntil: 'domcontentloaded' });
  await page.goto(BASE + '/app/asset/AAPL', { waitUntil: 'domcontentloaded' });
  const back = await waitForChartReady(page, { testId: 'chart-price-1d' });
  record('navigation-away-and-back', back.ok, { points: back.checks?.pointCount });
}

// 3. Interval switching 1D <-> 1H
{
  await page.goto(BASE + '/app/asset/AAPL', { waitUntil: 'domcontentloaded' });
  await waitForChartReady(page, { testId: 'chart-price-1d' });
  const dailyPoints = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-point-count');
  await page.getByRole('button', { name: '1H', exact: true }).click();
  const hourly = await waitForChartReady(page, { testId: 'chart-price-1h' });
  const attrInterval = await page.getAttribute('[data-testid="chart-price-1h"]', 'data-interval');
  const lastTs = await page.getAttribute('[data-testid="chart-price-1h"]', 'data-last-ts');
  const intradayTime = /T(?!00:00:00)/.test(lastTs ?? '');
  // Switch back: no stale hourly points under the daily selection.
  await page.getByRole('button', { name: '1D', exact: true }).click();
  const backDaily =await waitForChartReady(page, { testId: 'chart-price-1d' });
  const backPoints = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-point-count');
  record(
    'interval-switch-1d-1h-1d',
    hourly.ok && backDaily.ok && attrInterval === '1H' && Number(backPoints) === Number(dailyPoints) && intradayTime,
    { dailyPoints, hourlyPoints: hourly.checks?.pointCount, attrInterval, backPoints, lastTs },
  );
}

// 4. Rapid A -> B -> A with a delayed first A response
{
  const delayed = { count: 0 };
  const handler = async (route) => {
    const url = route.request().url();
    if (url.includes('symbol=AAPL') && delayed.count === 0) {
      delayed.count += 1;
      await new Promise((r) => setTimeout(r, 2500));
    }
    await route.continue();
  };
  await page.route('**/api/v1/market/series?*', handler);
  const nav = (u) => page.goto(BASE + u, { waitUntil: 'domcontentloaded' });
  await nav('/app/asset/AAPL');
  await new Promise((r) => setTimeout(r, 100));
  await nav('/app/asset/BTC-USD');
  await waitForChartReady(page, { testId: 'chart-price-1d' });
  await nav('/app/asset/AAPL');
  const final = await waitForChartReady(page, { testId: 'chart-price-1d' });
  const symbol = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-symbol');
  const lastValue = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-last-value');
  const api = await fetch(`${API}/api/v1/market/series?symbol=AAPL&interval=1D&days=365`, {
    headers: { Authorization: `Bearer ${session.token}` },
  }).then((r) => r.json());
  const apiLast = api.bars?.[api.bars.length - 1]?.c;
  await page.unroute('**/api/v1/market/series?*', handler);
  record(
    'rapid-a-b-a-late-response-cannot-overwrite',
    final.ok && symbol === 'AAPL' && Math.abs(Number(lastValue) - Number(apiLast)) < 1e-6,
    { symbol, lastValue, apiLast, points: final.checks?.pointCount },
  );
}

// 5. Provider failure -> truthful error -> retry with real data
{
  let failNext = true;
  const handler = async (route) => {
    if (failNext && route.request().url().includes('/api/v1/market/series')) {
      failNext = false;
      await route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'UPSTREAM_UNAVAILABLE', message: 'Injected provider failure' }),
      });
      return;
    }
    await route.continue();
  };
  await page.route('**/api/v1/market/series?*', handler);
  await page.goto(BASE + '/app/asset/AAPL', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-testid="chart-price-1d"][data-chart-state="error"]', {
    timeout: 20000,
  });
  const errorState = await page.getAttribute('[data-testid="chart-price-1d"]', 'data-chart-state');
  const shot = path.join(EVID, 'phase-1/provider-error-state.png');
  await page.screenshot({ path: shot, animations: 'disabled' });
  // Retry: the injected failure is consumed, so the next fetch is real.
  const retry = page.getByRole('button', { name: /retry|try again/i }).first();
  await retry.click();
  const recovered = await waitForChartReady(page, { testId: 'chart-price-1d' });
  await page.unroute('**/api/v1/market/series?*', handler);
  record('provider-error-then-real-retry', errorState === 'error' && recovered.ok, {
    errorState,
    recoveredPoints: recovered.checks?.pointCount,
  });
}

results.consoleErrors = diag.consoleErrors;
results.pageErrors = diag.pageErrors;
results.failedRequests = diag.failedRequests;
fs.mkdirSync(path.join(EVID, 'phase-1/json'), { recursive: true });
fs.writeFileSync(
  path.join(EVID, 'phase-1/json/behaviour-scenarios.json'),
  JSON.stringify(results, null, 2),
);

const failed = results.scenarios.filter((s) => s.verdict === 'FAIL');
console.log(JSON.stringify({ failed: failed.length, scenarios: results.scenarios.map((s) => s.name) }));
await browser.close();
process.exit(failed.length ? 1 : 0);
