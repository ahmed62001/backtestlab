"""TwelveData provider — direct HTTP implementation.

Multi-asset market data (stocks, crypto, forex) via TwelveData API.
Requires TWELVEDATA_API_KEY environment variable.
Free tier: 800 requests/day, 8 requests/minute.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any

import httpx
import pandas as pd

from .base import (
    ERR_INVALID_KEY,
    ERR_NOT_CONFIGURED,
    ERR_NOT_ENTITLED,
    ERR_RATE_LIMITED,
    ERR_UNKNOWN_SYMBOL,
    ERR_UPSTREAM_UNAVAILABLE,
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    classify_error,
    get_httpx_client,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com"
_DEFAULT_MIN_INTERVAL = 8.0  # 8 req/min = 7.5s between calls

_KEY_PLACEHOLDERS = {"", "your_twelvedata_api_key", "demo", "changeme"}

_INTERVAL_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "1H": "1h",
    "4h": "4h",
    "4H": "4h",
    "1d": "1day",
    "1D": "1day",
    "1w": "1week",
    "1W": "1week",
    "1M": "1month",
}

_INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h", "1H", "4h", "4H"})

# In-memory quote cache to conserve API credits (8 req/min limit on basic tier)
_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# Negative cache for per-symbol plan/entitlement errors (e.g. Grow+ symbols on Basic)
# Maps symbol -> (expires_monotonic, error_code, message)
_quote_errors: dict[str, tuple[float, str, str]] = {}
_quote_rate_limited_until: float = 0.0
_quote_lock = threading.Lock()
_QUOTE_CACHE_TTL_S = float(os.environ.get("TWELVEDATA_QUOTE_CACHE_TTL_S", "30.0"))
_ENTITLEMENT_NEG_TTL_S = 600.0  # 10 min negative cache for plan-restricted symbols
_RATE_LIMIT_BACKOFF_S = 45.0    # Pause further quote HTTP calls after a 429

# In-memory reference caches for cryptocurrencies (free endpoints, 1-hour TTL)
_crypto_pairs_cache: tuple[float, list[dict[str, Any]]] | None = None
_crypto_pairs_lock = threading.Lock()
_crypto_exchanges_cache: tuple[float, list[str]] | None = None
_crypto_exchanges_lock = threading.Lock()
_REFERENCE_CACHE_TTL_S = 3600.0


class TwelveDataProvider(DataProvider):
    id = "twelvedata"
    name_en = "TwelveData (multi-asset)"
    name_ar = "TwelveData (أصول متعددة)"
    markets = ("us_equity", "crypto", "fx", "commodity")
    intervals = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")
    license_class = "freemium"
    adjusted = True
    requires_key = True
    min_interval_s = _DEFAULT_MIN_INTERVAL
    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity", "crypto", "fx", "commodity"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        supports_adjusted=True,
        requires_package=None,
        requires_key_env="TWELVEDATA_API_KEY",
        rate_limit_per_minute=8,
        description_en="TwelveData multi-asset market data (stocks, crypto, forex, precious metals)",
        description_ar="بيانات سوق متعددة الأصول من TwelveData (أسهم، عملات مشفرة، فوركس، معادن ثمينة)",
    )

    def _resolve_key(self) -> str:
        key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
        if key.lower() in _KEY_PLACEHOLDERS:
            return ""
        return key

    def get_cryptocurrencies(
        self,
        currency_base: str | None = None,
        currency_quote: str | None = None,
        exchange: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve and validate supported cryptocurrency pairs using the official
        /cryptocurrencies reference endpoint (https://twelvedata.com/cryptocurrency).
        Cached in-memory to prevent burning quota.
        """
        global _crypto_pairs_cache
        now = time.monotonic()
        with _crypto_pairs_lock:
            if _crypto_pairs_cache is not None and (now - _crypto_pairs_cache[0]) < _REFERENCE_CACHE_TTL_S:
                all_pairs = _crypto_pairs_cache[1]
            else:
                client = get_httpx_client(self.id, timeout=15.0)
                try:
                    resp = client.get(f"{_BASE_URL}/cryptocurrencies")
                    resp.raise_for_status()
                    data = resp.json()
                    all_pairs = data.get("data", []) if isinstance(data, dict) else []
                    _crypto_pairs_cache = (now, all_pairs)
                except Exception as e:
                    logger.warning("Failed to fetch TwelveData cryptocurrencies: %s", e)
                    all_pairs = _crypto_pairs_cache[1] if _crypto_pairs_cache is not None else []

        results = all_pairs
        if currency_base:
            cb = currency_base.upper().strip()
            results = [p for p in results if p.get("currency_base", "").upper() == cb or p.get("symbol", "").upper().startswith(f"{cb}/")]
        if currency_quote:
            cq = currency_quote.upper().strip()
            results = [p for p in results if p.get("currency_quote", "").upper() == cq or p.get("symbol", "").upper().endswith(f"/{cq}")]
        if exchange:
            ex = exchange.strip().lower()
            results = [p for p in results if any(e.lower() == ex for e in p.get("available_exchanges", []))]
        return results

    def get_cryptocurrency_exchanges(self) -> list[str]:
        """Retrieve supported cryptocurrency exchanges from /cryptocurrency_exchanges."""
        global _crypto_exchanges_cache
        now = time.monotonic()
        with _crypto_exchanges_lock:
            if _crypto_exchanges_cache is not None and (now - _crypto_exchanges_cache[0]) < _REFERENCE_CACHE_TTL_S:
                return list(_crypto_exchanges_cache[1])
            client = get_httpx_client(self.id, timeout=15.0)
            try:
                resp = client.get(f"{_BASE_URL}/cryptocurrency_exchanges")
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                exchanges = [
                    item if isinstance(item, str) else item.get("name", "")
                    for item in items
                    if isinstance(item, str) or (isinstance(item, dict) and item.get("name"))
                ]
                _crypto_exchanges_cache = (now, exchanges)
                return exchanges
            except Exception as e:
                logger.warning("Failed to fetch TwelveData cryptocurrency exchanges: %s", e)
                return _crypto_exchanges_cache[1] if _crypto_exchanges_cache is not None else []

    def validate_cryptocurrency_pair(self, symbol: str, exchange: str | None = None) -> bool:
        """Validate whether a cryptocurrency pair is genuinely supported by Twelve Data."""
        clean_sym = symbol.upper().strip().replace("-", "/")
        if "/" not in clean_sym and len(clean_sym) > 3:
            # E.g. BTCUSD -> BTC/USD
            for q in ("USDT", "USD", "EUR", "BTC", "ETH"):
                if clean_sym.endswith(q):
                    clean_sym = f"{clean_sym[:-len(q)]}/{q}"
                    break
        pairs = self.get_cryptocurrencies()
        for p in pairs:
            if p.get("symbol", "").upper() == clean_sym:
                if exchange:
                    available = [e.lower() for e in p.get("available_exchanges", [])]
                    return exchange.lower() in available
                return True
        return False

    def search_symbols(self, query: str) -> list[dict[str, Any]]:
        """Search instruments using Twelve Data /symbol_search endpoint."""
        api_key = self._resolve_key()
        client = get_httpx_client(self.id, timeout=15.0)
        params = {"symbol": query.strip()}
        if api_key:
            params["apikey"] = api_key
        try:
            resp = client.get(f"{_BASE_URL}/symbol_search", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.warning("TwelveData symbol_search error for %r: %s", query, e)
            return []

    def _twelvedata_symbol_and_exchange(self, symbol: str) -> tuple[str, str | None]:
        """Return (symbol, exchange) normalized for Twelve Data API.
        
        Handles:
          - explicit exchange prefix/suffix: "BINANCE:BTC-USD", "BTC/USD:Binance"
          - instrument metadata exchange: "Binance spot" -> "Binance"
          - crypto pairs: "BTC-USD" -> "BTC/USD", "BTC-USDT" -> "BTC/USDT"
          - FX pairs: "EURUSD" -> "EUR/USD"
          - spot metals: "XAUUSD" -> "XAU/USD", "XAU/USD" -> "XAU/USD"
          - US equities: "AAPL.US" -> "AAPL"
        """
        raw = symbol.strip()
        exchange: str | None = None

        if ":" in raw:
            p1, p2 = raw.split(":", 1)
            # Could be EXCHANGE:SYMBOL or SYMBOL:EXCHANGE
            if "/" in p1 or "-" in p1:
                raw, exchange = p1, p2
            else:
                exchange, raw = p1, p2
            if exchange:
                exchange = exchange.replace(" spot", "").replace(" SPOT", "").strip()

        from ..instruments import get_instrument

        inst = get_instrument(raw)
        stream_sym = None
        if inst is not None:
            if inst.metadata.get("stream_symbol"):
                stream_sym = str(inst.metadata["stream_symbol"])
            if not exchange and inst.metadata.get("exchange"):
                ex_raw = str(inst.metadata["exchange"])
                # Strip suffixes like ' spot' or ' CBOE'
                if " " in ex_raw:
                    ex_clean = ex_raw.split()[0]
                else:
                    ex_clean = ex_raw
                if ex_clean.lower() in ("binance", "coinbase", "kraken", "bitfinex", "huobi", "okx"):
                    exchange = ex_clean

        if stream_sym:
            return stream_sym, exchange

        upper = raw.upper().strip()
        if "/" in upper:
            return upper, exchange

        # Six-letter alphabetic FX
        if len(upper) == 6 and upper.isalpha():
            return f"{upper[:3]}/{upper[3:]}", exchange

        # Crypto pairs with '-' (BTC-USD, BTC-USDT, SOL-USD, ETH-USDT)
        if "-" in upper:
            parts = upper.split("-", 1)
            return f"{parts[0]}/{parts[1]}", exchange

        if upper.endswith(".US"):
            return upper[:-3], exchange

        return upper, exchange

    def _twelvedata_symbol(self, symbol: str) -> str:
        sym, _ = self._twelvedata_symbol_and_exchange(symbol)
        return sym

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        api_key = self._resolve_key()
        if not api_key:
            raise ProviderError(
                self.id,
                ERR_NOT_CONFIGURED,
                f"TWELVEDATA_API_KEY not configured (required for {self.id})",
            )

        td_symbol, td_exchange = self._twelvedata_symbol_and_exchange(symbol)
        td_interval = _INTERVAL_MAP.get(interval)
        if td_interval is None:
            raise ProviderError(
                self.id, "BAD_INPUT", f"unsupported interval {interval!r} for TwelveData"
            )

        # Short-circuit known plan-restricted symbols (e.g. XAG/USD on Basic) so
        # fallback providers like Massive/Polygon serve immediately without burning credits.
        now_mono = time.monotonic()
        with _quote_lock:
            neg = _quote_errors.get(symbol) or _quote_errors.get(td_symbol)
            if neg is not None and neg[0] > now_mono and neg[1] == ERR_NOT_ENTITLED:
                raise ProviderError(self.id, ERR_NOT_ENTITLED, neg[2])

        client = get_httpx_client(self.id, timeout=30.0)

        # Twelve Data interprets date-only end_date ("YYYY-MM-DD") as 00:00:00 UTC,
        # which truncates all of today's intraday candles. Extend intraday bounds to
        # full-day UTC boundaries so 1m/5m/15m/1H/4H always include the latest bars.
        eff_start = start
        eff_end = end
        if interval in _INTRADAY_INTERVALS:
            if eff_start and len(eff_start.strip()) == 10:
                eff_start = f"{eff_start.strip()} 00:00:00"
            if eff_end and len(eff_end.strip()) == 10:
                eff_end = f"{eff_end.strip()} 23:59:59"

        params: dict[str, Any] = {
            "symbol": td_symbol,
            "interval": td_interval,
            "start_date": eff_start,
            "end_date": eff_end,
            "format": "JSON",
            "timezone": "UTC",
            "outputsize": 5000,
        }
        if td_exchange:
            params["exchange"] = td_exchange
        headers = {"Authorization": f"apikey {api_key}"}

        try:
            resp = client.get(f"{_BASE_URL}/time_series", params=params, headers=headers)
            data = None
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, dict) and data.get("status") == "error":
                msg = str(data.get("message", "Unknown error"))
                code_num = data.get("code") or resp.status_code
                low = msg.lower()
                if code_num == 401 or "apikey" in low or "api key" in low:
                    raise ProviderError(self.id, ERR_INVALID_KEY, msg)
                if code_num == 403 or "plan" in low or "upgrade" in low or "entitle" in low or "not available" in low:
                    raise ProviderError(self.id, ERR_NOT_ENTITLED, msg)
                if code_num == 429 or "rate limit" in low or "quota" in low or "credits" in low:
                    raise ProviderError(self.id, ERR_RATE_LIMITED, msg, retry_after=60)
                if code_num == 404 or "not found" in low or "invalid symbol" in low:
                    raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, msg)
                raise ProviderError(self.id, ERR_UPSTREAM_UNAVAILABLE, msg)
            resp.raise_for_status()
            if data is None:
                data = resp.json()
        except ProviderError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ProviderError(self.id, ERR_INVALID_KEY, "invalid TwelveData API key") from e
            if e.response.status_code == 403:
                raise ProviderError(
                    self.id, ERR_NOT_ENTITLED, f"TwelveData entitlement required for {symbol!r}"
                ) from e
            if e.response.status_code == 429:
                raise ProviderError(self.id, ERR_RATE_LIMITED, "TwelveData API rate limit exceeded", retry_after=60) from e
            raise classify_error(self.id, e) from e
        except httpx.RequestError as e:
            raise classify_error(self.id, e) from e

        values = data.get("values", [])
        if not values:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"no data for {symbol!r} from TwelveData"
            )

        rows = []
        for row in values:
            try:
                op = float(row["open"])
                hi = float(row["high"])
                lo = float(row["low"])
                cl = float(row["close"])
                vol = float(row.get("volume", 0) or 0)
                if not (math.isfinite(op) and math.isfinite(hi) and math.isfinite(lo) and math.isfinite(cl)):
                    continue
                if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
                    continue
                # Validate OHLC boundaries
                if hi < lo or lo > min(op, cl) + 1e-9 or hi < max(op, cl) - 1e-9:
                    # Enforce valid envelope
                    hi = max(hi, op, cl)
                    lo = min(lo, op, cl)
                rows.append(
                    {
                        "timestamp": pd.Timestamp(row["datetime"], tz="UTC"),
                        "open": op,
                        "high": hi,
                        "low": lo,
                        "close": cl,
                        "volume": max(0.0, vol),
                    }
                )
            except (KeyError, ValueError):
                continue

        if not rows:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"no valid bars for {symbol!r} from TwelveData"
            )

        df = pd.DataFrame(rows).set_index("timestamp")
        # Prevent duplicate candles and ensure chronological ordering
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch quote metadata for a symbol using Twelve Data /quote REST endpoint.

        Returns normalized dictionary with latest price, prevClose, change, changePct,
        high, low, volume, timestamp, is_market_open.
        """
        from ..instruments import normalize_symbol

        canon = normalize_symbol(symbol)
        quotes = self.fetch_quotes_batch([symbol])
        q = quotes.get(symbol) or quotes.get(canon)
        if q is not None:
            return q
        now_mono = time.monotonic()
        with _quote_lock:
            err = _quote_errors.get(symbol) or _quote_errors.get(canon)
            if err and err[0] > now_mono:
                raise ProviderError(self.id, err[1], err[2])
            if _quote_rate_limited_until > now_mono:
                raise ProviderError(
                    self.id,
                    ERR_RATE_LIMITED,
                    f"TwelveData quote rate limit active for {symbol!r}",
                    retry_after=max(1.0, _quote_rate_limited_until - now_mono),
                )
        raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"no quote returned for {symbol!r}")

    def fetch_quotes_batch(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch quotes for multiple symbols with in-memory caching and error isolation."""
        global _quote_rate_limited_until

        if not symbols:
            return {}

        import datetime as dt
        from ..instruments import get_instrument, normalize_symbol
        from ..market_sessions import session_for

        now_mono = time.monotonic()
        results: dict[str, dict[str, Any]] = {}
        missing: list[str] = []

        with _quote_lock:
            for s in symbols:
                canon = normalize_symbol(s)
                cached = _quote_cache.get(s) or _quote_cache.get(canon)
                if cached is not None and now_mono - cached[0] < _QUOTE_CACHE_TTL_S:
                    results[s] = cached[1]
                    continue
                neg = _quote_errors.get(s) or _quote_errors.get(canon)
                if neg is not None and neg[0] > now_mono:
                    # Skip known plan-restricted symbols so they don't burn API credits
                    continue
                missing.append(s)

            rate_limited = _quote_rate_limited_until > now_mono

        if not missing:
            return results

        if rate_limited:
            # Serve stale cache if present rather than hammering TwelveData with 429s
            with _quote_lock:
                for s in missing:
                    canon = normalize_symbol(s)
                    cached = _quote_cache.get(s) or _quote_cache.get(canon)
                    if cached:
                        results[s] = cached[1]
            return results

        api_key = self._resolve_key()
        if not api_key:
            # If cached data exists even if stale, return it
            with _quote_lock:
                for s in missing:
                    canon = normalize_symbol(s)
                    cached = _quote_cache.get(s) or _quote_cache.get(canon)
                    if cached:
                        results[s] = cached[1]
            if len(results) == len(symbols):
                return results
            raise ProviderError(
                self.id,
                ERR_NOT_CONFIGURED,
                f"TWELVEDATA_API_KEY not configured (required for {self.id})",
            )

        # Deduplicate by Twelve Data symbol while preserving original requested names
        dedup_missing: list[str] = []
        seen_td: set[str] = set()
        for s in missing:
            td_s = self._twelvedata_symbol(s)
            if td_s not in seen_td:
                seen_td.add(td_s)
                dedup_missing.append(s)

        # Batch in chunks of up to 8 (matching the 8 requests/minute quota limit on Basic plan)
        chunks = [dedup_missing[i : i + 8] for i in range(0, len(dedup_missing), 8)]
        client = get_httpx_client(self.id, timeout=15.0)
        now_utc = dt.datetime.now(dt.UTC)

        for chunk in chunks:
            td_symbol_to_orig = {self._twelvedata_symbol(s): s for s in chunk}
            td_symbols_str = ",".join(td_symbol_to_orig.keys())
            params = {"symbol": td_symbols_str, "apikey": api_key}

            try:
                resp = client.get(f"{_BASE_URL}/quote", params=params)
                if resp.status_code == 429:
                    logger.warning("TwelveData API rate limit exceeded on chunk %s", td_symbols_str)
                    with _quote_lock:
                        _quote_rate_limited_until = time.monotonic() + _RATE_LIMIT_BACKOFF_S
                    break
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("TwelveData API rate limit exceeded on chunk %s", td_symbols_str)
                    with _quote_lock:
                        _quote_rate_limited_until = time.monotonic() + _RATE_LIMIT_BACKOFF_S
                    break
                raise classify_error(self.id, e) from e
            except httpx.RequestError as e:
                logger.warning("TwelveData request error: %s", e)
                break

            if isinstance(data, dict) and data.get("status") == "error":
                msg = str(data.get("message", "API error"))
                code = data.get("code")
                low = msg.lower()
                if code == 429 or "rate limit" in low or "credits" in low:
                    logger.warning("TwelveData rate limit message: %s", msg)
                    with _quote_lock:
                        _quote_rate_limited_until = time.monotonic() + _RATE_LIMIT_BACKOFF_S
                    break
                if code == 401:
                    raise ProviderError(self.id, ERR_INVALID_KEY, msg)
                if code == 403 or "plan" in low or "upgrade" in low or "entitle" in low or "not available" in low:
                    if len(chunk) == 1:
                        orig = chunk[0]
                        canon = normalize_symbol(orig)
                        exp = time.monotonic() + _ENTITLEMENT_NEG_TTL_S
                        with _quote_lock:
                            _quote_errors[orig] = (exp, ERR_NOT_ENTITLED, msg)
                            _quote_errors[canon] = (exp, ERR_NOT_ENTITLED, msg)
                continue

            # Response is either a single quote dict {"symbol": "AAPL", ...} or
            # a dict of quote dicts {"AAPL": {...}, "MSFT": {...}}
            items_to_parse: dict[str, dict[str, Any]] = {}
            if "symbol" in data:
                td_sym = str(data["symbol"])
                items_to_parse[td_sym] = data
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        items_to_parse[k] = v

            with _quote_lock:
                for td_sym, raw_item in items_to_parse.items():
                    orig_sym = td_symbol_to_orig.get(td_sym)
                    if not orig_sym:
                        for s in chunk:
                            if self._twelvedata_symbol(s) == td_sym:
                                orig_sym = s
                                break
                    if not orig_sym:
                        orig_sym = td_sym
                    canon_sym = normalize_symbol(orig_sym)

                    # CRITICAL: Detect per-symbol error items in batch payloads (e.g. Grow+ 403)
                    if raw_item.get("status") == "error":
                        msg = str(raw_item.get("message", "API error"))
                        code = raw_item.get("code")
                        low = msg.lower()
                        if code == 429 or "rate limit" in low or "credits" in low:
                            _quote_rate_limited_until = time.monotonic() + _RATE_LIMIT_BACKOFF_S
                        elif code == 403 or "plan" in low or "upgrade" in low or "entitle" in low or "not available" in low:
                            exp = time.monotonic() + _ENTITLEMENT_NEG_TTL_S
                            _quote_errors[orig_sym] = (exp, ERR_NOT_ENTITLED, msg)
                            _quote_errors[canon_sym] = (exp, ERR_NOT_ENTITLED, msg)
                        else:
                            exp = time.monotonic() + 60.0
                            _quote_errors[orig_sym] = (exp, ERR_UNKNOWN_SYMBOL, msg)
                            _quote_errors[canon_sym] = (exp, ERR_UNKNOWN_SYMBOL, msg)
                        continue

                    try:
                        price = float(raw_item.get("close") or raw_item.get("price") or 0.0)
                        if not math.isfinite(price) or price <= 0.0:
                            continue
                        prev_close_val = raw_item.get("previous_close")
                        prev_close = float(prev_close_val) if prev_close_val not in (None, "") else None
                        change_val = raw_item.get("change")
                        change = float(change_val) if change_val not in (None, "") else None
                        change_pct_val = raw_item.get("percent_change")
                        change_pct = float(change_pct_val) if change_pct_val not in (None, "") else None
                        high_val = raw_item.get("high")
                        day_high = float(high_val) if high_val not in (None, "") else None
                        low_val = raw_item.get("low")
                        day_low = float(low_val) if low_val not in (None, "") else None
                        vol_val = raw_item.get("volume")
                        volume = float(vol_val) if vol_val not in (None, "") else 0.0
                        raw_open = raw_item.get("is_market_open")
                        is_open = bool(raw_open) if raw_open is not None else False
                        if not is_open:
                            inst = get_instrument(canon_sym)
                            if inst is not None and inst.asset_class in ("crypto", "fx", "commodity"):
                                is_open = session_for(inst.asset_class, inst.symbol).is_open(now_utc)
                            else:
                                upper_sym = orig_sym.upper()
                                if any(upper_sym.endswith(suffix) for suffix in ("-USD", "-USDT", "/USD", "/USDT", "-BTC", "-ETH", "/BTC", "/ETH")):
                                    is_open = True
                        datetime_str = str(raw_item.get("datetime") or "")
                        exchange_str = str(raw_item.get("exchange") or "")
                        currency_str = str(raw_item.get("currency") or "")
                        ts_val = raw_item.get("timestamp")
                        timestamp = int(ts_val) if ts_val not in (None, "") else 0

                        # Re-verify change / changePct against previous close
                        if prev_close and prev_close > 0:
                            if change is None:
                                change = price - prev_close
                            if change_pct is None:
                                change_pct = (change / prev_close) * 100.0

                        quote_entry = {
                            "symbol": orig_sym,
                            "price": price,
                            "prevClose": prev_close,
                            "change": change,
                            "changePct": change_pct,
                            "dayHigh": day_high,
                            "dayLow": day_low,
                            "volume": volume,
                            "isMarketOpen": is_open,
                            "exchange": exchange_str,
                            "currency": currency_str,
                            "datetime": datetime_str,
                            "timestamp": timestamp,
                        }
                        _quote_cache[orig_sym] = (now_mono, quote_entry)
                        _quote_cache[canon_sym] = (now_mono, quote_entry)
                        _quote_errors.pop(orig_sym, None)
                        _quote_errors.pop(canon_sym, None)
                        results[orig_sym] = quote_entry
                        results[canon_sym] = quote_entry
                    except (ValueError, TypeError) as e:
                        logger.warning("failed to parse quote for %s: %s", orig_sym, e)

        # Ensure every originally requested symbol alias maps to its result
        for s in symbols:
            if s not in results:
                canon = normalize_symbol(s)
                if canon in results:
                    results[s] = results[canon]

        return results

    def health_check(self) -> dict[str, Any]:
        api_key = self._resolve_key()
        if not api_key:
            return {"available": False, "detail": "TWELVEDATA_API_KEY not configured"}
        try:
            client = get_httpx_client(self.id, timeout=10.0)
            resp = client.get(
                f"{_BASE_URL}/time_series",
                params={
                    "symbol": "AAPL",
                    "interval": "1day",
                    "format": "JSON",
                    "outputsize": 1,
                },
                headers={"Authorization": f"apikey {api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "error":
                    return {"available": False, "detail": data.get("message", "API error")}
                return {"available": True, "detail": ""}
            return {"available": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": str(e)}
