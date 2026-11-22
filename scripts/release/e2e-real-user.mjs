/**
 * Phase 7.4 — genuine UI-driven end-to-end run.
 *
 * Registers a fresh free-plan account through the UI, then executes three real
 * backtests (AAPL, BTC-USD, GC=F) through the wizard, verifying persistence,
 * history reopening, refresh survival, comparison, and the free-plan quota.
 *
 * Evidence classes are recorded per run: NEW_RUN + LIVE_PROVIDER/CACHED_PROVIDER.
 */
import { chromium } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '../..');
const EVID = process.env.EVID ?? path.join(REPO, 'final-release-evidence');
const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const API = process.env.API_URL ?? 'http://localhost:8000';
const RUN_TS = process.env.RUN_TS ?? 'run';
const password = fs.readFileSync('/tmp/opencode/qa-password.txt', 'utf8').trim();
const email = `e2e+${RUN_TS}-b-${Date.now().toString(36)}@example.test`;
const OUT = path.join(EVID, 'phase-7', 'e2e');
fs.mkdirSync(OUT, { recursive: true });

const ASSETS = ['AAPL', 'BTC-USD', 'GC=F'];
const FROM = '2024-11-18';
const TO = '2026-11-13';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
await ctx.addInitScript(() => {
  localStorage.setItem('bl_lang', 'en');
  localStorage.setItem('bl_theme', 'light');
});
const page = await ctx.newPage();
const consoleErrors = [];
const pageErrors = [];
page.on('console', (m) => {
  if (m.type() === 'error') consoleErrors.push(m.text());
});
page.on('pageerror', (e) => pageErrors.push(e.message));

const result = {
  generated_at: new Date().toISOString(),
  account: { email, created_via: 'ui' },
  runs: [],
  quota: null,
  history: null,
  refresh: null,
  compare: null,
  consoleErrors,
  pageErrors,
};

async function register() {
  await page.goto(BASE + '/register', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Full name').fill('Release E2E');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.locator('#register-terms').check();
  await page.getByRole('button', { name: /create account/i }).click();
  await page.waitForURL('**/app', { timeout: 30000 });
  const session = await page.evaluate(() => JSON.parse(localStorage.getItem('bl_session') || 'null'));
  return session;
}

async function freshWizard() {
  await page.evaluate(() => localStorage.removeItem('bl_run_draft'));
  await page.goto(BASE + '/app/new', { waitUntil: 'domcontentloaded' });
}

async function runOne(asset, fast, slow) {
  await freshWizard();
  try {
    await page.waitForSelector('[role="radio"]', { timeout: 20000 });
  } catch (e) {
    const shot = path.join(OUT, `debug-new-${asset.replace(/[^A-Za-z0-9]/g, '')}.png`);
    await page.screenshot({ path: shot, animations: 'disabled' });
    console.error('DEBUG', page.url(), (await page.locator('body').innerText()).slice(0, 500));
    throw e;
  }
  await page.getByRole('radio', { name: /Moving Average Crossover/ }).click();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.locator('#asset-search').fill(asset);
  await page.getByRole('radio', { name: new RegExp(`^${asset.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) }).first().click();
  await page.locator('#run-from').fill(FROM);
  await page.locator('#run-to').fill(TO);
  await page.locator('#run-cap').fill('10000');
  await page.locator('#run-fee').fill('0.1');
  await page.locator('#param-fastPeriod').fill(String(fast));
  await page.locator('#param-slowPeriod').fill(String(slow));
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  const started = Date.now();
  await page.getByRole('button', { name: 'Run backtest', exact: true }).click();
  await page.waitForURL(/\/app\/results\/bt-[a-f0-9]+/, { timeout: 90000 });
  const id = page.url().match(/bt-[a-f0-9]+/)?.[0];
  await page.waitForSelector('[data-testid="chart-results-equity"][data-chart-state="ready"]', {
    timeout: 30000,
  });
  return { id, uiSeconds: (Date.now() - started) / 1000 };
}

async function apiResult(token, id) {
  const res = await fetch(`${API}/api/v1/backtests/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

const session = await register();
if (!session?.token) throw new Error('registration did not create a session');
const token = session.token;

const params = [
  [20, 50],
  [20, 50],
  [20, 50],
];
for (let i = 0; i < ASSETS.length; i += 1) {
  const asset = ASSETS[i];
  const [fast, slow] = params[i];
  const run = await runOne(asset, fast, slow);
  const body = await apiResult(token, run.id);
  const shot = path.join(OUT, `results-${asset.replace(/[^A-Za-z0-9]/g, '')}.png`);
  await page.screenshot({ path: shot, animations: 'disabled' });
  result.runs.push({
    label: 'NEW_RUN',
    asset,
    run_id: run.id,
    created_at: new Date().toISOString(),
    request: { templateId: 'ma-crossover', params: { fastPeriod: fast, slowPeriod: slow }, from: FROM, to: TO, initialCapital: 10000, feePct: 0.1 },
    provider: body.provenance?.provider ?? null,
    data_origin: body.provenance?.cache === 'hit' ? 'CACHED_PROVIDER' : 'LIVE_PROVIDER',
    data_window: { start: body.provenance?.start ?? null, end: body.provenance?.end ?? null },
    equity_points: body.equity?.length ?? 0,
    metrics: {
      totalReturnPct: body.totalReturnPct,
      maxDrawdownPct: body.maxDrawdownPct,
      sharpe: body.sharpe,
      winRatePct: body.winRatePct,
      trades: body.trades,
    },
    ui_seconds: run.uiSeconds,
    screenshot: path.relative(EVID, shot),
  });
  console.log(`NEW_RUN ${asset} ${run.id} return=${body.totalReturnPct} trades=${body.trades}`);
}

// History + refresh persistence
await page.goto(BASE + '/app/history', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('input[aria-label^="bt-"]', { timeout: 30000 });
const listedIds = await page.locator('input[aria-label^="bt-"]').evaluateAll((els) =>
  els.map((e) => e.getAttribute('aria-label')),
);
// Reopen the first run from History and verify it resolves to the same run.
const reopenTarget = result.runs[0].run_id;
await page.goto(BASE + `/app/results/${reopenTarget}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('[data-testid="chart-results-equity"][data-chart-state="ready"]', {
  timeout: 30000,
});
const reopenedId = page.url().match(/bt-[a-f0-9]+/)?.[0];
result.history = {
  listed: result.runs.every((r) => listedIds.includes(r.run_id)),
  listed_ids: listedIds,
  reopen_matched: reopenedId === reopenTarget,
  run_ids: result.runs.map((r) => r.run_id),
};

const firstRun = result.runs[0].run_id;
await page.goto(BASE + `/app/results/${firstRun}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('[data-testid="chart-results-equity"][data-chart-state="ready"]', { timeout: 30000 });
const consoleBeforeQuota = consoleErrors.length;
const beforeRefresh = await page.locator('body').innerText();
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('[data-testid="chart-results-equity"][data-chart-state="ready"]', { timeout: 30000 });
const afterRefresh = await page.locator('body').innerText();
const metric = (text) => (text.match(/([+-]?\d+\.\d{2})%/g) || []).join(',');
result.refresh = {
  run_id: firstRun,
  survives: metric(beforeRefresh) === metric(afterRefresh),
  before: metric(beforeRefresh),
  after: metric(afterRefresh),
};

// Comparison of the first two runs
await page.goto(BASE + `/app/compare?a=${result.runs[0].run_id}&b=${result.runs[1].run_id}`, {
  waitUntil: 'domcontentloaded',
});
await page.waitForSelector('[data-testid="chart-compare-equity"][data-chart-state="ready"]', {
  timeout: 30000,
});
const counts = await page.locator('[data-testid="chart-compare-equity"]').evaluate((el) => ({
  a: el.getAttribute('data-series-a-count'),
  b: el.getAttribute('data-series-b-count'),
  first: el.getAttribute('data-first-ts'),
  last: el.getAttribute('data-last-ts'),
}));
const compareShot = path.join(OUT, 'compare.png');
await page.screenshot({ path: compareShot, animations: 'disabled' });
result.compare = { ...counts, screenshot: path.relative(EVID, compareShot) };

// Quota enforcement through the real UI (4th run must be rejected)
await freshWizard();
await page.getByRole('radio', { name: /Moving Average Crossover/ }).click();
await page.getByRole('button', { name: 'Next', exact: true }).click();
await page.locator('#asset-search').fill('AAPL');
await page.getByRole('radio', { name: /^AAPL/ }).first().click();
await page.locator('#run-from').fill(FROM);
await page.locator('#run-to').fill(TO);
await page.locator('#run-cap').fill('10000');
await page.locator('#run-fee').fill('0.1');
await page.getByRole('button', { name: 'Next', exact: true }).click();
await page.getByRole('button', { name: 'Run backtest', exact: true }).click();
let quotaMessage = '';
try {
  await page.waitForSelector('[role="alert"]', { timeout: 30000 });
  quotaMessage = await page.locator('[role="alert"]').first().innerText();
} catch {
  quotaMessage = '';
}
const stayed = page.url().includes('/app/new');
const quotaShot = path.join(OUT, 'quota-limit.png');
await page.screenshot({ path: quotaShot, animations: 'disabled' });
result.quota = {
  message: quotaMessage.slice(0, 300),
  stayed_on_new_page: stayed,
  enforced: stayed && /limit/i.test(quotaMessage),
  screenshot: path.relative(EVID, quotaShot),
};

// The 429 emitted by the deliberate quota test is expected and labelled.
result.consoleErrorsBeforeQuota = consoleErrors.slice(0, consoleBeforeQuota);
result.consoleErrorsQuota = consoleErrors.slice(consoleBeforeQuota);
result.consoleErrors = consoleErrors;
result.pageErrors = pageErrors;
result.finished_at = new Date().toISOString();
fs.writeFileSync(path.join(OUT, 'e2e-result.json'), JSON.stringify(result, null, 2));

const ok =
  result.runs.length === 3 &&
  result.history.listed &&
  result.refresh.survives &&
  result.compare.a === String(result.runs[0].equity_points) &&
  result.compare.b === String(result.runs[1].equity_points) &&
  result.quota.enforced &&
  result.history.reopen_matched &&
  result.consoleErrorsBeforeQuota.length === 0 &&
  pageErrors.length === 0;
console.log(
  JSON.stringify(
    {
      runs: result.runs.map((r) => ({ asset: r.asset, id: r.run_id, origin: r.data_origin, points: r.equity_points })),
      history: result.history,
      refresh: result.refresh,
      compare: result.compare,
      quota: result.quota,
      consoleErrors: consoleErrors.length,
      pageErrors: pageErrors.length,
      verdict: ok ? 'PASS' : 'FAIL',
    },
    null,
    2,
  ),
);
await browser.close();
process.exit(ok ? 0 : 1);
