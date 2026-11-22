import { expect, test, type Page } from '@playwright/test';

/**
 * Streaming E2E — MOCKED provider (fake Twelve Data upstream), real app end to end.
 *
 * The backend runs with TWELVEDATA_WS_URL pointing at e2e/fake-td.py, which
 * emits periodic price events with an incremented price. This proves the
 * forwarding path (fake provider -> backend manager -> authenticated frontend
 * WebSocket -> visible UI update). It does NOT prove real-provider data;
 * real-provider browser verification is BLOCKED on credentials (see
 * docs/MARKET_STREAMING_IMPLEMENTATION_REPORT.md).
 */

const PASSWORD = 'E2E-pass-12345';

function uniqueEmail(): string {
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `e2e-stream-${stamp}@backtestlab.test`;
}

async function register(page: Page, email = uniqueEmail()) {
  await page.goto('/register');
  await page.getByLabel('Full name').fill('E2E Stream User');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/app$/);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('bl_lang')) localStorage.setItem('bl_lang', 'en');
    if (!localStorage.getItem('bl_theme')) localStorage.setItem('bl_theme', 'light');
  });
});

test('live ticks reach the browser and update a visible price (mocked provider)', async ({ page }) => {
  await register(page);

  const tape = page.getByTestId('ticker-tape');
  await expect(tape).toBeVisible();

  // The tape must show a LIVE marker once ticks arrive through the backend WS.
  await expect(tape.getByText(/LIVE/i).first()).toBeVisible({ timeout: 25_000 });

  // The AAPL tape price must visibly change as incremented ticks arrive.
  const aapl = tape.getByRole('link', { name: /AAPL/ }).first();
  await expect(aapl).toBeVisible();
  const before = (await aapl.textContent()) ?? '';
  await page.waitForTimeout(2500);
  const after = (await aapl.textContent()) ?? '';
  expect(after).not.toEqual(before);

  // The asset page shows the LIVE indicator too.
  await aapl.click();
  await expect(page).toHaveURL(/\/app\/asset\/AAPL/);
  await expect(page.getByText(/LIVE/i).first()).toBeVisible({ timeout: 25_000 });
});
