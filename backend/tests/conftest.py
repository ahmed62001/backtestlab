"""Pytest env bootstrap — runs BEFORE any app import (conftest is first).

Tests always exercise the REAL vendor engine path (ENGINE_MODE=vendor) and
the local CSV fixture provider. No live network in CI.
"""

import os
import socket

import pytest

os.environ.setdefault("ENV", "dev")
os.environ.setdefault("ENGINE_MODE", "vendor")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")
# Phase 2: data-provider defaults for tests (synthetic in tests is allowed but
# the fixture-backed "local" provider keeps golden/API results deterministic).
os.environ.setdefault("DATA_PROVIDER_DEFAULT", "local")
os.environ.setdefault(
    "DATA_PROVIDERS_ENABLED",
    "local,synthetic,csv_upload,stooq,yfinance,ccxt,alphavantage,binance_public,coingecko,frankfurter,fred,tiingo,twelvedata,polygon,local_store",
)
os.environ.setdefault("DATA_CACHE_DIR", "/tmp/btlab_test_cache")
os.environ.setdefault("DATA_UPLOAD_DIR", "/tmp/btlab_test_uploads")
# The worker cap is a production backpressure control; the suite submits many
# jobs/backtests in-process and must not trip a 2-slot limit.
os.environ.setdefault("QUEUE_MAX_WORKERS", "64")


# --- Socket guard: block all real network connections in tests ---
# This ensures no test accidentally hits the network.
# Providers that need network must be explicitly mocked in their tests.
_real_socket_connect = socket.socket.connect


def _blocked_connect(self, address, *args, **kwargs):
    # A caller may explicitly allow only its private PostgreSQL Unix socket.
    # Normal tests leave this unset and continue to block all connections.
    pg_socket_dir = os.environ.get("P15_TEST_PG_SOCKET_DIR")
    if (
        pg_socket_dir
        and isinstance(address, str)
        and address.startswith(f"{pg_socket_dir.rstrip('/')}/")
    ):
        return _real_socket_connect(self, address, *args, **kwargs)
    # Optional TCP allowance for a throwaway verification database only.
    pg_host = os.environ.get("P15_TEST_PG_HOST")
    pg_port = os.environ.get("P15_TEST_PG_PORT")
    if pg_host and pg_port and isinstance(address, tuple):
        host, port = address[0], address[1]
        if str(host) == pg_host and int(port) == int(pg_port):
            return _real_socket_connect(self, address, *args, **kwargs)
    raise OSError("Network access blocked in tests. Mock the HTTP call.")


@pytest.fixture(autouse=True)
def _isolate_login_rate_limiter():
    """Keep login/register limiting state from leaking across tests.

    The in-memory limiter is process-global and per-IP; a full suite
    legitimately creates many accounts, which would otherwise trip the
    production cap and make unrelated later tests fail with 429. The shared
    DB-backed ledger must be cleared for the same reason.
    """
    try:
        from app import auth
        from app.data_providers.cooldown import clear_provider_state
        from app.data_providers.registry import clear_provider_info_cache

        auth._attempts.clear()
        auth.reset_login_attempts()
        clear_provider_state()
        clear_provider_info_cache()
    except Exception:  # noqa: BLE001 - app may not be importable yet
        pass
    yield


def pytest_configure(config):
    """Install socket guard before any test runs."""
    socket.socket.connect = _blocked_connect


def pytest_unconfigure(config):
    """Restore real socket after tests."""
    socket.socket.connect = _real_socket_connect
