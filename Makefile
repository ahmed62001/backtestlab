# BacktestLab developer entry points.
#
# Quick start:
#   make setup          # venv + backend deps + npm ci + Playwright chromium
#   make verify         # lint + typecheck + unit tests + production build
#   make e2e            # real-browser Playwright suite (seeded backend)
#   make up / make down # production Docker stack
#
# Override the interpreter/venv with: make setup PYTHON=python3.11 VENV=.venv

PYTHON ?= python3
VENV ?= .venv
BACKEND_DIR := backend
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
DEMO_DB ?= /tmp/bt_demo.db
SEED_DB ?= /tmp/bt_seed.db
TEST_DB ?= /tmp/bt_test.db

.PHONY: help setup verify test test-backend test-frontend lint lint-backend \
	lint-frontend format typecheck e2e e2e-install up down seed ingest-demo \
	openapi-snapshot check docker-up docker-down verify-vendor

help:
	@echo "setup        create .venv, install backend/npm deps, install Chromium"
	@echo "verify       lint + typecheck + backend/frontend tests + build"
	@echo "test         backend + frontend test suites"
	@echo "lint         ruff check/format + mypy + eslint"
	@echo "e2e          Playwright browser suite against a seeded real backend"
	@echo "up / down    start / stop the production Docker stack"
	@echo "seed         deterministic synthetic data-store seed ($(SEED_DB))"
	@echo "ingest-demo  ingest the local fixture into the store ($(DEMO_DB))"

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND_DIR)/requirements-dev.txt
	npm ci
	npx playwright install chromium

# ---- tests -----------------------------------------------------------------
test: test-backend test-frontend

test-backend:
	cd $(BACKEND_DIR) && rm -f $(TEST_DB) && \
		DATABASE_URL=sqlite:///$(TEST_DB) $(abspath $(PY)) -m pytest tests/ -q \
		--cov=app --cov-fail-under=70 -p no:cacheprovider

test-frontend:
	npm run verify

# ---- lint / types ----------------------------------------------------------
lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND_DIR) && $(abspath $(VENV))/bin/ruff check . && \
		$(abspath $(VENV))/bin/ruff format --check . && \
		$(abspath $(VENV))/bin/mypy

lint-frontend:
	npm run typecheck && npm run lint && npm run check-colors && npm run check-rtl

format:
	cd $(BACKEND_DIR) && $(abspath $(VENV))/bin/ruff format .

typecheck:
	cd $(BACKEND_DIR) && $(abspath $(VENV))/bin/mypy
	npm run typecheck

verify: lint test

verify-vendor:
	cd $(BACKEND_DIR) && $(abspath $(PY)) scripts/verify_vendor.py

# ---- browser E2E -----------------------------------------------------------
e2e-install:
	npx playwright install chromium

e2e:
	npx playwright test

# ---- data store ------------------------------------------------------------
seed:
	cd $(BACKEND_DIR) && DATABASE_URL=sqlite:///$(SEED_DB) \
		$(abspath $(PY)) -m app.cli seed

ingest-demo:
	cd $(BACKEND_DIR) && DATABASE_URL=sqlite:///$(DEMO_DB) \
		$(abspath $(PY)) -m app.cli ingest local AAPL \
		--start 2022-01-01 --end 2023-12-31

openapi-snapshot:
	cd $(BACKEND_DIR) && DATABASE_URL=sqlite:////tmp/bt_snapshot.db \
		$(abspath $(PY)) scripts/update_openapi_snapshot.py

check: openapi-snapshot
	cd $(BACKEND_DIR) && DATABASE_URL=sqlite:////tmp/bt_snapshot_check.db \
		$(abspath $(PY)) scripts/update_openapi_snapshot.py --check

# ---- Docker ----------------------------------------------------------------
up:
	docker compose up --build -d

down:
	docker compose down -v

# Backwards-compatible aliases used by older docs/scripts.
docker-up: up
docker-down: down
