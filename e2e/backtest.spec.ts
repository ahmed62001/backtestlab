import { expect, test, type Page } from '@playwright/test';

/**
 * Phase 11 — real browser E2E.
 *
 * These tests run against the real FastAPI backend (SQLite + vendor engine,
 * seeded synthetic market data) and the real React app with VITE_USE_MOCK=false.
 * See playwright.config.ts and e2e/start-backend.sh.
 */

const PASSWORD = 'E2E-pass-12345';
const RAW_KEY_PATTERN = /\b(?:run|results|dataProviders|common|nav|auth)\.[a-zA-Z][a-zA-Z.]*/;

function uniqueEmail(): string {
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `e2e-${stamp}@backtestlab.test`;
}

async function register(page: Page, email = uniqueEmail(), name = 'E2E User') {
  await page.goto('/register');
  await page.getByLabel('Full name').fill(name);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/app$/);
  return email;
}

async function login(page: Page, email: string) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page).toHaveURL(/\/app$/);
}

async function openWizardStepTwo(page: Page) {
  await page.goto('/app/new');
  await expect(page.getByRole('radiogroup', { name: 'Strategy template' })).toBeVisible();
  await page.getByRole('radio', { name: /Moving Average Crossover/ }).click();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'Data provider', exact: true })).toBeVisible();
}

async function configureAapl(page: Page) {
  await page.getByRole('radiogroup', { name: 'Asset' }).getByRole('radio', { name: /AAPL/ }).click();
  await expect(page.getByRole('radio', { name: /Local data store/ })).toBeChecked();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'Review your backtest' })).toBeVisible();
}

async function runBacktest(page: Page) {
  await page.getByRole('button', { name: 'Run backtest' }).click();
  await expect(page).toHaveURL(/\/app\/results\/bt-/, { timeout: 60_000 });
  await expect(page.getByRole('heading', { name: 'Backtest results' })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  // Force a deterministic language/theme instead of the app's Arabic default.
  await page.addInitScript(() => {
    if (!localStorage.getItem('bl_lang')) localStorage.setItem('bl_lang', 'en');
    if (!localStorage.getItem('bl_theme')) localStorage.setItem('bl_theme', 'light');
  });
});

test('register, log out, log in, and see the seeded provider catalog', async ({ page }) => {
  const email = await register(page);

  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page).toHaveURL(/\/login/);
  await login(page, email);
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
});

test('provider catalog groups by category and disables unavailable providers', async ({ page }) => {
  await register(page);

  // A stale/invalid persisted provider choice must never be submittable:
  // the wizard re-resolves it to an enabled+available provider from the
  // server catalog (local_store is the configured default here).
  await page.addInitScript(() => {
    localStorage.setItem('bl_run_draft', JSON.stringify({ dataProvider: 'alphavantage', step: 0 }));
  });

  await openWizardStepTwo(page);

  await expect(page.getByRole('heading', { name: 'Equities', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Local / Offline', exact: true })).toBeVisible();

  const localStore = page.getByRole('radio', { name: /Local data store/ });
  await expect(localStore).toBeChecked();
  await expect(localStore).toBeEnabled();
  await expect(page.getByRole('radio', { name: /Synthetic \(seeded GBM/ })).toBeEnabled();

  const alphaVantage = page.getByRole('radio', { name: /Alpha Vantage/ });
  await expect(alphaVantage).toBeDisabled();
  await expect(page.getByText(/Unavailable:/).first()).toBeVisible();

  // Without an asset the wizard cannot advance even though a provider is valid.
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled();
});

test('runs a seeded local_store backtest and renders metrics + provenance', async ({ page }) => {
  await register(page);
  await openWizardStepTwo(page);
  await configureAapl(page);
  await runBacktest(page);

  for (const label of ['Total return', 'Max drawdown', 'Sharpe ratio', 'Win rate', 'Trades']) {
    await expect(page.getByText(label).first()).toBeVisible();
  }

  await expect(page.getByRole('heading', { name: 'Data Provenance' })).toBeVisible();
  await expect(page.getByText('local_store', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/^(Store|Live)$/).first()).toBeVisible();
  await expect(page.getByText(/^[0-9a-f]{64}$/).first()).toBeVisible();
});

test('shows a translated provider error when the store has no data for the range', async ({ page }) => {
  await register(page);
  await openWizardStepTwo(page);

  await page.getByLabel('Start date').fill('2015-01-01');
  await page.getByLabel('End date').fill('2016-12-31');
  await configureAapl(page);

  await page.getByRole('button', { name: 'Run backtest' }).click();

  const alert = page.getByRole('alert');
  await expect(alert).toContainText('No cached data available', { timeout: 60_000 });
  await expect(alert).toContainText('local_store');
  await expect(alert).not.toContainText('run.errors');
});

test('language switch applies RTL and leaves no untranslated keys', async ({ page }) => {
  await register(page);

  await page.getByRole('button', { name: 'Language' }).click();
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  // IA change (2026-11-13): the /app nav link is "Overview" / "نظرة عامة".
  await expect(page.getByRole('link', { name: 'نظرة عامة' })).toBeVisible();

  await page.goto('/app/new');
  await expect(page.getByRole('heading', { name: 'اختبار جديد' })).toBeVisible();
  const body = await page.locator('body').innerText();
  expect(body).not.toMatch(RAW_KEY_PATTERN);

  await page.getByRole('button', { name: 'اللغة' }).click();
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.getByRole('link', { name: 'Overview' })).toBeVisible();
});
