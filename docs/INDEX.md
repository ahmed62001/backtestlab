# Documentation Index

Reference docs for BacktestLab's architecture, HTTP contract, data providers, storage layer, and operations.

## Overview & design

| Document | Covers |
|---|---|
| [`../README.md`](../README.md) | Project overview, screenshots, quick start, and local dev workflow |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, request/job flow, and service boundaries |
| [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) | Engineering trade-offs and product decisions |
| [`DECISIONS_BACKEND.md`](DECISIONS_BACKEND.md) | Backend design notes |
| [`DESIGN_TOKENS.md`](DESIGN_TOKENS.md) | Color, spacing, and typography tokens |

## API & market data

| Document | Covers |
|---|---|
| [`API_CONTRACT.md`](API_CONTRACT.md) | Endpoints, error codes, pagination, auth, and rate limits |
| [`ROUTES.md`](ROUTES.md) | Frontend route inventory |
| [`openapi.snapshot.json`](openapi.snapshot.json) | Committed OpenAPI snapshot (drift-checked in CI) |
| [`DATA_PROVIDERS.md`](DATA_PROVIDERS.md) | Provider catalog, auth gating, retries, cooldowns, and error taxonomy |
| [`FX_PROVIDERS.md`](FX_PROVIDERS.md) | FX provider eligibility and pairing rules |
| [`MARKET_ASSET_COVERAGE.md`](MARKET_ASSET_COVERAGE.md) | Supported symbols and asset-class coverage |
| [`MARKET_DATA_API_REQUIREMENTS.md`](MARKET_DATA_API_REQUIREMENTS.md) | Live market data endpoint requirements |
| [`DATA_STORE.md`](DATA_STORE.md) | Persistent market-data store schema, coverage, TTL, hashing, and CLI |
| [`METRICS_AND_INTEGRITY.md`](METRICS_AND_INTEGRITY.md) | Performance metric definitions and integrity checks |
| [`provider_template.py`](provider_template.py) | Starter template for adding a new data provider |

## Engine & operations

| Document | Covers |
|---|---|
| [`ENGINE_VERIFICATION.md`](ENGINE_VERIFICATION.md) | Engine verification methodology |
| [`VIBE_TRADING_INTEGRATION.md`](VIBE_TRADING_INTEGRATION.md) | Vendored Vibe-Trading integration and boundaries |
| [`OPERATIONS.md`](OPERATIONS.md) | Deployment topology, production checks, logging, worker recovery, backups |
| [`RUNBOOK.md`](RUNBOOK.md) | Short operational checklist |
| [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) | Pre-release verification gates |
| [`../DEPLOYMENT.md`](../DEPLOYMENT.md) | Production deployment guide |
| [`../ENVIRONMENT.md`](../ENVIRONMENT.md) | Environment variable reference |

## Security, privacy & billing

| Document | Covers |
|---|---|
| [`SECURITY_NOTES.md`](SECURITY_NOTES.md) | Threat model, cookie/CSRF auth, and hardening controls |
| [`PRIVACY_NOTES.md`](PRIVACY_NOTES.md) | Data handling notes |
| [`BILLING_OPTIONS.md`](BILLING_OPTIONS.md) | Billing integration options and disabled-by-default setup |
