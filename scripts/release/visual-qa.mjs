/**
 * Phase 6 — application-aware visual QA matrix.
 *
 * Generates a plan from the route inventory, captures every cell, validates
 * real chart geometry before declaring a cell PASS, records diagnostics, and
 * writes screenshots/manifest.json. Exits non-zero if any cell fails.
 *
 * Negative control: `--negative-control` injects an empty series for the
 * landing chart and expects the harness to FAIL that cell (proving it detects
 * an empty chart rather than merely a missing PNG).
 */
import { chromium } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { waitForChartReady, collectDiagnostics } from './chartReady.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '../..');
const EVID = process.env.EVID ?? path.join(REPO, 'final-release-evidence');
const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const API = process.env.API_URL ?? 'http://localhost:8000';
const NEGATIVE = process.argv.includes('--negative-control');
const OUTDIR = path.join(EVID, 'screenshots');
const SHOTDIR = path.join(OUTDIR, NEGATIVE ? 'negative-control' : 'matrix');

const ASSETS = ['AAPL', 'BTC-USD', 'GC=F'];
const LOCALES = ['en', 'ar'];
const THEMES = ['light', 'dark'];
const VIEWPORTS = [
  { id: 'desktop', width: 1440, height: 900 },
  { id: 'mobile', width: 390, height: 844 },
];
const RUN_A = process.env.RUN_A ?? 'bt-81358b1f';
const RUN_B = process.env.RUN_B ?? 'bt-4b48f039';

const PLAIN_PAGES = [
  { key: 'markets', route: '/app/markets' },
  { key: 'new-backtest', route: '/app/new' },
  { key: 'results', route: `/app/results/${RUN_A}` },
  { key: 'compare', route: `/app/compare?a=${RUN_A}&b=${RUN_B}` },
  { key: 'history', route: '/app/history' },
  { key: 'settings', route: '/app/settings' },
];

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
  if (!res.ok) throw new Error(`login ${res.status}`);
  const d = await res.json();
  return { token: d.token ?? d.access_token, refreshToken: d.refresh_token, user: d.user };
}

async function fetchApiSeries(cell, session) {
  if (!cell.testId) return null;
  let url;
  if (cell.key === 'landing') {
    url = `${API}/api/v1/public/market/series?symbol=${encodeURIComponent(cell.publicSymbol)}&interval=1D&limit=250`;
  } else {
    const symbol = cell.key === 'dashboard' ? 'GC=F' : cell.asset;
    url = `${API}/api/v1/market/series?symbol=${encodeURIComponent(symbol)}&interval=1D&days=365`;
  }
  const headers = cell.key === 'landing' ? {} : { Authorization: `Bearer ${session.token}` };
  const res = await fetch(url, { headers });
  if (!res.ok) return { status: res.status, points: null };
  const body = await res.json();
  const bars = body.bars ?? body.candles ?? [];
  const valid = bars.filter((b) => Number.isFinite(Number(b.c)));
  return {
    status: res.status,
    points: bars.length,
    validPoints: valid.length,
    firstValue: valid.length ? Number(valid[0].c) : null,
    lastValue: valid.length ? Number(valid[valid.length - 1].c) : null,
    firstTs: bars.length ? bars[0].t : null,
    lastTs: bars.length ? bars[bars.length - 1].t : null,
  };
}

function buildPlan() {
  const cells = [];
  for (const locale of LOCALES) {
    for (const theme of THEMES) {
      for (const vp of VIEWPORTS) {
        for (const asset of ASSETS) {
          cells.push({
            key: 'landing',
            route: '/',
            asset,
            testId: 'chart-public-1d',
            auth: false,
            locale,
            theme,
            viewport: vp.id,
            width: vp.width,
            height: vp.height,
            publicSymbol: asset,
          });
        }
        cells.push({
          key: 'dashboard',
          route: '/app',
          asset: 'GC=F',
          testId: 'chart-dashboard-1d',
          auth: true,
          locale,
          theme,
          viewport: vp.id,
          width: vp.width,
          height: vp.height,
        });
        for (const asset of ASSETS) {
          cells.push({
            key: 'asset',
            route: `/app/asset/${encodeURIComponent(asset)}`,
            asset,
            testId: 'chart-price-1d',
            auth: true,
            locale,
            theme,
            viewport: vp.id,
            width: vp.width,
            height: vp.height,
          });
        }
        for (const p of PLAIN_PAGES) {
          cells.push({
            key: p.key,
            route: p.route,
            asset: null,
            testId: null,
            auth: true,
            locale,
            theme,
            viewport: vp.id,
            width: vp.width,
            height: vp.height,
          });
        }
      }
    }
  }
  return cells;
}

function sha256File(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

async function genericReady(page) {
  await page.waitForFunction(() => {
    const h1 = document.querySelector('h1');
    if (!h1) return false;
    if (document.querySelectorAll('.animate-pulse').length > 0) return false;
    return true;
  }, null, { timeout: 30000, polling: 150 });
  await page.evaluate(() => (document.fonts ? document.fonts.ready : Promise.resolve()));
}

async function visualChecks(page, locale, chartTestId) {
  return page.evaluate(
    ({ locale, chartTestId }) => {
      const de = document.documentElement;
      const overflow = de.scrollWidth - de.clientWidth;
      const dir = de.getAttribute('dir');
      const lang = de.getAttribute('lang');
      const h1 = document.querySelector('h1')?.textContent?.trim() || '';
      // Text clipping: ignore elements that intentionally truncate.
      let clipped = 0;
      const nodes = [...document.querySelectorAll('p,h2,h3,td,th,label,dd,dt')];
      for (const n of nodes) {
        const style = getComputedStyle(n);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        if (n.closest('.truncate') || n.classList.contains('truncate')) continue;
        if (n.scrollWidth > n.clientWidth + 2 && n.clientWidth > 0) clipped += 1;
      }
      // Identify what actually widens the document (diagnostics only).
      const offenders = [];
      if (overflow > 1) {
        for (const n of document.querySelectorAll('body *')) {
          const r = n.getBoundingClientRect();
          if (r.right > de.clientWidth + 1 || r.left < -1) {
            const style = getComputedStyle(n);
            if (style.position === 'fixed' && style.visibility === 'hidden') continue;
            offenders.push({
              tag: n.tagName.toLowerCase(),
              cls: String(n.className || '').slice(0, 80),
              right: Math.round(r.right),
              left: Math.round(r.left),
              width: Math.round(r.width),
            });
            if (offenders.length >= 5) break;
          }
        }
      }
      // Locale-correct digits: the product uses Western digits in both locales.
      const bodyText = document.body.innerText || '';
      const arabicDigits = /[٠-٩]/.test(bodyText);
      const rawI18n = /\b[a-z]+\.[a-z]+\.[a-z]+\b/.test(bodyText) && bodyText.includes('market.');
      // Chart-label contrast (axis ticks vs page background).
      let contrast = null;
      if (chartTestId) {
        const tick = document.querySelector(
          `[data-testid="${chartTestId}"] .recharts-cartesian-axis-tick-value`,
        );
        if (tick) {
          const fg = getComputedStyle(tick).fill || getComputedStyle(tick).color;
          const bg = getComputedStyle(document.body).backgroundColor;
          const parse = (c) => {
            const m = c.match(/rgba?\(([^)]+)\)/);
            if (!m) return null;
            const [r, g, b] = m[1].split(',').map((x) => parseFloat(x));
            return [r, g, b];
          };
          const lum = ([r, g, b]) => {
            const f = (v) => {
              v /= 255;
              return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            };
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          const a = parse(fg);
          const b = parse(bg);
          if (a && b) {
            const la = lum(a);
            const lb = lum(b);
            contrast = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
          }
        }
      }
      return {
        overflowPx: overflow,
        dir,
        lang,
        h1,
        clippedElements: clipped,
        overflowOffenders: offenders,
        arabicDigits,
        rawI18nKeys: rawI18n,
        axisContrast: contrast,
        hasChartContainer: chartTestId ? Boolean(document.querySelector(`[data-testid="${chartTestId}"]`)) : null,
      };
    },
    { locale, chartTestId },
  );
}

async function hoverTooltip(page, chartTestId) {
  const el = await page.$(`[data-testid="${chartTestId}"] svg.recharts-surface`);
  if (!el) return { ok: false, reason: 'no-svg' };
  await el.scrollIntoViewIfNeeded().catch(() => {});
  const box = await el.boundingBox();
  if (!box) return { ok: false, reason: 'no-box' };
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.4);
  try {
    await page.waitForSelector('.recharts-tooltip-wrapper', { state: 'visible', timeout: 4000 });
    const text = await page.$eval('.recharts-tooltip-wrapper', (n) => n.textContent || '');
    return { ok: text.trim().length > 0, text: text.slice(0, 120) };
  } catch {
    return { ok: false, reason: 'tooltip-not-visible' };
  }
}

async function captureCell(browser, cell, session) {
  const started = Date.now();
  const context = await browser.newContext({
    viewport: { width: cell.width, height: cell.height },
    locale: cell.locale === 'ar' ? 'ar-SA' : 'en-US',
    colorScheme: cell.theme,
    deviceScaleFactor: 1,
  });
  if (cell.auth && session) {
    await context.addInitScript(
      ([s, lang, theme]) => {
        localStorage.setItem('bl_session', JSON.stringify(s));
        localStorage.setItem('bl_lang', lang);
        localStorage.setItem('bl_theme', theme);
      },
      [session, cell.locale, cell.theme],
    );
  } else {
    await context.addInitScript(
      ([lang, theme]) => {
        localStorage.setItem('bl_lang', lang);
        localStorage.setItem('bl_theme', theme);
      },
      [cell.locale, cell.theme],
    );
  }
  const page = await context.newPage();
  const diag = collectDiagnostics(page);
  const record = {
    route: cell.route,
    page: cell.key,
    asset: cell.asset,
    locale: cell.locale,
    theme: cell.theme,
    viewport: cell.viewport,
    viewportSize: { width: cell.width, height: cell.height },
    status: 'FAIL',
    readiness: null,
    api: { status: null, points: null },
    expected: { points: null, firstTs: null, lastTs: null },
    actual: { points: null, firstTs: null, lastTs: null },
    visual: null,
    tooltip: null,
    consoleErrors: [],
    failedRequests: [],
    screenshot: null,
    screenshotSha256: null,
    durationMs: 0,
    retries: 0,
    error: null,
  };

  try {
    if (cell.key === 'landing' && NEGATIVE) {
      await page.route('**/api/v1/public/market/series*', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            symbol: cell.publicSymbol,
            displayName: cell.publicSymbol,
            assetClass: 'equity',
            currency: 'USD',
            provider: 'yfinance',
            interval: '1D',
            candles: [],
            lastCandleTime: null,
            retrievedAt: new Date().toISOString(),
            dataStatus: 'delayed',
            cacheAgeSeconds: 0,
          }),
        }),
      );
    }

    await page.goto(BASE + cell.route, { waitUntil: 'domcontentloaded' });
    if (cell.key === 'landing') {
      const select = page.locator('select').first();
      await select.waitFor({ state: 'visible', timeout: 20000 });
      await page.waitForFunction(
        () => {
          const el = document.querySelector('select');
          return el && !el.disabled;
        },
        null,
        { timeout: 30000, polling: 150 },
      );
      await select.selectOption(cell.publicSymbol);
      // The public chart exposes its own readiness state (empty/error/ready).
      await page.waitForFunction(
        () => {
          const el = document.querySelector('[data-testid="chart-public-state"]');
          const s = el?.getAttribute('data-chart-state');
          return s === 'ready' || s === 'empty' || s === 'error';
        },
        null,
        { timeout: 45000, polling: 150 },
      );
      const state = await page.getAttribute('[data-testid="chart-public-state"]', 'data-chart-state');
      if (state !== 'ready') throw new Error(`chart not ready: state=${state}`);
    }

    if (cell.testId) {
      const r = await waitForChartReady(page, { testId: cell.testId, timeoutMs: 45000 });
      record.readiness = r;
      const api = await fetchApiSeries(cell, session);
      record.api = { status: api?.status ?? null, points: api?.points ?? null };
      record.expected.points = api?.validPoints ?? null;
      record.expected.firstTs = api?.firstTs ?? null;
      record.expected.lastTs = api?.lastTs ?? null;
      record.actual.points = r.checks?.pointCount ?? null;
      record.actual.firstTs = r.checks?.firstTs ?? null;
      record.actual.lastTs = r.checks?.lastTs ?? null;
      if (r.ok && api && api.validPoints !== null && api.validPoints !== record.actual.points) {
        r.ok = false;
        r.error = `chart ${record.actual.points} != api ${api.validPoints}`;
      }
      if (r.ok && api && Number.isFinite(api.firstValue)) {
        const cf = Number(r.checks?.attrs?.['data-first-value']);
        const cl = Number(r.checks?.attrs?.['data-last-value']);
        if (Number.isFinite(cf) && Math.abs(cf - api.firstValue) > 1e-6) {
          r.ok = false;
          r.error = `first value ${cf} != api ${api.firstValue}`;
        }
        if (Number.isFinite(cl) && Math.abs(cl - api.lastValue) > 1e-6) {
          r.ok = false;
          r.error = `last value ${cl} != api ${api.lastValue}`;
        }
      }
      if (r.ok) {
        record.tooltip = await hoverTooltip(page, cell.testId);
      }
    } else {
      await genericReady(page);
      record.readiness = { ok: true, checks: { genericReady: true } };
    }

    record.visual = await visualChecks(page, cell.locale, cell.testId);
    record.consoleErrors = diag.consoleErrors;
    // A request superseded by an explicit symbol switch is aborted by the app
    // (AbortController). That is correct behaviour, not a failed request.
    record.abortedRequests = diag.failedRequests.filter(
      (r) => r.failure === 'net::ERR_ABORTED',
    );
    record.failedRequests = diag.failedRequests.filter(
      (r) => r.failure !== 'net::ERR_ABORTED',
    );

    const fileName = `${cell.key}-${(cell.asset ?? 'all').replace(/[^A-Za-z0-9]/g, '')}__${cell.locale}__${cell.theme}__${cell.viewport}.png`;
    const shotPath = path.join(SHOTDIR, fileName);
    fs.mkdirSync(SHOTDIR, { recursive: true });
    await page.screenshot({ path: shotPath, animations: 'disabled', fullPage: false });
    record.screenshot = path.relative(EVID, shotPath);
    record.screenshotSha256 = sha256File(shotPath);

    const chartOk = cell.testId ? Boolean(record.readiness?.ok) : true;
    const visualOk =
      record.visual.overflowPx <= 1 &&
      !record.visual.arabicDigits &&
      !record.visual.rawI18nKeys &&
      (record.visual.axisContrast === null || record.visual.axisContrast >= 3) &&
      (cell.locale === 'en' ? record.visual.dir !== 'rtl' : record.visual.dir === 'rtl');
    const tooltipOk = cell.testId ? Boolean(record.tooltip?.ok) : true;
    const clean = diag.consoleErrors.length === 0 && record.failedRequests.length === 0;
    record.status = chartOk && visualOk && tooltipOk && clean ? 'PASS' : 'FAIL';
    if (!chartOk) record.error = record.readiness?.error ?? 'chart not ready';
    else if (!visualOk) record.error = 'visual check failed';
    else if (!tooltipOk) record.error = 'tooltip check failed';
    else if (!clean) record.error = 'console/failed requests';
  } catch (e) {
    record.error = `${e.name || 'error'}: ${String(e.message || e).slice(0, 300)}`;
    record.consoleErrors = diag.consoleErrors;
    record.failedRequests = diag.failedRequests;
    try {
      const shotPath = path.join(SHOTDIR, `FAILED-${cell.key}-${cell.locale}-${cell.theme}-${cell.viewport}.png`);
      fs.mkdirSync(SHOTDIR, { recursive: true });
      await page.screenshot({ path: shotPath, animations: 'disabled' });
      record.screenshot = path.relative(EVID, shotPath);
      record.screenshotSha256 = sha256File(shotPath);
    } catch {
      /* capture is best-effort */
    }
  } finally {
    record.durationMs = Date.now() - started;
    await context.close();
  }
  return record;
}

const session = await login();
const plan = buildPlan();
fs.mkdirSync(OUTDIR, { recursive: true });
fs.writeFileSync(
  path.join(OUTDIR, NEGATIVE ? 'plan-negative-control.json' : 'plan.json'),
  JSON.stringify({ generated_at: new Date().toISOString(), cells: plan }, null, 2),
);

const browser = await chromium.launch();
const results = [];
const targets = NEGATIVE ? plan.filter((c) => c.key === 'landing' && c.asset === 'AAPL' && c.locale === 'en' && c.theme === 'light' && c.viewport === 'desktop') : plan;

for (const cell of targets) {
  let rec = await captureCell(browser, cell, session);
  if (rec.status === 'FAIL' && !NEGATIVE) {
    rec.retries = 1;
    const retry = await captureCell(browser, cell, session);
    retry.retries = 1;
    rec = retry;
  }
  results.push(rec);
  console.log(`${rec.status} ${rec.page}/${rec.asset ?? '-'} ${rec.locale}/${rec.theme}/${rec.viewport} ${rec.error ?? ''}`);
}

await browser.close();

const manifestPath = path.join(OUTDIR, NEGATIVE ? 'manifest-negative-control.json' : 'manifest.json');
fs.writeFileSync(
  manifestPath,
  JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      negative_control: NEGATIVE,
      total: results.length,
      passed: results.filter((r) => r.status === 'PASS').length,
      failed: results.filter((r) => r.status === 'FAIL').length,
      cells: results,
    },
    null,
    2,
  ),
);

const failed = results.filter((r) => r.status === 'FAIL');
if (NEGATIVE) {
  // The negative control is a success when the harness detects the empty chart.
  const detected = failed.length === 1 && /chart not ready|point-count|state=empty/.test(failed[0].error ?? '');
  console.log(`NEGATIVE_CONTROL ${detected ? 'DETECTED' : 'MISSED'} failures=${failed.length}`);
  process.exit(detected ? 0 : 1);
}
console.log(`MATRIX total=${results.length} passed=${results.length - failed.length} failed=${failed.length}`);
process.exit(failed.length ? 1 : 0);
