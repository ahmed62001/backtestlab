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

async function login() {
  const res = await fetch(`${API}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(`login failed ${res.status}`);
  const d = await res.json();
  return { token: d.token ?? d.access_token, refreshToken: d.refresh_token, user: d.user };
}

const session = await login();
const args = process.argv.slice(2);
const runA = args[0] ?? 'bt-81358b1f';
const runB = args[1] ?? 'bt-4b48f039';

const cases = [
  {
    name: 'dashboard',
    url: '/app',
    testId: 'chart-dashboard-1d',
    apiPattern: /\/api\/v1\/market\/series\?.*symbol=GC%3DF.*interval=1D/,
    out: 'phase-1/after-dashboard.png',
  },
  {
    name: 'asset-aapl',
    url: '/app/asset/AAPL',
    testId: 'chart-price-1d',
    apiPattern: /\/api\/v1\/market\/series\?.*symbol=AAPL.*interval=1D/,
    out: 'phase-1/after-asset-AAPL.png',
  },
  {
    name: 'asset-btc',
    url: '/app/asset/BTC-USD',
    testId: 'chart-price-1d',
    apiPattern: /\/api\/v1\/market\/series\?.*symbol=BTC-USD.*interval=1D/,
    out: 'phase-1/after-asset-BTC-USD.png',
  },
  {
    name: 'asset-gcf',
    url: '/app/asset/GC%3DF',
    testId: 'chart-price-1d',
    apiPattern: /\/api\/v1\/market\/series\?.*symbol=GC%3DF.*interval=1D/,
    out: 'phase-1/after-asset-GC=F.png',
  },
  {
    name: 'compare-aapl',
    url: `/app/compare?a=${runA}&b=${runB}`,
    testId: 'chart-compare-equity',
    out: 'phase-2/after-compare.png',
  },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
await ctx.addInitScript(
  ([sess]) => {
    localStorage.setItem('bl_session', JSON.stringify(sess));
    localStorage.setItem('bl_lang', 'en');
    localStorage.setItem('bl_theme', 'light');
  },
  [session],
);

const results = { generated_at: new Date().toISOString(), runs: { a: runA, b: runB }, cases: [] };

for (const c of cases) {
  const page = await ctx.newPage();
  const diag = collectDiagnostics(page);
  const started = Date.now();
  let readiness;
  try {
    const apiResponsePromise = c.apiPattern
      ? page
          .waitForResponse((r) => c.apiPattern.test(r.url()) && r.status() === 200, {
            timeout: 30000,
          })
          .catch(() => null)
      : null;
    await page.goto(BASE + c.url, { waitUntil: 'domcontentloaded' });
    readiness = await waitForChartReady(page, {
      testId: c.testId,
      expectedPoints: c.expectedPoints,
      apiResponsePromise,
    });
  } catch (e) {
    readiness = { ok: false, error: String(e) };
  }
  // Recharts animates entry: give the geometry a final settle before capture.
  await page.waitForTimeout(400);
  const outPath = path.join(EVID, c.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  await page.screenshot({ path: outPath, animations: 'disabled', fullPage: false });
  const record = {
    name: c.name,
    url: c.url,
    testId: c.testId,
    verdict: readiness.ok && diag.consoleErrors.length === 0 && diag.failedRequests.length === 0
      ? 'PASS'
      : 'FAIL',
    readiness,
    consoleErrors: diag.consoleErrors,
    pageErrors: diag.pageErrors,
    failedRequests: diag.failedRequests,
    screenshot: c.out,
    durationMs: Date.now() - started,
  };
  // A compare chart must carry both series in its attributes.
  if (c.name === 'compare-aapl') {
    record.compareCounts = await page
      .locator(`[data-testid="${c.testId}"]`)
      .evaluate((el) => ({
        a: el.getAttribute('data-series-a-count'),
        b: el.getAttribute('data-series-b-count'),
        first: el.getAttribute('data-first-ts'),
        last: el.getAttribute('data-last-ts'),
      }));
  }
  results.cases.push(record);
  await page.close();
}

fs.mkdirSync(path.join(EVID, 'phase-1/json'), { recursive: true });
fs.mkdirSync(path.join(EVID, 'phase-2/json'), { recursive: true });
const split = {
  phase1: results.cases.filter((c) => c.name !== 'compare-aapl'),
  phase2: results.cases.filter((c) => c.name === 'compare-aapl'),
};
fs.writeFileSync(
  path.join(EVID, 'phase-1/json/chart-readiness.json'),
  JSON.stringify({ generated_at: results.generated_at, cases: split.phase1 }, null, 2),
);
fs.writeFileSync(
  path.join(EVID, 'phase-2/json/compare-readiness.json'),
  JSON.stringify({ generated_at: results.generated_at, runs: results.runs, cases: split.phase2 }, null, 2),
);

const failed = results.cases.filter((c) => c.verdict === 'FAIL');
console.log(
  JSON.stringify(
    results.cases.map((c) => ({
      name: c.name,
      verdict: c.verdict,
      points: c.readiness?.checks?.pointCount,
      bbox: c.readiness?.checks?.pathBBox,
      error: c.readiness?.error,
      compareCounts: c.compareCounts,
      console: c.consoleErrors.length,
      failedReq: c.failedRequests.length,
    })),
    null,
    2,
  ),
);
await browser.close();
process.exit(failed.length ? 1 : 0);
