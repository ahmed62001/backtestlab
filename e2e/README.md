# Real-browser E2E (Phase 11)

Playwright tests run against the **real** FastAPI backend and the real React app
(`VITE_USE_MOCK=false`). No network or API keys are required: the backend uses a
throwaway SQLite database seeded with deterministic synthetic bars, and the
`local_store` provider serves them offline.

## Run

```bash
npm ci
npx playwright install chromium   # once per machine (CI installs --with-deps)
npm run e2e                       # or: make e2e
```

`playwright.config.ts` starts both servers automatically:

1. `e2e/start-backend.sh` — creates `/tmp/backtestlab_e2e.db`, runs
   `python -m app.cli seed` (2022-01-01 → 2023-12-31, 20 symbols), then starts
   uvicorn on `127.0.0.1:8000` with `ENGINE_MODE=vendor`,
   `DATA_PROVIDER_DEFAULT=local_store`.
2. Vite dev server on `127.0.0.1:5173` with `VITE_USE_MOCK=false` and
   `VITE_API_BASE=http://127.0.0.1:8000`.

Both are reused when already running locally (`reuseExistingServer`), but never
in CI. Override ports with `E2E_API_PORT` / `E2E_WEB_PORT`, or the DB path with
`E2E_DB`.

## Coverage

| Spec | What it proves |
| --- | --- |
| register/logout/login | Real auth against the API, session restore |
| provider catalog | Category grouping, unavailable providers disabled, stale draft provider re-resolved |
| happy path | Template → asset → `local_store` run → metrics + provenance (provider, retrieval, 64-hex hash) |
| provider error | Missing stored range returns `DATA_NOT_IN_STORE`, shown as a translated message |
| language switch | EN ↔ AR applies `dir="rtl"`, no raw i18n keys rendered |

Failures keep a screenshot, video and Playwright trace under `test-results/`;
the CI `e2e` job uploads `playwright-report/` and `test-results/` as artifacts.
