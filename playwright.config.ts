import { defineConfig, devices } from '@playwright/test';

/**
 * Phase 11 — real-browser E2E against the real backend.
 *
 * The backend webServer runs e2e/start-backend.sh: a throwaway SQLite database
 * seeded with deterministic synthetic bars, ENGINE_MODE=vendor, and
 * local_store as the default provider. The frontend runs Vite with
 * VITE_USE_MOCK=false so every request hits the API.
 */
const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5173);
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 75_000,
  expect: { timeout: 20_000 },
  retries: process.env.CI ? 1 : 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: WEB_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'python3 e2e/fake-td.py',
      url: 'http://127.0.0.1:9451/health',
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: 'bash e2e/start-backend.sh',
      url: `${API_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        E2E_API_PORT: String(API_PORT),
        TWELVEDATA_API_KEY: 'fake-e2e-key',
        TWELVEDATA_WS_URL: 'ws://127.0.0.1:9451/v1/quotes/price',
        MARKET_STREAMING_ENABLED: 'true',
        MARKET_STREAM_MAX_SUBSCRIPTIONS: '8',
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: WEB_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        VITE_USE_MOCK: 'false',
        VITE_API_BASE: API_URL,
      },
    },
  ],
});
