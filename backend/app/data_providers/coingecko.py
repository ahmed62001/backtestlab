"""CoinGecko provider — direct HTTP implementation.

Free crypto market data (prices, OHLCV) via CoinGecko public API.
No API key required for basic usage (rate limited: 10-50 calls/min).

Correctness notes (remediation, 2026-11-09)
-------------------------------------------
* The upstream range is derived from the **requested start/end**, not from a
  fixed "last N days" window. The old implementation always asked for the last
  365 days and then filtered by the requested window, which silently produced
  an empty frame for historical backtests and triggered three identical
  retries followed by a misleading 404.
* A reachable provider that returns zero usable bars is a permanent
  ``PROVIDER_NO_DATA`` outcome — it is never retried.
* Unknown tickers are resolved through a **cached** ``/coins/list`` mapping
  (7-day disk TTL). The list is never downloaded per backtest, and an
  unresolvable ticker fails before a market-chart request is made.
* Identical successful JSON calls inside one request/job are deduplicated by
  ``base.http_get_json``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .base import (
    CACHE_DIR,
    ERR_BAD_INPUT,
    ERR_UNKNOWN_SYMBOL,
    ERR_UPSTREAM_BAD_RESPONSE,
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    ProviderNoDataError,
    classify_error,
    get_httpx_client,
    http_get_json,
)

logger = logging.getLogger(__name__)

# CoinGecko API base
_BASE_URL = "https://api.coingecko.com/api/v3"
_DEFAULT_MIN_INTERVAL = 1.2  # seconds between calls
_HEALTH_TIMEOUT_S = float(os.environ.get("PROVIDER_HEALTH_TIMEOUT_S", "1.0"))
_COIN_LIST_TTL_S = int(os.environ.get("COINGECKO_COIN_LIST_TTL_S", str(7 * 24 * 3600)))
_COIN_LIST_FILE = CACHE_DIR / "coingecko_coins.json"

# Canonical base asset -> CoinGecko coin id. This is a bounded curated map; a
# miss falls back to the cached coin list, never to a guessed id.
_KNOWN_COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "XLM": "stellar",
    "TRX": "tron",
    "TON": "the-open-network",
    "SHIB": "shiba-inu",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
}

# Quote aliases: CoinGecko prices every coin against a fiat/crypto currency id.
_QUOTE_ALIASES = {"USDT": "usd", "USDC": "usd", "BUSD": "usd", "DAI": "usd"}

_INTERVAL_MAP = {
    "1D": "daily",
    "1H": "hourly",
}

_coin_list_mem: tuple[float, dict[str, str]] | None = None
_coin_list_lock = threading.Lock()


def _split_symbol(symbol: str) -> tuple[str, str]:
    """Split ``BTC-USD`` / ``BTC/USD`` / ``BTC`` into (base, vs_currency)."""
    raw = str(symbol or "").strip().upper()
    if "-" in raw:
        base, quote = raw.split("-", 1)
    elif "/" in raw:
        base, quote = raw.split("/", 1)
    else:
        base, quote = raw, "USD"
    quote = quote.strip() or "USD"
    return base.strip(), _QUOTE_ALIASES.get(quote, quote.lower())


def _coin_list_path() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", str(CACHE_DIR))) / _COIN_LIST_FILE.name


def _read_cached_coin_list() -> dict[str, str] | None:
    path = _coin_list_path()
    try:
        if not path.exists() or time.time() - path.stat().st_mtime >= _COIN_LIST_TTL_S:
            return None
        payload = json.loads(path.read_text())
        if isinstance(payload, dict) and payload:
            return {str(k): str(v) for k, v in payload.items()}
    except Exception:  # noqa: BLE001 - corrupt cache is just a cache miss
        return None
    return None


def _write_cached_coin_list(mapping: dict[str, str]) -> None:
    try:
        path = _coin_list_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(mapping, sort_keys=True))
        tmp.replace(path)
    except Exception:  # noqa: BLE001 - caching is best-effort
        logger.warning("could not persist CoinGecko coin list cache")


def _coin_list() -> dict[str, str]:
    """Symbol -> coin-id mapping, cached in memory and on disk for 7 days."""
    global _coin_list_mem
    now = time.time()
    if _coin_list_mem is not None and now - _coin_list_mem[0] < _COIN_LIST_TTL_S:
        return _coin_list_mem[1]
    with _coin_list_lock:
        if _coin_list_mem is not None and now - _coin_list_mem[0] < _COIN_LIST_TTL_S:
            return _coin_list_mem[1]
        cached = _read_cached_coin_list()
        if cached is not None:
            _coin_list_mem = (now, cached)
            return cached
        try:
            data = http_get_json("coingecko", f"{_BASE_URL}/coins/list", timeout=10.0)
        except (httpx.HTTPError, ValueError, TypeError):
            return _coin_list_mem[1] if _coin_list_mem else {}
        mapping: dict[str, str] = {}
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol") or "").strip().upper()
                cid = str(item.get("id") or "").strip()
                if not sym or not cid:
                    continue
                # Prefer the shortest id (usually the canonical coin, not a
                # bridged/wrapped derivative sharing the ticker).
                if sym not in mapping or len(cid) < len(mapping[sym]):
                    mapping[sym] = cid
        _write_cached_coin_list(mapping)
        _coin_list_mem = (now, mapping)
        return mapping


def resolve_coin_id(base: str) -> str | None:
    """Resolve a base asset ticker to a CoinGecko coin id (cached)."""
    base = base.upper().strip()
    if base in _KNOWN_COIN_IDS:
        return _KNOWN_COIN_IDS[base]
    return _coin_list().get(base)


def clear_coin_list_cache() -> None:
    """Test helper: drop the in-memory mapping (disk cache is left intact)."""
    global _coin_list_mem
    _coin_list_mem = None


class CoingeckoProvider(DataProvider):
    id = "coingecko"
    name_en = "CoinGecko (crypto)"
    name_ar = "CoinGecko (عملات مشفرة)"
    markets = ("crypto",)
    intervals = ("1H", "1D")
    license_class = "public_free"
    adjusted = False
    requires_key = False
    min_interval_s = _DEFAULT_MIN_INTERVAL
    capabilities = Capabilities(
        category=Category.CRYPTO,
        asset_classes=("crypto",),
        timeframes=("1H", "1D"),
        supports_adjusted=False,
        requires_package=None,
        requires_key_env=None,
        rate_limit_per_minute=30,
        description_en="CoinGecko free crypto market data (OHLCV, prices)",
        description_ar="بيانات سوق العملات المشفرة المجانية من CoinGecko (OHLCV، أسعار)",
    )

    def _coingecko_id(self, symbol: str) -> str | None:
        """Map our canonical symbol to a CoinGecko coin ID."""
        base, _quote = _split_symbol(symbol)
        return resolve_coin_id(base)

    def _interval_to_coingecko(self, interval: str) -> str:
        return _INTERVAL_MAP.get(interval, "daily")

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        base, vs_currency = _split_symbol(symbol)
        coin_id = resolve_coin_id(base)
        if coin_id is None:
            # Fail *before* any market-chart request: an unknown ticker cannot
            # be resolved by retrying the chart endpoint.
            raise ProviderError(
                self.id,
                ERR_UNKNOWN_SYMBOL,
                f"unsupported symbol for CoinGecko: {symbol!r}",
                details={"symbol": symbol},
            )

        cg_interval = self._interval_to_coingecko(interval)
        if cg_interval == "hourly" and interval not in ("1H",):
            raise ProviderError(
                self.id, ERR_BAD_INPUT, f"CoinGecko hourly only supports 1H, got {interval!r}"
            )

        start_dt = pd.Timestamp(start or "2020-01-01")
        start_dt = (
            start_dt.tz_localize("UTC") if start_dt.tz is None else start_dt.tz_convert("UTC")
        )
        end_dt = pd.Timestamp(end or "2100-01-01")
        end_dt = end_dt.tz_localize("UTC") if end_dt.tz is None else end_dt.tz_convert("UTC")
        if end_dt <= start_dt:
            raise ProviderError(self.id, ERR_BAD_INPUT, f"start must precede end: {start} >= {end}")

        url = f"{_BASE_URL}/coins/{coin_id}/market_chart/range"
        params = {
            "vs_currency": vs_currency,
            "from": int(start_dt.timestamp()),
            "to": int(end_dt.timestamp()),
        }
        try:
            data = http_get_json(self.id, url, params=params, timeout=30.0)
        except httpx.HTTPStatusError as e:
            raise classify_error(self.id, e) from e
        except httpx.RequestError as e:
            raise classify_error(self.id, e) from e
        except (ValueError, TypeError) as e:
            raise ProviderError(
                self.id, ERR_UPSTREAM_BAD_RESPONSE, f"invalid CoinGecko JSON: {e}"
            ) from e

        if not isinstance(data, dict):
            raise ProviderError(
                self.id, ERR_UPSTREAM_BAD_RESPONSE, "unexpected CoinGecko response shape"
            )

        prices = data.get("prices") or []
        if not prices:
            # 200 with no prices is a permanent no-data outcome, not a symbol
            # error and not a transient failure.
            raise ProviderNoDataError(
                self.id,
                f"no data for {symbol!r} from CoinGecko in {start}..{end}",
                details={
                    "symbol": symbol,
                    "start": str(start_dt.date()),
                    "end": str(end_dt.date()),
                },
            )

        try:
            df = pd.DataFrame(prices, columns=["timestamp", "close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
        except Exception as e:  # noqa: BLE001
            raise ProviderError(
                self.id, ERR_UPSTREAM_BAD_RESPONSE, f"malformed CoinGecko prices: {e}"
            ) from e

        if df.empty:
            raise ProviderNoDataError(
                self.id,
                f"no data for {symbol!r} from CoinGecko in {start}..{end}",
                details={"symbol": symbol},
            )

        # CoinGecko's market_chart endpoint returns close prices. Derive the
        # OHLC envelope deterministically (open = previous close) rather than
        # pretending the source supplies intrabar extremes.
        df["open"] = df["close"].shift(1).fillna(df["close"])
        df["high"] = df[["open", "close"]].max(axis=1)
        df["low"] = df[["open", "close"]].min(axis=1)

        volumes = data.get("total_volumes") or []
        if volumes:
            try:
                vol_df = pd.DataFrame(volumes, columns=["timestamp", "volume"])
                vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms", utc=True)
                vol_df = vol_df.set_index("timestamp")
                vol_df["volume"] = pd.to_numeric(vol_df["volume"], errors="coerce")
                df = df.join(vol_df["volume"], how="left")
            except Exception:  # noqa: BLE001
                df["volume"] = 0.0
        else:
            df["volume"] = 0.0

        df = df[(df.index >= start_dt) & (df.index <= end_dt)]
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if df.empty:
            raise ProviderNoDataError(
                self.id,
                f"no data for {symbol!r} from CoinGecko in {start}..{end}",
                details={
                    "symbol": symbol,
                    "start": str(start_dt.date()),
                    "end": str(end_dt.date()),
                },
            )
        return df

    def health_check(self) -> dict[str, Any]:
        try:
            client = get_httpx_client(self.id, timeout=_HEALTH_TIMEOUT_S)
            resp = client.get(f"{_BASE_URL}/ping")
            if resp.status_code == 200:
                return {"available": True, "detail": ""}
            return {"available": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": str(e)}


def symbol_fingerprint(symbol: str) -> str:
    """Stable short fingerprint used in diagnostics (never a credential)."""
    return hashlib.sha256(symbol.encode()).hexdigest()[:12]
