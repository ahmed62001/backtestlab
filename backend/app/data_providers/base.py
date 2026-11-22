"""DataProvider interface + shared plumbing (cache, retry, rate limit, guards).

Every provider is OPTIONAL and isolated in its own module; the app runs with
none of them installed (the fixture-backed `local` provider and `synthetic`
have no external deps). There is NO silent fallback to synthetic data: if the
chosen provider fails, the caller gets a ProviderError that names the provider.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
MAX_BARS = int(os.environ.get("MAX_BARS", "2000"))
CACHE_TTL_S = int(os.environ.get("DATA_CACHE_TTL_S", "86400"))
CACHE_DIR = Path(os.environ.get("DATA_CACHE_DIR", "/tmp/btlab_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = Path(os.environ.get("DATA_UPLOAD_DIR", "/tmp/btlab_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RETRY_ATTEMPTS = int(os.environ.get("DATA_FETCH_RETRIES", "3"))
RETRY_BACKOFF_S = float(os.environ.get("DATA_FETCH_BACKOFF_S", "0.5"))


# ---- Provider capability metadata ---------------------------------------------


class Category(StrEnum):
    """Provider category for grouping in the catalog UI."""

    EQUITIES = "equities"
    CRYPTO = "crypto"
    FX = "fx"
    MACRO = "macro"
    LOCAL = "local"
    SYNTHETIC = "synthetic"
    UPLOAD = "upload"


@dataclass
class Capabilities:
    """Provider capability metadata exposed through the catalog endpoint."""

    category: Category = Category.EQUITIES
    asset_classes: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ("1D",)
    supports_adjusted: bool = False
    requires_package: str | None = None
    requires_key_env: str | None = None
    # Accepted fallback variable name (e.g. MASSIVE_API_KEY preferred,
    # POLYGON_API_KEY still accepted). Exposed in the catalog for operators.
    requires_key_env_legacy: str | None = None
    rate_limit_per_minute: int = 60
    description_en: str = ""
    description_ar: str = ""


# ---- Typed provider error taxonomy -------------------------------------------

# Stable, machine-readable codes. The message ALWAYS names the provider so
# failures are never silent. Each code maps to a consistent HTTP status so the
# API layer can translate without re-inspecting the message.
#
#   UPSTREAM_BLOCKED       anti-bot / challenge / 403 / 429-after-retries
#   UPSTREAM_UNAVAILABLE   timeout / 5xx / network down / DNS failure
#   UPSTREAM_BAD_RESPONSE  unparseable / malformed body
#   UNKNOWN_SYMBOL         upstream clearly says "no such symbol"
#   PROVIDER_NOT_CONFIGURED missing API key or optional package not installed
#   RATE_LIMITED           explicit rate-limit signal (honor Retry-After)
#   BAD_INPUT              caller supplied an invalid symbol/interval/range
#   EMPTY_DATA             request succeeded but yielded zero usable bars
#   PROVIDER_NO_DATA       provider reachable but returned no bars (never retried)
#   PROVIDER_DOWN          legacy catch-all (kept for back-compat)
#   PROVIDER_TIMEOUT       legacy timeout alias
#   DATA_NOT_IN_STORE      local_store has no coverage for the requested range
#   DATA_STORE_UNAVAILABLE persistent store (DB) unavailable / read-only

ERR_UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"
ERR_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
ERR_UPSTREAM_BAD_RESPONSE = "UPSTREAM_BAD_RESPONSE"
ERR_UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
ERR_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_BAD_INPUT = "BAD_INPUT"
ERR_EMPTY_DATA = "EMPTY_DATA"
ERR_NO_DATA = "PROVIDER_NO_DATA"
ERR_DATA_STORE_UNAVAILABLE = "DATA_STORE_UNAVAILABLE"
ERR_PROVIDER_COOLDOWN = "PROVIDER_COOLDOWN"
# The credential is present but the provider rejects it (401/403 "bad key").
ERR_INVALID_KEY = "PROVIDER_INVALID_KEY"
# The credential is valid but the account lacks the product/asset entitlement
# (e.g. Massive 403 NOT_AUTHORIZED). Distinct from an invalid key so operators
# never "fix" an entitlement problem by rotating a working key.
ERR_NOT_ENTITLED = "PROVIDER_NOT_ENTITLED"

# Never sleep longer than this for a single Retry-After/backoff step. A hostile
# or misconfigured upstream must not pin a request thread for minutes.
RETRY_MAX_WAIT_S = float(os.environ.get("DATA_RETRY_MAX_WAIT_S", "30"))


def resolve_env_key(
    preferred: str,
    legacy: str | None,
    placeholders: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Resolve a provider credential with deterministic precedence.

    The preferred variable always wins when it holds a non-placeholder value;
    the legacy variable is the backward-compatible fallback. Empty values and
    well-known placeholders never count as configured, so a placeholder can
    never shadow a real key in the other variable.
    """
    for name in (preferred, legacy):
        if not name:
            continue
        value = os.environ.get(name, "").strip()
        if value and value.lower() not in placeholders:
            return value
    return ""


@dataclass
class TokenBucket:
    """Token bucket rate limiter."""

    capacity: int  # max tokens
    refill_rate_per_s: float  # tokens per second

    def __init__(self, capacity: int, refill_rate_per_s: float) -> None:
        self.capacity = capacity
        self.refill_rate_per_s = refill_rate_per_s
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate_per_s)
        self._last_refill = now

    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rate limited."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def try_acquire(self) -> bool:
        """Non-blocking token acquisition."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


ERR_PROVIDER_DOWN = "PROVIDER_DOWN"
ERR_PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
ERR_DATA_NOT_IN_STORE = "DATA_NOT_IN_STORE"

# Codes that describe a permanent outcome. Retrying one of these can only
# repeat an identical upstream request (wasted quota) or mask a caller error.
NON_RETRYABLE_CODES = frozenset(
    {
        ERR_UNKNOWN_SYMBOL,
        ERR_BAD_INPUT,
        ERR_NOT_CONFIGURED,
        ERR_EMPTY_DATA,
        ERR_NO_DATA,
        ERR_DATA_NOT_IN_STORE,
        ERR_PROVIDER_COOLDOWN,
        ERR_INVALID_KEY,
        ERR_NOT_ENTITLED,
    }
)

# Codes that represent a transient upstream condition worth a bounded retry.
RETRYABLE_CODES = frozenset(
    {
        ERR_UPSTREAM_BLOCKED,
        ERR_UPSTREAM_UNAVAILABLE,
        ERR_UPSTREAM_BAD_RESPONSE,
        ERR_PROVIDER_DOWN,
        ERR_PROVIDER_TIMEOUT,
        ERR_RATE_LIMITED,
    }
)

# HTTP status mapping, applied consistently across the API.
#
# A create operation must not answer 404 because an upstream source had no
# bars: 404 is reserved for a missing *resource* (a backtest/job id). "The
# provider is reachable but has no data for this symbol/range" is an
# unprocessable request (422) with a distinct stable code.
CODE_HTTP_STATUS: dict[str, int] = {
    ERR_UPSTREAM_BLOCKED: 502,
    ERR_UPSTREAM_BAD_RESPONSE: 502,
    ERR_UPSTREAM_UNAVAILABLE: 503,
    ERR_PROVIDER_DOWN: 503,
    ERR_PROVIDER_TIMEOUT: 503,
    ERR_NOT_CONFIGURED: 503,
    ERR_RATE_LIMITED: 429,
    ERR_UNKNOWN_SYMBOL: 422,
    ERR_DATA_NOT_IN_STORE: 422,
    ERR_BAD_INPUT: 422,
    ERR_EMPTY_DATA: 422,
    ERR_NO_DATA: 422,
    ERR_PROVIDER_COOLDOWN: 503,
    ERR_DATA_STORE_UNAVAILABLE: 503,
    ERR_INVALID_KEY: 503,
    ERR_NOT_ENTITLED: 503,
}


def get_httpx_client(provider_id: str, timeout: float = 30.0) -> httpx.Client:
    """Get or create an httpx.Client for a provider with consistent settings.

    The cache key includes the timeout: a provider that first asks for 30s and
    later for 10s must not silently inherit the stale timeout.
    """
    key = (provider_id, float(timeout))
    if key not in _httpx_clients:
        _httpx_clients[key] = httpx.Client(
            timeout=float(timeout),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _httpx_clients[key]


def clear_httpx_clients() -> None:
    """Clear the httpx client cache (use for test isolation)."""
    global _httpx_clients
    _httpx_clients = {}


# Global httpx client cache keyed by (provider_id, timeout_seconds)
_httpx_clients: dict[tuple[str, float], httpx.Client] = {}


def http_status_for_code(code: str) -> int:
    """Map a provider error code to an HTTP status (default 502)."""
    return CODE_HTTP_STATUS.get(code, 502)


class ProviderError(RuntimeError):
    """A data provider failed. `code` is a stable machine code; the message
    ALWAYS names the provider so failures are never silent.

    ``retry_after`` carries an upstream Retry-After hint (seconds) when the
    provider supplied one. ``details`` holds safe, non-secret context for the
    API error payload (symbol/range etc.).
    """

    def __init__(
        self,
        provider: str,
        code: str,
        message: str,
        *,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.provider = provider
        self.code = code
        self.retry_after = retry_after
        self.details = details or {}
        super().__init__(f"data provider '{provider}': {message}")


class ProviderNoDataError(ProviderError):
    """Provider was reachable but returned zero usable bars (permanent)."""

    def __init__(self, provider: str, message: str, **kwargs: Any):
        super().__init__(provider, ERR_NO_DATA, message, **kwargs)


def classify_error(provider: str, exc: BaseException) -> ProviderError:
    """Map an arbitrary exception to a typed ProviderError code.

    Classifies common upstream/network failure shapes (HTTP status, time-outs,
    rate-limit headers, DNS/connect errors) without re-reading the message.
    Vendor/unknown exceptions fall back to a conservative code so a failure is
    never mistaken for "no such symbol".
    """
    # httpx-specific: inspect the status code and headers.
    # HTTPStatusError stores status_code on exc.response, not exc directly.
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)
    headers = getattr(exc, "headers", None) or {}
    retry_after: float | None = None
    try:
        raw_ra = headers.get("retry-after") if hasattr(headers, "get") else None
        if raw_ra is not None:
            retry_after = float(raw_ra)
    except (TypeError, ValueError):
        retry_after = None
    if status is not None:
        if status in (403, 401):
            code = ERR_UPSTREAM_BLOCKED
        elif status == 429:
            code = ERR_RATE_LIMITED
        elif status == 404:
            code = ERR_UNKNOWN_SYMBOL
        elif 500 <= status <= 599:
            code = ERR_UPSTREAM_UNAVAILABLE
        else:
            code = ERR_UPSTREAM_BAD_RESPONSE
    elif isinstance(
        exc,
        (httpx.TimeoutException, TimeoutError, ConnectionError, httpx.NetworkError, OSError),
    ) or type(exc).__name__.endswith("Timeout"):
        code = ERR_UPSTREAM_UNAVAILABLE
    else:
        # Retry-After present anywhere => rate limited.
        ra = headers.get("retry-after") if hasattr(headers, "get") else None
        if ra or type(exc).__name__ in ("RateLimitExceeded", "Timeout"):
            code = ERR_RATE_LIMITED
        elif type(exc).__name__ in ("BadSymbol", "InvalidSymbol"):
            code = ERR_UNKNOWN_SYMBOL
        elif type(exc).__name__ in ("NetworkError", "ExchangeNotAvailable"):
            code = ERR_UPSTREAM_UNAVAILABLE
        else:
            code = ERR_UPSTREAM_BAD_RESPONSE
    return ProviderError(
        provider,
        code,
        str(exc) or exc.__class__.__name__,
        retry_after=retry_after,
    )


@dataclass
class BarsResult:
    frame: pd.DataFrame
    provenance: dict[str, Any]
    warnings: list[dict[str, str]] = field(default_factory=list)


def normalize_ohlcv(df: pd.DataFrame, symbol: str, provider: str) -> pd.DataFrame:
    """Normalize any provider frame to the canonical OHLCV contract:
    UTC DatetimeIndex (sorted, unique), float open/high/low/close/volume."""
    if df is None or len(df) == 0:
        raise ProviderError(provider, ERR_NO_DATA, f"no data for {symbol!r}")
    out = df.copy()
    rename = {c: str(c).strip().lower() for c in out.columns}
    out = out.rename(columns=rename)
    missing = [c for c in ("open", "high", "low", "close") if c not in out.columns]
    if missing:
        raise ProviderError(provider, "BAD_INPUT", f"missing OHLC columns {missing} for {symbol!r}")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    if not isinstance(out.index, pd.DatetimeIndex):
        for cand in ("date", "trade_date", "datetime", "timestamp"):
            if cand in out.columns:
                out[cand] = pd.to_datetime(out[cand], utc=True, errors="coerce")
                out = out.set_index(cand)
                break
        else:
            out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out[OHLCV_COLUMNS].astype(float)
    out = out.tail(MAX_BARS)
    if len(out) == 0:
        raise ProviderError(provider, ERR_NO_DATA, f"all rows dropped while normalizing {symbol!r}")
    return out


def _cache_file(key: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".csv")


# Bumped when the *meaning* of cached frames changes. v2: intraday frames now
# carry true UTC instants (exchange timezone restored) instead of a mislabelled
# local wall clock. Old files are left on disk but are no longer addressed.
CACHE_SCHEMA_VERSION = "v2"


def cache_key(provider: str, symbol: str, start: str, end: str, interval: str) -> str:
    return f"{CACHE_SCHEMA_VERSION}|{provider}|{symbol}|{start}|{end}|{interval}"


_INTRADAY_CACHE_TTL_S: dict[str, int] = {
    "1m": 30,
    "5m": 60,
    "15m": 120,
    "30m": 180,
    "1H": 300,
    "4H": 600,
}


def cache_ttl_for_interval(interval: str) -> int:
    """Return an interval-aware disk cache TTL (short for intraday, CACHE_TTL_S for daily+)."""
    intraday = _INTRADAY_CACHE_TTL_S.get(interval)
    if intraday is not None:
        return min(CACHE_TTL_S, intraday)
    return CACHE_TTL_S


def cache_read(key: str, ttl_s: int | None = None) -> pd.DataFrame | None:
    ck = _cache_file(key)
    effective_ttl = CACHE_TTL_S if ttl_s is None else ttl_s
    if ck.exists() and time.time() - ck.stat().st_mtime < effective_ttl:
        try:
            return pd.read_csv(ck, index_col=0, parse_dates=True)
        except Exception:  # noqa: BLE001
            return None
    return None


def cache_written_at(key: str) -> dt.datetime | None:
    """UTC time the cached payload was written (the real provider fetch time).

    Serving a cache hit must report this, not "now": otherwise a 20-hour-old
    cached series would claim `cache_age = 0` and look freshly fetched.
    """
    ck = _cache_file(key)
    try:
        return dt.datetime.fromtimestamp(ck.stat().st_mtime, dt.UTC)
    except OSError:
        return None


def cache_write(key: str, df: pd.DataFrame) -> Path:
    ck = _cache_file(key)
    df.to_csv(ck)
    return ck


class _RateLimiter:
    """Process-local per-provider minimum spacing between fetches."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def wait(self, provider_id: str, min_interval_s: float) -> None:
        now = time.monotonic()
        prev = self._last.get(provider_id, 0.0)
        delta = now - prev
        if delta < min_interval_s:
            time.sleep(min_interval_s - delta)
        self._last[provider_id] = time.monotonic()


RATE_LIMITER = _RateLimiter()


def retry_delay(error: ProviderError, attempt: int) -> float:
    """Delay before retry ``attempt`` (0-based). Honors Retry-After, bounded.

    A 429/503 with an explicit Retry-After is respected (capped at
    ``RETRY_MAX_WAIT_S``); everything else uses linear backoff.
    """
    if error.retry_after is not None:
        return max(0.0, min(float(error.retry_after), RETRY_MAX_WAIT_S))
    return max(0.0, min(RETRY_BACKOFF_S * (attempt + 1), RETRY_MAX_WAIT_S))


def with_retries(fn: Callable[[], Any], provider_id: str, attempts: int = RETRY_ATTEMPTS) -> Any:
    """Retry only *transient* provider failures, with bounded backoff.

    Permanent outcomes (no data, unknown symbol, bad input, unconfigured
    provider) are raised immediately: repeating the same upstream request for
    an empty/200 response wastes provider quota and cannot change the result.
    """
    attempts = max(1, int(attempts))
    last: ProviderError | None = None
    for i in range(attempts):
        try:
            return fn()
        except ProviderError as e:
            if e.code not in RETRYABLE_CODES:
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = ProviderError(provider_id, ERR_PROVIDER_DOWN, str(e))
        if i < attempts - 1:
            time.sleep(retry_delay(last, i))
    if last is None:  # defensive: attempts >= 1 always sets `last`
        raise ProviderError(provider_id, ERR_PROVIDER_DOWN, "no attempt executed")
    raise last


# ---- Request-scoped response deduplication --------------------------------
# A single backtest/worker step can legitimately ask the same provider URL more
# than once (retry re-plans, fallback checks). Within one logical request we
# replay the successful JSON body instead of spending quota on an identical
# call. The scope is explicitly created per job and never survives it, so this
# is not an unbounded cache.
_http_scope: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "provider_http_scope", default=None
)
_MAX_SCOPE_ENTRIES = 64


@contextmanager
def request_scope() -> Iterator[None]:
    """Open a bounded, request-local HTTP response cache."""
    token = _http_scope.set({})
    try:
        yield
    finally:
        _http_scope.reset(token)


def _url_key(url: str, params: dict[str, Any] | None) -> str:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    return url + ("?" + urlencode(sorted(clean.items())) if clean else "")


def http_get_json(
    provider_id: str,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
) -> Any:
    """GET JSON inside the current request scope, deduplicating identical URLs.

    Only successful (2xx/JSON) responses are recorded. Errors are never cached,
    so a transient failure still retries according to ``with_retries``.
    """
    scope = _http_scope.get()
    key = _url_key(url, params)
    if scope is not None and key in scope:
        return scope[key]
    client = get_httpx_client(provider_id, timeout=timeout)
    resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    if scope is not None and len(scope) < _MAX_SCOPE_ENTRIES:
        scope[key] = data
    return data


class DataProvider:
    """Provider interface. Subclasses implement fetch_ohlcv_raw (network-free
    for local/synthetic/csv_upload; optional network for the rest)."""

    id: str = "base"
    name_en: str = "Base"
    name_ar: str = "أساسي"
    markets: tuple[str, ...] = ()
    intervals: tuple[str, ...] = ("1D",)
    # Market structure a provider can serve. Spot only by default; a futures /
    # perpetual provider must opt in explicitly so fallback can never swap a
    # spot instrument for a derivative series.
    market_types: tuple[str, ...] = ("spot",)
    requires_key: bool = False
    license_class: str = "unknown"
    adjusted: bool | None = None  # True split/div-adjusted, False raw, None unknown
    capabilities: Capabilities = Capabilities()  # default capabilities
    min_interval_s: float = 0.0
    # When a provider returns an anti-bot/challenge or rate-limit signal, park
    # it for this many seconds (shared through the DB) instead of letting every
    # request rediscover the block. 0 disables cooldown.
    cooldown_s: float = 0.0
    # Shared on-disk cache is safe for public provider data only. Per-user
    # providers (csv_upload) must set this False to prevent cross-tenant hits.
    cache_ok: bool = True

    def list_supported_markets(self) -> list[str]:
        return list(self.markets)

    def health_check(self) -> dict[str, Any]:
        """Cheap availability probe. No network unless overridden."""
        return {"available": True, "detail": ""}

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        """Provider-specific fetch (unnormalized). Override this."""
        raise NotImplementedError

    def fetch_ohlcv(self, symbol: str, start: str, end: str, interval: str = "1D") -> pd.DataFrame:
        """Normalized OHLCV frame (spec interface; no cache, with retries)."""
        from ..instruments import normalize_symbol

        symbol = normalize_symbol(symbol)
        if interval not in self.intervals:
            raise ProviderError(
                self.id,
                "BAD_INPUT",
                f"interval {interval!r} unsupported (supported: {self.intervals})",
            )
        with request_scope():
            return with_retries(
                lambda: normalize_ohlcv(
                    self.fetch_ohlcv_raw(symbol, start, end, interval), symbol, self.id
                ),
                self.id,
            )

    # ---- shared plumbing -------------------------------------------------
    def fetch_ohlcv_cached(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> BarsResult:
        from ..instruments import get_instrument, normalize_symbol

        requested_symbol = symbol
        symbol = normalize_symbol(symbol)
        if interval not in self.intervals:
            raise ProviderError(
                self.id,
                "BAD_INPUT",
                f"interval {interval!r} unsupported (supported: {self.intervals})",
            )
        key = cache_key(self.id, symbol, start, end, interval)
        hit = cache_read(key, ttl_s=cache_ttl_for_interval(interval)) if self.cache_ok else None
        if hit is not None:
            frame = normalize_ohlcv(hit, symbol, self.id)
            from_cache = True
        else:
            if self.min_interval_s:
                RATE_LIMITER.wait(self.id, self.min_interval_s)
            with request_scope():
                frame = with_retries(
                    lambda: normalize_ohlcv(
                        self.fetch_ohlcv_raw(symbol, start, end, interval), symbol, self.id
                    ),
                    self.id,
                )
            frame = frame.tail(MAX_BARS)
            if self.cache_ok:
                cache_write(key, frame)
            from_cache = False
        inst = get_instrument(symbol)
        served_at = dt.datetime.now(dt.UTC)
        written_at = cache_written_at(key) if from_cache else None
        fetched_at = written_at or served_at
        cache_age_s = max(0, int((served_at - fetched_at).total_seconds())) if from_cache else 0
        prov = {
            "provider": self.id,
            "requested_provider": self.id,
            "symbol": symbol,
            "requested_symbol": requested_symbol,
            "asset_class": inst.asset_class if inst else None,
            "market_type": (inst.metadata.get("market_type") if inst else None),
            "exchange": (inst.metadata.get("exchange") if inst else None),
            "base_currency": (inst.base_currency if inst else None),
            "quote_currency": (inst.quote_currency if inst else None),
            "interval": interval,
            "requested_start": start or None,
            "requested_end": end or None,
            "start": str(frame.index[0].date()) if len(frame) else None,
            "end": str(frame.index[-1].date()) if len(frame) else None,
            "bars": len(frame),
            "rows": len(frame),
            "dataHash": frame_hash(frame),
            "timezone": "UTC",
            "adjusted": self.adjusted,
            "price_adjustment": (
                "adjusted"
                if self.adjusted is True
                else "unadjusted"
                if self.adjusted is False
                else "unknown"
            ),
            "license_class": self.license_class,
            "fallback": False,
            "fallback_from": None,
            "fallback_reason": None,
            "retrieved_at": served_at.isoformat(),
            "served_at": served_at.isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "cache_age_s": cache_age_s,
            "served_from_cache": from_cache,
            "cache": ("hit" if from_cache else "miss") if self.cache_ok else "disabled",
            "cacheDir": str(CACHE_DIR),
        }
        return BarsResult(frame=frame, provenance=prov, warnings=[])


def frame_hash(df: pd.DataFrame) -> str:
    """Deterministic content hash of a normalized frame (provenance)."""
    payload = df.index.strftime("%Y-%m-%dT%H:%M:%SZ").tolist() + [
        round(float(x), 6) for x in df.to_numpy().ravel()
    ]
    return hashlib.sha256(repr(payload).encode()).hexdigest()
