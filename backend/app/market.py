"""Market-data read layer: universe, quotes and series (backend only).

Also hosts the narrow, read-only public market endpoints used by the landing
page before login. Those endpoints are allowlisted, cached, rate-limited and
never accept arbitrary URLs or symbols.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .auth import current_user
from .data_providers.base import ProviderError, http_status_for_code
from .data_providers.registry import enabled_ids, fetch_bars, get_provider
from .db import User
from .instruments import get_instrument, list_instruments, normalize_symbol
from .market_sessions import freshness_metadata
from .netutil import client_ip_from
from .spot_engine import CANONICAL_INTERVALS, INTRADAY_INTERVALS
from .streaming import LIVE_PRIORITY, get_manager

log = logging.getLogger("backtestlab.market")
router = APIRouter()

_MAX_SYMBOLS = 40
_MAX_BARS = 2000
# Bounded concurrency for the quotes sweep: enough to keep a cold 40-symbol
# chunk well inside the gateway timeout, small enough not to stampede the
# upstream provider.
_QUOTE_WORKERS = int(os.environ.get("MARKET_QUOTE_WORKERS", "8"))

_METAL_SYMBOLS = frozenset(
    {
        "XAU/USD",
        "XAG/USD",
        "XPT/USD",
        "XPD/USD",
        "GC=F",
        "SI=F",
        "PL=F",
        "PA=F",
        "HG=F",
    }
)


def _group(inst) -> str:
    ac = inst.asset_class
    if ac == "commodity":
        return "metals" if inst.symbol in _METAL_SYMBOLS else "commodities"
    if ac == "index":
        return "indices"
    if ac in ("equity", "etf"):
        return "stocks"
    if ac == "crypto":
        return "crypto"
    if ac == "fx":
        return "forex"
    return str(ac)


def _exchange(inst) -> str | None:
    ex = inst.metadata.get("exchange")
    return str(ex) if ex else None


def _transport(result) -> str:
    """Honest transport: a disk-cache hit is served from CACHE, never
    presented as a fresh provider fetch."""
    if result is not None and result.provenance and result.provenance.get("cache") == "hit":
        return "CACHE"
    return "REST_POLLING"


def _td_configured() -> bool:
    """Twelve Data configured and preferred for REST quotes when it serves
    the instrument: verified real-time for equity/crypto/fx on this account
    (WS ticks at 6s/39s provider-ts age + REST price movement check)."""
    import os

    return os.environ.get("TWELVEDATA_API_KEY", "").strip() not in (
        "",
        "your_twelvedata_api_key",
        "demo",
        "changeme",
    )


# Asset classes where Twelve Data real-time was actually verified on the
# configured account (docs/MARKET_STREAMING_IMPLEMENTATION_REPORT.md).
_TD_REALTIME_CLASSES = frozenset({"equity", "etf", "crypto", "fx"})


def _unavailable(symbol: str, display: str, group: str, code: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "display": display,
        "group": group,
        "status": "unavailable",
        "price": None,
        "change": None,
        "changePct": None,
        "prevClose": None,
        "dayHigh": None,
        "dayLow": None,
        "volume": None,
        "asOf": None,
        "source": None,
        "quality": "unavailable",
        "classification": "UNAVAILABLE",
        "transport": None,
        "errorCode": code,
    }


def _quote_from_result(
    symbol: str,
    display: str,
    group: str,
    frame,
    source: str,
    quality: str,
    classification: str = "END_OF_DAY",
    transport: str = "REST_POLLING",
) -> dict[str, Any]:
    if frame is None or len(frame) == 0:
        return _unavailable(symbol, display, group, "EMPTY_DATA")
    last = frame.iloc[-1]
    price = float(last["close"])
    day_high = float(last["high"])
    day_low = float(last["low"])
    volume = float(last["volume"]) if "volume" in frame.columns else 0.0
    prev_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    if len(frame) >= 2:
        prev_close = float(frame.iloc[-2]["close"])
        change = price - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else None
    as_of = (
        str(frame.index[-1].isoformat())
        if hasattr(frame.index[-1], "isoformat")
        else str(frame.index[-1])
    )
    return {
        "symbol": symbol,
        "display": display,
        "group": group,
        "status": "ok",
        "price": price,
        "change": change,
        "changePct": change_pct,
        "prevClose": prev_close,
        "dayHigh": day_high,
        "dayLow": day_low,
        "volume": volume,
        "asOf": as_of,
        "source": source,
        "quality": quality,
        "classification": classification,
        "transport": transport,
        "errorCode": None,
    }


@router.get("/api/v1/market/universe")
def universe(u: User = Depends(current_user)):  # noqa: B008
    items: list[dict[str, Any]] = []
    for inst in list_instruments():
        if inst.asset_class == "macro_reference":
            continue
        items.append(
            {
                "symbol": inst.symbol,
                "display": inst.display,
                "group": _group(inst),
                "assetClass": inst.asset_class,
                "quoteCurrency": inst.quote_currency,
                "baseCurrency": inst.base_currency,
                "exchange": _exchange(inst),
                "backtestEligible": inst.backtest_eligible,
                "intervals": list(inst.timeframes),
                "providers": list(inst.providers),
            }
        )
    return {"items": items}


@router.get("/api/v1/market/quotes")
def quotes(symbols: str = Query(default=""), u: User = Depends(current_user)):  # noqa: B008
    raw = [s.strip() for s in (symbols or "").split(",") if s.strip()]
    if not raw:
        raise HTTPException(422, detail={"code": "BAD_INPUT", "message": "symbols is required"})
    if len(raw) > _MAX_SYMBOLS:
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": f"at most {_MAX_SYMBOLS} symbols"}
        )
    now = dt.datetime.now(dt.UTC)
    end = now.strftime("%Y-%m-%d")
    start = (now - dt.timedelta(days=21)).strftime("%Y-%m-%d")
    user_id = getattr(u, "id", None)

    # Pre-batch fetch for Twelve Data symbols ordered by priority so high-value
    # live assets (BTC, EURUSD, XAU/USD, AAPL, major FX) consume the first chunk
    # before any rate-limit cap is reached.
    td_batch_symbols: list[str] = []
    for s in raw:
        sym = normalize_symbol(s)
        inst = get_instrument(sym)
        if inst and "twelvedata" in inst.providers and _td_configured():
            td_batch_symbols.append(s)
    if td_batch_symbols:
        def _prio(req_s: str) -> tuple[int, str]:
            c = normalize_symbol(req_s)
            try:
                return (LIVE_PRIORITY.index(c), c)
            except ValueError:
                return (len(LIVE_PRIORITY), c)

        td_batch_symbols.sort(key=_prio)
        try:
            td_p = get_provider("twelvedata", user_id=user_id)
            td_p.fetch_quotes_batch(td_batch_symbols)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _quote_one(requested: str) -> dict[str, Any]:
        symbol = normalize_symbol(requested)
        inst = get_instrument(symbol)
        if inst is None:
            return _unavailable(requested, requested, "", "UNKNOWN_SYMBOL")
        display = inst.display
        group = _group(inst)

        # Check for active WebSocket live tick first
        manager = get_manager()
        live_tick = manager.get_latest_tick(symbol) or manager.get_latest_tick(requested)

        try:
            if "twelvedata" in inst.providers:
                if not _td_configured():
                    return _unavailable(requested, display, group, "PROVIDER_NOT_CONFIGURED")
                td_provider = get_provider("twelvedata", user_id=user_id)
                try:
                    q = td_provider.fetch_quote(requested if requested in ("BTC/USD", "XAU/USD") else symbol)  # type: ignore[attr-defined]
                    price = float(q["price"])
                    prev_close = q.get("prevClose")
                    change = q.get("change")
                    change_pct = q.get("changePct")
                    day_high = q.get("dayHigh")
                    day_low = q.get("dayLow")
                    volume = float(q.get("volume") or 0.0)
                    as_of = q.get("datetime") or dt.datetime.now(dt.UTC).isoformat()
                    is_open = q.get("isMarketOpen", False)

                    # If WebSocket live tick is present, overlay verified live price & recalculate change
                    if live_tick is not None:
                        price = live_tick.price
                        as_of = live_tick.provider_ts.isoformat()
                        if prev_close and prev_close > 0:
                            change = price - prev_close
                            change_pct = (change / prev_close) * 100.0
                        if day_high is not None:
                            day_high = max(day_high, price)
                        if day_low is not None:
                            day_low = min(day_low, price)
                        return {
                            "symbol": requested,
                            "display": display,
                            "group": group,
                            "status": "ok",
                            "price": price,
                            "change": change,
                            "changePct": change_pct,
                            "prevClose": prev_close,
                            "dayHigh": day_high,
                            "dayLow": day_low,
                            "volume": volume,
                            "asOf": as_of,
                            "source": "twelvedata",
                            "quality": "live",
                            "classification": "REAL_TIME",
                            "transport": "WEBSOCKET",
                            "errorCode": None,
                        }

                    classification = "REAL_TIME" if is_open else "LAST_AVAILABLE"
                    quality = "live" if is_open else "eod"
                    return {
                        "symbol": requested,
                        "display": display,
                        "group": group,
                        "status": "ok",
                        "price": price,
                        "change": change,
                        "changePct": change_pct,
                        "prevClose": prev_close,
                        "dayHigh": day_high,
                        "dayLow": day_low,
                        "volume": volume,
                        "asOf": as_of,
                        "source": "twelvedata",
                        "quality": quality,
                        "classification": classification,
                        "transport": "REST_POLLING",
                        "errorCode": None,
                    }
                except ProviderError as pe:
                    # If live tick is present, return it
                    if live_tick is not None:
                        return {
                            "symbol": requested,
                            "display": display,
                            "group": group,
                            "status": "ok",
                            "price": live_tick.price,
                            "change": None,
                            "changePct": None,
                            "prevClose": None,
                            "dayHigh": live_tick.price,
                            "dayLow": live_tick.price,
                            "volume": 0.0,
                            "asOf": live_tick.provider_ts.isoformat(),
                            "source": "twelvedata",
                            "quality": "live",
                            "classification": "REAL_TIME",
                            "transport": "WEBSOCKET",
                            "errorCode": None,
                        }
                    # Check cached quote
                    cached_q = None
                    try:
                        from .data_providers.twelvedata import _quote_cache, _quote_lock
                        with _quote_lock:
                            c = _quote_cache.get(requested) or _quote_cache.get(symbol)
                            if c:
                                cached_q = c[1]
                    except Exception:
                        pass
                    if cached_q:
                        return {
                            "symbol": requested,
                            "display": display,
                            "group": group,
                            "status": "ok",
                            "price": float(cached_q["price"]),
                            "change": cached_q.get("change"),
                            "changePct": cached_q.get("changePct"),
                            "prevClose": cached_q.get("prevClose"),
                            "dayHigh": cached_q.get("dayHigh"),
                            "dayLow": cached_q.get("dayLow"),
                            "volume": float(cached_q.get("volume") or 0.0),
                            "asOf": cached_q.get("datetime") or dt.datetime.now(dt.UTC).isoformat(),
                            "source": "twelvedata",
                            "quality": "stale",
                            "classification": "LAST_AVAILABLE",
                            "transport": "REST_POLLING",
                            "errorCode": None,
                        }
                    # Fallback to secondary provider via fetch_bars
                    try:
                        alt_p, alt_res = fetch_bars(None, symbol, start, end, "1D", user_id, allow_fallback=True)
                        source_id = str(alt_res.provenance.get("provider", alt_p.id))
                        return _quote_from_result(
                            requested, display, group, alt_res.frame, source_id, "eod", "LAST_AVAILABLE", _transport(alt_res)
                        )
                    except Exception:
                        return _unavailable(requested, display, group, pe.code or "RATE_LIMITED")

            # Route instruments not served by Twelve Data to their verified primary provider
            # (e.g. yfinance for commodity/metal futures, indices, and global equities).
            if "yfinance" in inst.providers:
                try:
                    yf_p = get_provider("yfinance", user_id=user_id)
                    yq = yf_p.fetch_quote(symbol)  # type: ignore[attr-defined]
                    is_open = bool(yq.get("isMarketOpen", False))
                    return {
                        "symbol": requested,
                        "display": display,
                        "group": group,
                        "status": "ok",
                        "price": float(yq["price"]),
                        "change": yq.get("change"),
                        "changePct": yq.get("changePct"),
                        "prevClose": yq.get("prevClose"),
                        "dayHigh": yq.get("dayHigh"),
                        "dayLow": yq.get("dayLow"),
                        "volume": float(yq.get("volume") or 0.0),
                        "asOf": yq.get("datetime") or dt.datetime.now(dt.UTC).isoformat(),
                        "source": "yfinance",
                        "quality": "delayed" if is_open else "eod",
                        "classification": "DELAYED" if is_open else "END_OF_DAY",
                        "transport": "REST_POLLING",
                        "errorCode": None,
                    }
                except Exception:
                    pass

            provider, result = fetch_bars(None, symbol, start, end, "1D", user_id, allow_fallback=True)
            source = str(result.provenance.get("provider", provider.id)) if result.provenance else provider.id
            return _quote_from_result(
                requested,
                display,
                group,
                result.frame,
                source,
                "eod",
                classification="END_OF_DAY",
                transport=_transport(result),
            )
        except ProviderError as e:
            return _unavailable(requested, display, group, e.code)
        except Exception as e:
            log.warning("Unexpected error fetching quote for %s: %s", requested, e)
            return _unavailable(requested, display, group, "PROVIDER_ERROR")

    # Fetch concurrently with a bounded pool. The previous sequential loop let
    # a 40-symbol cold sweep exceed the 60 s gateway timeout (504) because the
    # yfinance provider spaces requests ~1 s apart; per-symbol failures stay
    # isolated to their own card.
    if len(raw) == 1:
        items = [_quote_one(raw[0])]
    else:
        workers = max(1, min(_QUOTE_WORKERS, len(raw)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quotes") as pool:
            items = list(pool.map(_quote_one, raw))
    return {"generatedAt": now.isoformat(), "items": items}


@router.get("/api/v1/market/series")
def series(
    symbol: str = Query(default=""),
    interval: str = Query(default="1D"),
    days: int = Query(default=365),
    u: User = Depends(current_user),  # noqa: B008
):
    raw_sym = (symbol or "").strip()
    sym = normalize_symbol(raw_sym)
    inst = get_instrument(sym) if sym else None
    if inst is None:
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": f"unknown instrument {symbol!r}"}
        )
    canon_interval = CANONICAL_INTERVALS.get((interval or "1D").strip())
    if canon_interval is None:
        raise HTTPException(
            422,
            detail={
                "code": "BAD_INPUT",
                "message": f"unsupported interval {interval!r} (valid: 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M)",
            },
        )
    interval = canon_interval
    if not 1 <= days <= 1825:
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": "days must be within 1..1825"}
        )
    # On weekends/holidays, a 1-2 day lookback for non-crypto intraday intervals
    # falls entirely inside closed hours and returns 0 bars. Widen automatically
    # so 1m/5m/15m charts always show recent trading sessions.
    effective_days = days
    if interval in INTRADAY_INTERVALS and inst.asset_class != "crypto":
        if interval == "1m":
            effective_days = max(effective_days, 5)
        elif interval in ("5m", "15m", "30m"):
            effective_days = max(effective_days, 7)
    now = dt.datetime.now(dt.UTC)
    end = now.strftime("%Y-%m-%d")
    start = (now - dt.timedelta(days=effective_days)).strftime("%Y-%m-%d")
    user_id = getattr(u, "id", None)
    try:
        # User-facing market charts: intelligent asset-class routing with automatic fallback
        provider, result = fetch_bars(
            None, sym, start, end, interval, user_id, allow_fallback=True
        )
    except ProviderError as e:
        status = http_status_for_code(e.code)
        if e.code in ("BAD_INPUT", "UNKNOWN_SYMBOL", "DATA_NOT_IN_STORE", "EMPTY_DATA", "NO_DATA", "UNSUPPORTED_INSTRUMENT"):
            status = 422
        raise HTTPException(status, detail={"code": e.code, "message": str(e)}) from e
    frame = result.frame.tail(_MAX_BARS) if result.frame is not None else result.frame
    bars = []
    if frame is not None:
        for ts, row in frame.iterrows():
            bars.append(
                {
                    "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "o": float(row["open"]),
                    "h": float(row["high"]),
                    "l": float(row["low"]),
                    "c": float(row["close"]),
                    "v": float(row["volume"]) if "volume" in frame.columns else 0.0,
                }
            )
    prov = result.provenance or {}
    provider_id = str(prov.get("provider", provider.id))
    served_now = dt.datetime.now(dt.UTC)
    timestamps: list[dt.datetime] = []
    if frame is not None:
        for ts in frame.index:
            if hasattr(ts, "to_pydatetime"):
                parsed = ts.to_pydatetime()
            elif isinstance(ts, dt.datetime):
                parsed = ts
            else:
                try:
                    parsed = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            timestamps.append(parsed.astimezone(dt.UTC))
    fetched_at: dt.datetime | None = None
    fetched_raw = prov.get("fetched_at") or prov.get("retrieved_at")
    if fetched_raw:
        try:
            fetched_at = dt.datetime.fromisoformat(str(fetched_raw).replace("Z", "+00:00"))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=dt.UTC)
        except ValueError:
            fetched_at = None
    freshness = freshness_metadata(
        provider=provider_id,
        interval=interval,
        asset_class=inst.asset_class,
        symbol=sym,
        candle_timestamps=timestamps,
        now=served_now,
        fetched_at=fetched_at,
        served_from_cache=prov.get("cache") == "hit",
        cache_age_s=int(prov.get("cache_age_s") or 0),
    )
    out_sym = raw_sym if ("/" in raw_sym or raw_sym in ("BTC/USD", "XAU/USD")) else sym
    return {
        "symbol": out_sym,
        "display": inst.display,
        "interval": interval,
        "provider": provider_id,
        "bars": bars,
        "provenance": result.provenance or {},
        "freshness": freshness,
        "generatedAt": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Public (pre-login) market data
#
# A visitor must see a real market chart on the landing page without a session.
# The surface is deliberately narrow: GET only, no body, no arbitrary symbol or
# URL proxying, a strict allowlist derived from the instrument registry, a hard
# candle limit, a short server-side cache with single-flight, bounded stale
# fallback, and a per-IP rate limit.
# ---------------------------------------------------------------------------

_PUBLIC_PROVIDER = os.environ.get("PUBLIC_MARKET_PROVIDER", "twelvedata")
_PUBLIC_DEFAULT_SYMBOL = os.environ.get("PUBLIC_MARKET_DEFAULT_SYMBOL", "BTC/USD")
_PUBLIC_INTERVALS = ("1D", "1H", "1W", "1M")
_PUBLIC_INTERVAL_DAYS = {"1H": 60, "1D": 365, "1W": 1825, "1M": 1825}
# Cache TTL by interval: short for intraday, longer for daily/weekly.
_PUBLIC_TTL_S = {"1H": 60, "1D": 300, "1W": 900, "1M": 900}
# How long last-known-good data may be served, labelled ``stale``, after a
# provider failure. Beyond this the endpoint must return a truthful error.
_PUBLIC_STALE_MAX_S = {"1H": 3600, "1D": 172800, "1W": 604800, "1M": 604800}
_PUBLIC_MAX_BARS = int(os.environ.get("PUBLIC_MARKET_MAX_BARS", "500"))
_PUBLIC_DEFAULT_LIMIT = int(os.environ.get("PUBLIC_MARKET_DEFAULT_LIMIT", "250"))
_PUBLIC_RATE_MAX = int(os.environ.get("PUBLIC_MARKET_RATE_LIMIT", "60"))
_PUBLIC_RATE_WINDOW_S = 60
_PUBLIC_RATE_MAX_KEYS = 5000

_PUBLIC_ASSET_CLASSES = frozenset({"equity", "etf", "crypto", "index", "commodity"})
_PUBLIC_SYMBOL_MAX = 32
_PUBLIC_SYMBOL_RE = re.compile(rf"^[A-Za-z0-9^=.\-_/]{{1,{_PUBLIC_SYMBOL_MAX}}}$")

_public_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_public_key_locks: dict[tuple[str, str], threading.Lock] = {}
_public_guard = threading.Lock()
_public_rate: dict[str, list[float]] = {}
_public_rate_guard = threading.Lock()


def _public_instruments() -> dict[str, Any]:
    """Allowlisted public instruments: registered, backtest-eligible and
    servable by the configured public provider."""
    if _PUBLIC_PROVIDER not in enabled_ids():
        return {}
    out: dict[str, Any] = {}
    for inst in list_instruments():
        if inst.asset_class not in _PUBLIC_ASSET_CLASSES:
            continue
        if not inst.backtest_eligible:
            continue
        if _PUBLIC_PROVIDER not in inst.providers:
            continue
        if not [i for i in _PUBLIC_INTERVALS if i in inst.timeframes]:
            continue
        out[inst.symbol] = inst
        if inst.symbol == "BTC-USD":
            out["BTC/USD"] = inst
    return out


def _public_intervals(inst: Any) -> list[str]:
    return [i for i in _PUBLIC_INTERVALS if i in inst.timeframes]


def _public_default_symbol(insts: dict[str, Any]) -> str | None:
    if "BTC/USD" in insts:
        return "BTC/USD"
    if _PUBLIC_DEFAULT_SYMBOL in insts:
        return _PUBLIC_DEFAULT_SYMBOL
    return next(iter(insts), None)


def _public_key_lock(key: tuple[str, str]) -> threading.Lock:
    with _public_guard:
        lock = _public_key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _public_key_locks[key] = lock
        return lock


def _public_rate_ok(ip: str) -> tuple[bool, int]:
    now = time.time()
    with _public_rate_guard:
        if ip not in _public_rate and len(_public_rate) >= _PUBLIC_RATE_MAX_KEYS:
            for k in list(_public_rate):
                if not _public_rate[k] or now - _public_rate[k][-1] >= _PUBLIC_RATE_WINDOW_S:
                    del _public_rate[k]
            while len(_public_rate) >= _PUBLIC_RATE_MAX_KEYS:
                _public_rate.pop(next(iter(_public_rate)))
        hits = [t for t in _public_rate.get(ip, []) if now - t < _PUBLIC_RATE_WINDOW_S]
        if len(hits) >= _PUBLIC_RATE_MAX:
            _public_rate[ip] = hits
            retry = max(1, int(_PUBLIC_RATE_WINDOW_S - (now - hits[0])))
            return False, retry
        hits.append(now)
        _public_rate[ip] = hits
        return True, 0


def _public_error(
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    retry_after: int | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    headers: dict[str, str] = {}
    if retry_after is not None:
        body["retryAfterSeconds"] = int(retry_after)
        headers["Retry-After"] = str(int(retry_after))
    return JSONResponse(status_code=status, content=body, headers=headers)


def _frame_to_candles(frame: Any) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    if frame is None:
        return candles
    for ts, row in frame.iterrows():
        candles.append(
            {
                "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]) if "volume" in frame.columns else 0.0,
            }
        )
    return candles


def _validate_candles(candles: list[dict[str, Any]]) -> None:
    """Enforce the documented candle integrity rules.

    Raises ``ValueError`` when a returned series is not internally consistent;
    callers turn that into a truthful 502 instead of rendering bad data.
    """
    prev: dt.datetime | None = None
    for c in candles:
        vals = (c["o"], c["h"], c["l"], c["c"], c["v"])
        if any(not math.isfinite(float(v)) for v in vals):
            raise ValueError("non-finite price/volume")
        if c["v"] < 0:
            raise ValueError("negative volume")
        if c["l"] > min(c["o"], c["c"]) + 1e-9 or c["h"] < max(c["o"], c["c"]) - 1e-9:
            raise ValueError("high/low do not enclose open/close")
        try:
            ts = dt.datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError("unparseable timestamp") from e
        if prev is not None and ts <= prev:
            raise ValueError("timestamps are not strictly ascending")
        prev = ts


def _public_payload(
    symbol: str,
    inst: Any,
    interval: str,
    candles: list[dict[str, Any]],
    *,
    provider: str,
    retrieved_at: str,
    data_status: str,
    cache_age: int,
    stale_since: str | None = None,
) -> dict[str, Any]:
    limited = candles[-_PUBLIC_MAX_BARS :] if _PUBLIC_MAX_BARS else candles
    payload: dict[str, Any] = {
        "symbol": symbol,
        "displayName": inst.display,
        "assetClass": inst.asset_class,
        "currency": inst.quote_currency or inst.base_currency,
        "provider": provider,
        "interval": interval,
        "candles": limited,
        "lastCandleTime": limited[-1]["t"] if limited else None,
        "retrievedAt": retrieved_at,
        "dataStatus": data_status,
        "cacheAgeSeconds": max(0, int(cache_age)),
    }
    if stale_since:
        payload["staleSince"] = stale_since
    return payload


@router.get("/api/v1/public/market/instruments")
def public_instruments() -> dict[str, Any]:
    """Allowlisted symbols the public chart can serve (no auth, no secrets)."""
    insts = _public_instruments()
    items = []
    seen = set()
    for inst in insts.values():
        if inst.symbol in seen:
            continue
        seen.add(inst.symbol)
        ivs = _public_intervals(inst)
        if not ivs:
            continue
        items.append(
            {
                "symbol": inst.symbol,
                "displayName": inst.display,
                "assetClass": inst.asset_class,
                "currency": inst.quote_currency or inst.base_currency,
                "intervals": ivs,
            }
        )
        if inst.symbol == "BTC-USD":
            items.append(
                {
                    "symbol": "BTC/USD",
                    "displayName": inst.display,
                    "assetClass": inst.asset_class,
                    "currency": inst.quote_currency or inst.base_currency,
                    "intervals": ivs,
                }
            )
    return {
        "items": items,
        "defaultSymbol": _public_default_symbol(insts),
        "provider": _PUBLIC_PROVIDER,
    }


@router.post("/api/v1/public/market/ws-ticket")
def public_ws_ticket(request: Request, response: Response) -> dict[str, Any]:
    """Exchange a public rate-limited request for a short-lived single-use WS ticket."""
    from .streaming import issue_ws_ticket

    response.headers["Cache-Control"] = "no-store"
    ip = client_ip_from(
        request.client.host if request.client else "?",
        {k.lower(): v for k, v in request.headers.items()},
    )
    allowed, retry = _public_rate_ok(ip)
    if not allowed:
        return _public_error(
            429,
            "RATE_LIMITED",
            "Too many requests for public market data.",
            retryable=True,
            retry_after=retry,
        )
    ticket, ttl = issue_ws_ticket("public")
    return {"ticket": ticket, "expiresIn": ttl}


@router.get("/api/v1/public/market/series")
def public_series(
    request: Request,
    response: Response,
    symbol: str = Query(default=""),
    interval: str = Query(default="1D"),
    limit: int = Query(default=_PUBLIC_DEFAULT_LIMIT),
) -> Any:
    """Read-only public candles for the landing-page chart.

    - symbol must be in the instrument allowlist
    - interval must be one the allowlisted instrument actually supports
    - limit is clamped to a hard maximum (never arbitrary history)
    """
    ip = client_ip_from(
        request.client.host if request.client else "?",
        {k.lower(): v for k, v in request.headers.items()},
    )
    allowed, retry = _public_rate_ok(ip)
    if not allowed:
        return _public_error(
            429,
            "RATE_LIMITED",
            "Too many requests for public market data.",
            retryable=True,
            retry_after=retry,
        )

    insts = _public_instruments()
    if not insts:
        return _public_error(
            503,
            "PROVIDER_NOT_CONFIGURED",
            "No public market-data provider is configured.",
            retryable=False,
        )

    # Validate the raw symbol BEFORE it can reach a cache key, log line or
    # provider URL. Case/whitespace normalization happens only after the
    # safe-character and length checks.
    raw_symbol = (symbol or "").strip()
    if raw_symbol and not _PUBLIC_SYMBOL_RE.fullmatch(raw_symbol):
        return _public_error(
            400,
            "BAD_SYMBOL",
            "Symbol must be 1–32 characters from A-Z, 0-9 and ^ = . - _ /.",
            retryable=False,
        )

    canonical_default = _public_default_symbol(insts) or "BTC/USD"
    out_symbol = raw_symbol or canonical_default
    sym = normalize_symbol(out_symbol)
    inst = insts.get(sym) or insts.get(out_symbol)
    if inst is None:
        return _public_error(
            404,
            "UNKNOWN_SYMBOL",
            f"Symbol {raw_symbol[:32]!r} is not available on the public chart.",
            retryable=False,
        )

    supported = _public_intervals(inst)
    if interval not in supported:
        return _public_error(
            400,
            "BAD_INTERVAL",
            f"Interval {interval!r} is not supported for {sym} (supported: {', '.join(supported)}).",
            retryable=False,
        )
    if limit < 1 or limit > _PUBLIC_MAX_BARS:
        return _public_error(
            400,
            "BAD_LIMIT",
            f"limit must be within 1..{_PUBLIC_MAX_BARS}.",
            retryable=False,
        )

    # Public, read-only data: allow short shared caching, never cookies.
    response.headers["Cache-Control"] = f"public, max-age={_PUBLIC_TTL_S[interval]}"
    response.headers["Vary"] = "Accept-Encoding"

    key = (out_symbol, interval)
    lock = _public_key_lock(key)
    with lock:
        cached = _public_cache.get(key)
        now = time.monotonic()
        ttl = _PUBLIC_TTL_S[interval]

        if cached is not None and now - cached[0] < ttl:
            age = int(now - cached[0])
            payload = copy.deepcopy(cached[1])
            payload["dataStatus"] = "cached"
            payload["cacheAgeSeconds"] = age
            payload["candles"] = payload["candles"][-limit:]
            return payload

        now_dt = dt.datetime.now(dt.UTC)
        end = now_dt.strftime("%Y-%m-%d")
        start = (now_dt - dt.timedelta(days=_PUBLIC_INTERVAL_DAYS[interval])).strftime("%Y-%m-%d")

        try:
            provider, result = fetch_bars(
                _PUBLIC_PROVIDER, sym, start, end, interval, allow_fallback=False
            )
            candles = _frame_to_candles(result.frame)
            if not candles:
                raise ProviderError(_PUBLIC_PROVIDER, "EMPTY_DATA", "provider returned no candles")
            _validate_candles(candles)
        except ValueError:
            return _public_error(
                502,
                "INVALID_CANDLES",
                "The market-data provider returned an inconsistent candle series.",
                retryable=True,
            )
        except ProviderError as e:
            # Bounded last-known-good fallback, explicitly labelled stale.
            if cached is not None and now - cached[0] <= _PUBLIC_STALE_MAX_S[interval]:
                age = int(now - cached[0])
                payload = copy.deepcopy(cached[1])
                payload["dataStatus"] = "stale"
                payload["cacheAgeSeconds"] = age
                payload["staleSince"] = payload.get("retrievedAt")
                payload["candles"] = payload["candles"][-limit:]
                return payload
            return _public_provider_error(e)

        retrieved_at = str((result.provenance or {}).get("fetched_at") or now_dt.isoformat())
        provider_id = str((result.provenance or {}).get("provider", provider.id))
        prov = result.provenance or {}
        cache_age = int(prov.get("cache_age_s") or 0)
        # Derive an honest public status from the same freshness rules as the
        # authenticated series endpoint. The configured public provider is a
        # delayed/EOD source, so a non-stale response is reported as delayed.
        candle_ts: list[dt.datetime] = []
        for c in candles:
            try:
                parsed = dt.datetime.fromisoformat(str(c["t"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            candle_ts.append(
                parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed.astimezone(dt.UTC)
            )
        fetched_at: dt.datetime | None = None
        if retrieved_at:
            try:
                fetched_at = dt.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
            except ValueError:
                fetched_at = None
        freshness = freshness_metadata(
            provider=provider_id,
            interval=interval,
            asset_class=getattr(inst, "asset_class", None),
            symbol=sym,
            candle_timestamps=candle_ts,
            now=dt.datetime.now(dt.UTC),
            fetched_at=fetched_at,
            served_from_cache=prov.get("cache") == "hit",
            cache_age_s=cache_age,
        )
        if freshness["is_stale"]:
            data_status = "stale"
        elif prov.get("cache") == "hit":
            data_status = "cached"
        else:
            data_status = "live" if provider_id == "twelvedata" else "delayed"
        payload = _public_payload(
            out_symbol,
            inst,
            interval,
            candles,
            provider=provider_id,
            retrieved_at=retrieved_at,
            data_status=data_status,
            cache_age=cache_age,
        )
        payload["freshness"] = freshness
        _public_cache[key] = (time.monotonic(), copy.deepcopy(payload))
        payload["candles"] = payload["candles"][-limit:]
        return payload


def _public_provider_error(e: ProviderError) -> JSONResponse:
    """Map a provider failure onto the documented public error contract."""
    code = e.code or "UPSTREAM_UNAVAILABLE"
    if code in ("UNKNOWN_SYMBOL",):
        return _public_error(404, code, str(e), retryable=False)
    if code in ("BAD_INPUT", "DATA_NOT_IN_STORE"):
        return _public_error(400, code, str(e), retryable=False)
    if code in ("EMPTY_DATA", "PROVIDER_NO_DATA"):
        return _public_error(404, "NO_DATA", str(e), retryable=False)
    if code in ("RATE_LIMITED",):
        retry_after = int(getattr(e, "retry_after", None) or _PUBLIC_RATE_WINDOW_S)
        return _public_error(429, code, str(e), retryable=True, retry_after=retry_after)
    if code == "PROVIDER_NOT_CONFIGURED":
        return _public_error(503, code, str(e), retryable=False)
    status = http_status_for_code(code)
    if status not in (502, 503, 504):
        status = 502
    return _public_error(status, code, str(e), retryable=True)


# ---------------------------------------------------------------------------
# Cryptocurrency reference and search endpoints (Twelve Data official API)
# ---------------------------------------------------------------------------


@router.get("/api/v1/market/crypto/pairs")
def crypto_pairs(
    base: str = Query(default=""),
    quote: str = Query(default=""),
    exchange: str = Query(default=""),
):
    """Retrieve supported cryptocurrency pairs via Twelve Data /cryptocurrencies reference API."""
    from .data_providers.twelvedata import TwelveDataProvider

    td = TwelveDataProvider()
    pairs = td.get_cryptocurrencies(
        currency_base=base or None,
        currency_quote=quote or None,
        exchange=exchange or None,
    )
    return {"total": len(pairs), "items": pairs}


@router.get("/api/v1/market/crypto/exchanges")
def crypto_exchanges():
    """Retrieve supported cryptocurrency exchanges via Twelve Data /cryptocurrency_exchanges API."""
    from .data_providers.twelvedata import TwelveDataProvider

    td = TwelveDataProvider()
    exchanges = td.get_cryptocurrency_exchanges()
    return {"total": len(exchanges), "items": exchanges}


@router.get("/api/v1/market/search")
def search_market_symbols(q: str = Query(default="")):
    """Universal symbol lookup across registered universe and Twelve Data."""
    query = (q or "").strip()
    if not query:
        return {"items": []}

    results: list[dict[str, Any]] = []
    seen = set()

    # 1. First check registered instruments
    upper_q = query.upper()
    for inst in list_instruments():
        if upper_q in inst.symbol.upper() or upper_q in inst.display.upper():
            results.append({
                "symbol": inst.symbol,
                "display": inst.display,
                "assetClass": inst.asset_class,
                "exchange": inst.metadata.get("exchange", ""),
                "source": "registered",
            })
            seen.add(inst.symbol)

    # 2. Query Twelve Data symbol search if configured
    if _td_configured():
        from .data_providers.twelvedata import TwelveDataProvider

        td = TwelveDataProvider()
        remote = td.search_symbols(query)
        for item in remote[:15]:
            sym = str(item.get("symbol", ""))
            if sym and sym not in seen:
                results.append({
                    "symbol": sym,
                    "display": item.get("instrument_name", sym),
                    "assetClass": item.get("instrument_type", "unknown").lower(),
                    "exchange": item.get("exchange", ""),
                    "source": "twelvedata",
                })
                seen.add(sym)

    return {"total": len(results), "items": results}

