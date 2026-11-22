import { chromium } from '@playwright/test';
import fs from 'node:fs';

const BASE = 'http://localhost:5173';
const OUT = process.env.OUT_DIR || './final-release-evidence/phase-1';
const email = fs.readFileSync('/tmp/opencode/email.txt', 'utf8').trim();
const token = fs.readFileSync('/tmp/opencode/token.txt', 'utf8').trim();

const user = { id: 'u-5770e7ca', name: 'Release QA', email, plan: 'free', language: 'en', createdAt: new Date().toISOString() };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
await ctx.addInitScript(([t, u]) => {
  localStorage.setItem('bl_session', JSON.stringify({ token: t, user: u, refreshToken: '' }));
  localStorage.setItem('bl_lang', 'en');
  localStorage.setItem('bl_theme', 'light');
}, [token, user]);
const page = await ctx.newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

async function inspectChart(where, testid) {
  return page.evaluate(({ where, testid }) => {
    const root = testid ? document.querySelector(`[data-testid="${testid}"]`) : document;
    const svg = (root || document).querySelector('svg.recharts-surface');
    const paths = svg ? [...svg.querySelectorAll('path')] : [];
    const areas = paths.map((p) => ({ cls: p.getAttribute('class'), d: p.getAttribute('d'), fill: p.getAttribute('fill'), stroke: p.getAttribute('stroke') }));
    const wrapper = svg ? svg.closest('.recharts-wrapper') : null;
    return {
      where,
      testid,
      hasChart: !!svg,
      svgBox: svg ? (() => { const b = svg.getBoundingClientRect(); return { w: b.width, h: b.height }; })() : null,
      wrapperBox: wrapper ? (() => { const b = wrapper.getBoundingClientRect(); return { w: b.width, h: b.height }; })() : null,
      pathCount: paths.length,
      nonEmptyPaths: areas.filter((a) => a.d && a.d.length > 10).length,
      areas: areas.slice(0, 12),
      xTicks: [...(svg ? svg.querySelectorAll('.recharts-xAxis .recharts-cartesian-axis-tick-value') : [])].slice(0, 8).map((n) => n.textContent),
      dotCount: svg ? svg.querySelectorAll('.recharts-area-dot').length : 0,
    };
  }, { where, testid });
}

const results = {};

// Dashboard
const apiCalls = [];
page.on('response', async (r) => {
  if (r.url().includes('/api/v1/market/')) {
    let len = -1, pts = -1;
    try { const j = await r.json(); len = JSON.stringify(j).length; pts = Array.isArray(j.bars) ? j.bars.length : Array.isArray(j.candles) ? j.candles.length : -1; } catch {}
    apiCalls.push({ url: r.url(), status: r.status(), bodyBytes: len, points: pts });
  }
});
await page.goto(BASE + '/app', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(6000);
results.dashboard = await inspectChart('dashboard');
await page.screenshot({ path: OUT + '/before-dashboard.png', fullPage: false });
results.dashboardApi = apiCalls.filter((c) => c.url.includes('series'));

// Asset pages
for (const sym of ['AAPL', 'GC=F']) {
  apiCalls.length = 0;
  await page.goto(BASE + '/app/asset/' + encodeURIComponent(sym), { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6000);
  results['asset-' + sym] = await inspectChart('asset-' + sym);
  results['asset-' + sym + 'Api'] = apiCalls.filter((c) => c.url.includes('series'));
  await page.screenshot({ path: OUT + `/before-asset-${sym.replace(/[^A-Za-z0-9]/g, '')}.png`, fullPage: false });
}
results.consoleErrors = consoleErrors;
fs.mkdirSync(OUT + '/json', { recursive: true });
fs.writeFileSync(OUT + '/json/before-chart-trace.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2).slice(0, 9000));
await browser.close();
