import { chromium } from '@playwright/test';
import fs from 'node:fs';

const BASE = 'http://localhost:5173';
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
await page.goto(BASE + '/app/asset/AAPL', { waitUntil: 'domcontentloaded' });

for (const ms of [500, 1000, 1500, 2000, 3000, 5000, 8000]) {
  await page.waitForTimeout(ms === 500 ? 500 : ms - (ms === 1000 ? 500 : 0));
  const s = await page.evaluate(() => {
    const svg = document.querySelector('svg.recharts-surface');
    if (!svg) return { t: Date.now(), svg: false };
    const paths = [...svg.querySelectorAll('path')];
    const byClass = {};
    for (const p of paths) {
      const c = p.getAttribute('class') || '(none)';
      byClass[c] = (byClass[c] || 0) + 1;
    }
    const area = paths.find((p) => (p.getAttribute('class') || '').includes('area'));
    const areaD = area ? area.getAttribute('d') : null;
    return {
      svg: true,
      byClass,
      areaLen: areaD ? areaD.length : 0,
      areaHead: areaD ? areaD.slice(0, 120) : null,
      lastPoint: areaD ? areaD.slice(-80) : null,
      rects: svg.querySelectorAll('rect.recharts-rectangle').length,
      tickText: [...svg.querySelectorAll('.recharts-xAxis .recharts-cartesian-axis-tick-value')].slice(-2).map((n) => n.textContent),
    };
  });
  console.log(ms + 'ms', JSON.stringify(s));
}
await browser.close();
