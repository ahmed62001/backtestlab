/**
 * Application-aware chart readiness helpers (Sections 0.8-A / 6.2).
 *
 * A chart cell is only READY when:
 *  - the API response for the chart has completed successfully,
 *  - the container reports data-chart-state="ready",
 *  - data-point-count equals the API's valid point count,
 *  - the plotted series path has a non-empty `d` with finite coordinates,
 *  - its bounding box has non-zero width and height (when variance > 0),
 *  - the geometry is stable across two consecutive animation frames,
 *  - no loading overlay remains.
 *
 * `page.waitForLoadState('networkidle')` is never used as the readiness proof.
 */

const NUM_RE = /-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi;

export function parsePathNumbers(d) {
  if (!d) return [];
  return (d.match(NUM_RE) || []).map(Number);
}

/** Validate an SVG path's coordinates and compute its bounding box. */
export function validatePath(d) {
  const numbers = parsePathNumbers(d);
  if (numbers.length < 4) return { ok: false, reason: 'path-too-short', count: numbers.length };
  if (numbers.some((n) => !Number.isFinite(n))) {
    return { ok: false, reason: 'non-finite-coordinate', count: numbers.length };
  }
  const xs = [];
  const ys = [];
  for (let i = 0; i + 1 < numbers.length; i += 2) {
    xs.push(numbers[i]);
    ys.push(numbers[i + 1]);
  }
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  return { ok: true, count: numbers.length, width, height, xs, ys };
}

async function readChart(container) {
  return container.evaluate((root) => {
    const svg = root.querySelector('svg.recharts-surface');
    if (!svg) return { hasSvg: false };
    const paths = [...svg.querySelectorAll('path')];
    const series = paths
      .filter((p) => {
        const c = p.getAttribute('class') || '';
        return c.includes('recharts-area-curve') || c.includes('recharts-line-curve');
      })
      .map((p) => p.getAttribute('d') || '');
    const areaFill = paths
      .filter((p) => (p.getAttribute('class') || '').includes('recharts-area-area'))
      .map((p) => p.getAttribute('d') || '');
    const box = svg.getBoundingClientRect();
    const loadingOverlay = root.querySelector('[data-chart-loading], .recharts-loading, [role="status"]');
    return {
      hasSvg: true,
      width: box.width,
      height: box.height,
      seriesPaths: series,
      areaPaths: areaFill,
      hasLoadingOverlay: Boolean(loadingOverlay),
      attrs: Object.fromEntries(
        [...root.attributes].filter((a) => a.name.startsWith('data-')).map((a) => [a.name, a.value]),
      ),
    };
  });
}

/**
 * Wait for a chart container to be genuinely ready.
 * @param {import('@playwright/test').Page} page
 * @param {{testId: string, expectedPoints?: number, apiPattern?: RegExp, timeoutMs?: number}} opts
 */
export async function waitForChartReady(page, opts) {
  const { testId, expectedPoints, apiResponsePromise, timeoutMs = 30000 } = opts;
  const selector = `[data-testid="${testId}"]`;
  const started = Date.now();
  const checks = {};
  let lastError = null;

  try {
    await page.waitForSelector(selector, { timeout: timeoutMs });
    checks.containerFound = true;

    await page.waitForFunction(
      (sel) => {
        const el = document.querySelector(sel);
        return el && el.getAttribute('data-chart-state') === 'ready';
      },
      selector,
      { timeout: timeoutMs, polling: 100 },
    );
    checks.stateReady = true;

    const apiResponse = apiResponsePromise ? await apiResponsePromise.catch(() => null) : null;
    checks.apiOk = Boolean(apiResponse) || !apiResponsePromise;

    // Geometry stable across two consecutive frames.
    let prev = null;
    let stable = false;
    let finalSnap = null;
    let finalGeo = null;
    for (let i = 0; i < 120 && Date.now() - started < timeoutMs; i += 1) {
      const el = await page.$(selector);
      const snap = await readChart(el);
      const d = snap.seriesPaths?.[0] || snap.areaPaths?.[0] || '';
      const geo = validatePath(d);
      if (prev === d && geo.ok) {
        stable = true;
        finalSnap = snap;
        finalGeo = geo;
        break;
      }
      prev = d;
      await page.evaluate(
        () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
      );
    }
    checks.geometryStable = stable;
    if (!stable) lastError = 'geometry did not stabilise';

    const attrs = finalSnap?.attrs || {};
    checks.pointCount = Number(attrs['data-point-count'] || 0);
    checks.firstTs = attrs['data-first-ts'] || null;
    checks.lastTs = attrs['data-last-ts'] || null;
    checks.chartState = attrs['data-chart-state'] || null;
    checks.seriesCount = finalSnap?.seriesPaths?.length || 0;
    checks.areaCount = finalSnap?.areaPaths?.length || 0;
    checks.pathNumbers = finalGeo?.count || 0;
    checks.pathBBox = finalGeo ? { width: finalGeo.width, height: finalGeo.height } : null;
    checks.svgSize = finalSnap ? { width: finalSnap.width, height: finalSnap.height } : null;
    checks.noLoadingOverlay = !finalSnap?.hasLoadingOverlay;
    checks.attrs = attrs;

    if (checks.chartState !== 'ready') lastError = `state=${checks.chartState}`;
    if (expectedPoints !== undefined && checks.pointCount !== expectedPoints) {
      lastError = `point-count ${checks.pointCount} != api ${expectedPoints}`;
    }
    if (apiResponse) {
      const body = await apiResponse.json().catch(() => null);
      const apiPoints = body
        ? (body.bars?.length ?? body.candles?.length ?? body.equity?.length ?? null)
        : null;
      checks.apiPoints = apiPoints;
      if (apiPoints !== null && apiPoints !== checks.pointCount) {
        lastError = `chart ${checks.pointCount} != api ${apiPoints}`;
      }
      const bars = body?.bars ?? body?.candles ?? null;
      if (Array.isArray(bars) && bars.length > 0) {
        const valid = bars.filter((b) => Number.isFinite(Number(b.c)));
        if (valid.length > 0) {
          const apiFirst = Number(valid[0].c);
          const apiLast = Number(valid[valid.length - 1].c);
          const chartFirst = Number(attrs['data-first-value']);
          const chartLast = Number(attrs['data-last-value']);
          checks.apiFirstValue = apiFirst;
          checks.apiLastValue = apiLast;
          checks.chartFirstValue = chartFirst;
          checks.chartLastValue = chartLast;
          if (Number.isFinite(chartFirst) && Math.abs(chartFirst - apiFirst) > 1e-6) {
            lastError = `first value ${chartFirst} != api ${apiFirst}`;
          }
          if (Number.isFinite(chartLast) && Math.abs(chartLast - apiLast) > 1e-6) {
            lastError = `last value ${chartLast} != api ${apiLast}`;
          }
        }
      }
    }
    if (!checks.pathBBox || (checks.pathBBox.width <= 0 && checks.pathBBox.height <= 0)) {
      lastError = 'zero-size plotted geometry';
    }
    const ok = Object.values(checks).every((v) => v !== false) && !lastError;
    return { ok, testId, checks, error: lastError, durationMs: Date.now() - started };
  } catch (e) {
    return {
      ok: false,
      testId,
      checks,
      error: `${e.name || 'error'}: ${String(e.message || e).slice(0, 300)}`,
      durationMs: Date.now() - started,
    };
  }
}

/** Collect console errors and failed requests for a page. */
export function collectDiagnostics(page) {
  const consoleErrors = [];
  const failedRequests = [];
  const pageErrors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('requestfailed', (r) =>
    failedRequests.push({ url: r.url(), failure: r.failure()?.errorText }),
  );
  page.on('response', (r) => {
    if (r.status() >= 400 && r.url().includes('/api/')) {
      failedRequests.push({ url: r.url(), status: r.status() });
    }
  });
  return { consoleErrors, failedRequests, pageErrors };
}
