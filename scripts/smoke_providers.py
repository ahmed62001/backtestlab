"""Provider smoke-test tooling: real upstream connectivity verification.

Tests actual HTTP requests to public market-data providers (no mocks).
Results are classified as PASS / FAIL / BLOCKED / MISCONFIGURED / NOT_VERIFIED.

Usage:
  python scripts/smoke_providers.py              # all public providers
  python scripts/smoke_providers.py yfinance     # single provider
  python scripts/smoke_providers.py coingecko frankfurter

Environment:
  ALPHAVANTAGE_API_KEY, FRED_API_KEY, TIINGO_API_KEY,
  TWELVEDATA_API_KEY, POLYGON_API_KEY  -- optional keyed-provider tests

No personal credentials are required for the public paths tested here.
Tests use small, inexpensive requests and respect provider rate limits.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

# Ensure backend + vendor on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))
sys.path.insert(
    0, os.path.join(_REPO_ROOT, "backend", "vendor", "Vibe-Trading", "agent")
)

import httpx  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
MISCONFIGURED = "MISCONFIGURED"
NOT_VERIFIED = "NOT_VERIFIED"


def _result(status: str, detail: str, elapsed_ms: int | None = None) -> dict[str, Any]:
    return {"status": status, "detail": detail, "elapsed_ms": elapsed_ms}


def _timed(fn):
    t0 = time.monotonic()
    try:
        return fn(), int((time.monotonic() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        return e, int((time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------------------
# yfinance (via vendor loader, requires yfinance package)
# ---------------------------------------------------------------------------
def _smoke_yfinance() -> dict[str, Any]:
    import importlib.util

    if importlib.util.find_spec("yfinance") is None:
        return _result(MISCONFIGURED, "yfinance package not installed")
    try:
        from backtest.loaders.yfinance_loader import DataLoader as YFLoader

        loader = YFLoader()
        if not loader.is_available():
            return _result(FAIL, "yfinance loader reports unavailable")
        result, elapsed = _timed(
            lambda: loader.fetch(["AAPL.US"], "2024-01-01", "2024-01-10", interval="1D")
        )
        if isinstance(result, Exception):
            return _result(FAIL, f"fetch raised: {result}", elapsed)
        df = result.get("AAPL.US")
        if df is None or len(df) == 0:
            return _result(FAIL, "no bars returned for AAPL.US", elapsed)
        return _result(
            PASS,
            f"{len(df)} bars for AAPL.US, first close={float(df['close'].iloc[0]):.2f}",
            elapsed,
        )
    except Exception as e:  # noqa: BLE001
        return _result(FAIL, f"unexpected error: {e}")


# ---------------------------------------------------------------------------
# CCXT / Binance public (requires ccxt package)
# ---------------------------------------------------------------------------
def _smoke_ccxt() -> dict[str, Any]:
    import importlib.util

    if importlib.util.find_spec("ccxt") is None:
        return _result(MISCONFIGURED, "ccxt package not installed")
    try:
        import ccxt

        ex = ccxt.binance({"enableRateLimit": True, "timeout": 15000})
        result, elapsed = _timed(lambda: ex.load_markets())
        if isinstance(result, Exception):
            return _result(FAIL, f"load_markets raised: {result}", elapsed)
        markets = result
        if "BTC/USDT" not in markets:
            return _result(FAIL, "BTC/USDT not in Binance markets", elapsed)
        result, elapsed2 = _timed(lambda: ex.fetch_ohlcv("BTC/USDT", "1d", limit=3))
        if isinstance(result, Exception):
            return _result(FAIL, f"fetch_ohlcv raised: {result}", elapsed + elapsed2)
        ohlcv = result
        if not ohlcv or len(ohlcv) == 0:
            return _result(FAIL, "no OHLCV candles for BTC/USDT", elapsed + elapsed2)
        c = ohlcv[-1]
        return _result(
            PASS,
            f"BTC/USDT: {len(ohlcv)} candles, last close={c[4]:.2f}",
            elapsed + elapsed2,
        )
    except Exception as e:  # noqa: BLE001
        return _result(FAIL, f"unexpected error: {e}")


# ---------------------------------------------------------------------------
# CoinGecko (direct HTTP, no key)
# ---------------------------------------------------------------------------
def _smoke_coingecko() -> dict[str, Any]:
    try:
        client = httpx.Client(timeout=15.0)
        try:
            result, elapsed = _timed(
                lambda: client.get("https://api.coingecko.com/api/v3/ping")
            )
            resp = result
            if isinstance(resp, Exception):
                return _result(FAIL, f"ping raised: {resp}", elapsed)
            if resp.status_code != 200:
                return _result(FAIL, f"ping HTTP {resp.status_code}", elapsed)
            # Fetch a small OHLCV range for bitcoin
            result, elapsed2 = _timed(
                lambda: client.get(
                    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                    params={"vs_currency": "usd", "days": "7", "interval": "daily"},
                )
            )
            resp = result
            if isinstance(resp, Exception):
                return _result(FAIL, f"market_chart raised: {resp}", elapsed + elapsed2)
            if resp.status_code != 200:
                return _result(FAIL, f"market_chart HTTP {resp.status_code}", elapsed + elapsed2)
            data = resp.json()
            prices = data.get("prices", [])
            if not prices:
                return _result(FAIL, "no prices from CoinGecko", elapsed + elapsed2)
            return _result(
                PASS,
                f"ping OK, {len(prices)} daily prices for bitcoin, last=${prices[-1][1]:.2f}",
                elapsed + elapsed2,
            )
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001
        return _result(FAIL, f"unexpected error: {e}")


# ---------------------------------------------------------------------------
# Frankfurter (direct HTTP, no key)
# ---------------------------------------------------------------------------
def _smoke_frankfurter() -> dict[str, Any]:
    try:
        client = httpx.Client(timeout=15.0)
        try:
            result, elapsed = _timed(
                lambda: client.get(
                    "https://api.frankfurter.dev/v1/latest",
                    params={"from": "EUR", "to": "USD"},
                )
            )
            resp = result
            if isinstance(resp, Exception):
                return _result(FAIL, f"latest raised: {resp}", elapsed)
            if resp.status_code != 200:
                return _result(FAIL, f"latest HTTP {resp.status_code}", elapsed)
            data = resp.json()
            rate = data.get("rates", {}).get("USD")
            if rate is None:
                return _result(FAIL, "no USD rate in response", elapsed)
            return _result(
                PASS,
                f"EUR/USD={rate:.4f} ({data.get('date')})",
                elapsed,
            )
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001
        return _result(FAIL, f"unexpected error: {e}")


# ---------------------------------------------------------------------------
# Stooq (direct HTTP, no key) - often blocked by anti-bot challenge
# ---------------------------------------------------------------------------
def _smoke_stooq() -> dict[str, Any]:
    try:
        client = httpx.Client(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        try:
            result, elapsed = _timed(
                lambda: client.get(
                    "https://stooq.com/q/d/l/",
                    params={"s": "aapl.us", "d1": "20240101", "d2": "20240131", "i": "d"},
                )
            )
            resp = result
            if isinstance(resp, Exception):
                return _result(FAIL, f"request raised: {resp}", elapsed)
            body = resp.text or ""
            if resp.status_code in (403, 429):
                return _result(BLOCKED, f"HTTP {resp.status_code} - access denied", elapsed)
            text = body.lstrip().lower()
            if text.startswith("<") or "challenge" in text or "proof of work" in text:
                return _result(
                    BLOCKED,
                    "anti-bot / proof-of-work challenge page returned instead of CSV",
                    elapsed,
                )
            if "daily hits limit" in text or "too many requests" in text:
                return _result(BLOCKED, "quota refusal text returned", elapsed)
            resp.raise_for_status()
            if not body.strip() or body.strip().upper().startswith("N/D"):
                return _result(FAIL, "empty or N/D response (no data)", elapsed)
            return _result(
                PASS,
                f"CSV received ({len(body)} bytes), starts: {body.strip()[:60]!r}",
                elapsed,
            )
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001
        return _result(FAIL, f"unexpected error: {e}")


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

SMOKE_TESTS = {
    "yfinance": (_smoke_yfinance, "Yahoo Finance (public, no key)"),
    "ccxt": (_smoke_ccxt, "CCXT / Binance public (public, no key)"),
    "coingecko": (_smoke_coingecko, "CoinGecko (public, no key)"),
    "frankfurter": (_smoke_frankfurter, "Frankfurter ECB FX (public, no key)"),
    "stooq": (_smoke_stooq, "Stooq (public, no key, often anti-bot blocked)"),
}


def main() -> int:
    selected = sys.argv[1:] if len(sys.argv) > 1 else list(SMOKE_TESTS)
    print("=" * 70)
    print("BacktestLab Provider Smoke Tests (real upstream connectivity)")
    print("=" * 70)
    print()

    all_passed = True
    for pid in selected:
        if pid not in SMOKE_TESTS:
            print(f"[SKIP] {pid}: unknown provider (available: {', '.join(SMOKE_TESTS)})")
            continue
        fn, desc = SMOKE_TESTS[pid]
        res = fn()
        status = res["status"]
        detail = res["detail"]
        elapsed = res.get("elapsed_ms")
        elapsed_str = f" ({elapsed}ms)" if elapsed is not None else ""
        passed = status == PASS
        all_passed = all_passed and passed
        tag = {
            PASS: "PASS",
            FAIL: "FAIL",
            BLOCKED: "BLOCKED",
            MISCONFIGURED: "MISCONFIGURED",
            NOT_VERIFIED: "NOT_VERIFIED",
        }.get(status, status)
        print(f"[{tag}] {pid} - {desc}{elapsed_str}")
        print(f"      {detail}")
        print()

    print("=" * 70)
    if all_passed and selected:
        print("RESULT: all selected providers PASSED live connectivity.")
    else:
        print("RESULT: some providers did not pass (see details above).")
    print("=" * 70)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
