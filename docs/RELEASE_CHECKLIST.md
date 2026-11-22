# Release checklist — BacktestLab

Last reviewed: **2026-11-04** (Phase 14 — documentation).
A checked box needs a command and observed result in this repo's history; an
unchecked box needs a concrete reason and the command to run later.

## Mandatory gates

| Done | Item | Evidence / command |
|---|---|---|
| [x] | Frontend verify | `npm run verify` — 34 Vitest tests (6 files), TypeScript, ESLint, color/RTL guards, production build; PASS 2026-11-04 |
| [x] | Browser E2E | `npm run e2e` — Playwright/Chromium, 5 specs, real API + seeded SQLite + `local_store`; PASS (Phase 11) |
| [x] | Backend tests (SQLite) | `DATABASE_URL=sqlite:////tmp/bt_test.db pytest tests/ -q --cov=app --cov-fail-under=70` — 146 passed, coverage 73.04% (2026-11-04) |
| [x] | Backend lint/types | `ruff check .`, `ruff format --check .`, `mypy` — clean (Phase 12, re-run in CI) |
| [x] | i18n parity | `src/i18n/en.json` + `ar.json` parse; leaf-key parity test `src/i18n/i18n.test.ts` passes |
| [x] | Dependency consistency | `pip check` — “No broken requirements found” (core + providers + dev; Phase 12) |
| [~] | Dependency audit | Phase 12 recorded no known vulnerabilities. In the RC pass (2026-11-07) `npm audit --omit=dev --offline` reported 0, but the Python audit could not be re-run: the `pip-audit` entry point is broken (`ModuleNotFoundError: pip_audit`) and registry access is unavailable — **NOT VERIFIED**. |
| [x] | License scan | AGPL/Affero grep over all three `backend/requirements*.txt` — no matches (Phase 12) |
| [x] | Repo hygiene | `git status` clean; no secrets, DB files, `node_modules`, caches or generated reports tracked (Phase 13) |
| [x] | Vendor hygiene | `backend/vendor/README.md`, pinned commit, LICENSE/NOTICE, `tests/test_vendor_hygiene.py` (6 gates) pass (Phase 13) |
| [x] | SQLite migrations | `alembic upgrade head -> downgrade 5d8a7492f5a8 -> upgrade head`, single head `9c4e7a2b1f30`, `alembic check` clean |
| [x] | PostgreSQL migrations | Same round-trip on PostgreSQL 16 (CI `backend-postgres`; locally verified in Phase 10 and the RC pass) |
| [x] | OpenAPI snapshot | `python backend/scripts/update_openapi_snapshot.py --check` — 37 paths, no drift (RC pass, 2026-11-07) |
| [x] | Docker build/compose | `docker build` backend + frontend succeed; `docker compose config -q` passes (Phases 6/13) |
| [x] | Docs current | README, `DATA_PROVIDERS.md`, `DATA_STORE.md`, `OPERATIONS.md`, `API_CONTRACT.md`, this checklist, `RELEASE_HARDENING_AUDIT.md`, `PRE_PHASE_15_ACCEPTANCE_AUDIT.md`, `REMEDIATION_FINAL_REPORT.md` |
| [ ] | Live provider smoke recorded | `backend/scripts/smoke_providers.py` — yfinance/ccxt/stooq were exercised locally in earlier sessions; keyed providers need keys and this environment has none. Run on a networked release machine with keys and attach output. |
| [ ] | CI green on the remote | The workflow was replayed locally step-by-step (Phase 7), but no remote push/PR run exists yet. Push and require `ci.yml` to pass. |
| [ ] | Production secrets configured | `ENV=production`, 32+ char `LOCAL_JWT_SECRET`, real `DATABASE_URL`, explicit `CORS_ORIGINS`; `validate_prod_boot()` refuses weak config. Owner/infra action. |
| [ ] | Tag/version created | No release tag yet. Create after the remote CI run and sign-off. |

## Deferred / owner-only (with reason)

| Done | Item | Reason / next action |
|---|---|---|
| [x] | Structured logging + request/job IDs | Implemented in Phase 9 (`LOG_FORMAT`, context vars, redaction); no longer deferred. |
| [x] | Stooq anti-bot behavior | Known upstream behavior; typed `UPSTREAM_BLOCKED`, no silent fallback. |
| [x] | Playwright coverage | Real-browser suite + blocking CI `e2e` job (Phase 11). |
| [ ] | Commercial provider + redistribution terms | Owner-only legal/product review before production use. `license_class` is metadata only; no runtime license gate. |
| [ ] | Supabase URL/keys/JWKS | Local JWT auth is used; `SUPABASE_*` must be configured to switch `AUTH_PROVIDER=supabase`. |
| [ ] | Legal review (privacy, disclaimers, Shariah, vendor MIT confirmation) | Owner/counsel action; vendor license evidence is in `docs/ENGINE_VERIFICATION.md` and `backend/vendor/README.md`. |
| [ ] | Hosting + on-device UI review | Owner action; staging compose stack is ready and documented in `docs/OPERATIONS.md`. |
| [ ] | Billing | Intentionally postponed: billing endpoints return `501 NOT_AVAILABLE`. |
| [ ] | Automatic result retention | `RESULT_RETENTION_DAYS` is not implemented; add a scheduled purge if required (see `docs/DATA_STORE.md#retention-and-growth`). |

## Sign-off

Release is ready when every mandatory box is checked, the deferred items have an
owner and a date, and `git tag` has been created from the verified commit.
