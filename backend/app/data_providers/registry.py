"""Provider registry + env-driven selection.

DATA_PROVIDER_DEFAULT   default provider id when a request omits one
                        (dev default: yfinance; ENV=test default: synthetic).
DATA_PROVIDERS_ENABLED  comma list of selectable provider ids (default: all).
Only enabled providers are selectable; a disabled/unknown id is rejected with
a clear error (NO silent fallback to the default or to synthetic).
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from ..observability import redact
from .alphavantage import AlphaVantageProvider
from .base import (
    ERR_PROVIDER_COOLDOWN,
    BarsResult,
    Capabilities,
    DataProvider,
    ProviderError,
)
from .binance_public import BinancePublicProvider
from .ccxt_provider import CcxtProvider
from .coingecko import CoingeckoProvider
from .cooldown import cooldown_status, record_failure
from .csv_upload import CsvUploadProvider
from .frankfurter import FrankfurterProvider
from .fred import FredProvider
from .local_fixtures import LocalFixturesProvider
from .local_store import LocalStoreProvider
from .polygon import PolygonProvider
from .stooq import StooqProvider
from .synthetic import SyntheticProvider
from .tiingo import TiingoProvider
from .twelvedata import TwelveDataProvider
from .yfinance_provider import YFinanceProvider

# Registration order = UI order. All providers are optional; the app boots
# with none of the external dependencies installed.
_ALL: dict[str, type[DataProvider]] = {
    cls.id: cls
    for cls in (
        YFinanceProvider,
        CcxtProvider,
        AlphaVantageProvider,
        BinancePublicProvider,
        CoingeckoProvider,
        FrankfurterProvider,
        FredProvider,
        TiingoProvider,
        TwelveDataProvider,
        PolygonProvider,
        CsvUploadProvider,
        LocalFixturesProvider,
        LocalStoreProvider,
        SyntheticProvider,
        # Stooq is intentionally last: it is free but aggressively challenges
        # shared IPs. It is a useful fallback, not the first choice.
        StooqProvider,
    )
}

DEFAULT_ENABLED = ",".join(_ALL)

# The catalog endpoint performs live network health checks for public providers.
# It is unauthenticated, so every environment serves a short-lived cached
# snapshot instead of letting each anonymous request fan out to upstreams.
# Expired snapshots are served while one background thread refreshes them
# (stale-while-revalidate): a slow/down upstream never stalls the catalog.
_CATALOG_TTL_S = float(os.environ.get("PROVIDER_CATALOG_TTL_S", "60"))
_CATALOG_CACHE_ENABLED = os.environ.get("PROVIDER_CATALOG_CACHE", "1") not in (
    "0",
    "false",
    "False",
    "no",
)
_HEALTH_TIMEOUT_S = float(os.environ.get("PROVIDER_HEALTH_TIMEOUT_S", "2.0"))
_info_cache: tuple[float, dict[str, Any]] | None = None
_info_lock = threading.Lock()
_build_lock = threading.Lock()
_info_refreshing = False


def clear_provider_info_cache() -> None:
    """Drop the cached catalog snapshot (tests / config changes)."""
    global _info_cache, _info_refreshing
    with _info_lock:
        _info_cache = None
        _info_refreshing = False


def enabled_ids() -> list[str]:
    raw = os.environ.get("DATA_PROVIDERS_ENABLED", DEFAULT_ENABLED)
    wanted = [x.strip() for x in raw.split(",") if x.strip()]
    return [pid for pid in _ALL if pid in wanted]


def all_provider_ids() -> list[str]:
    """Every registered provider id, in catalog/UI order."""
    return list(_ALL)


def default_provider_id() -> str:
    explicit = os.environ.get("DATA_PROVIDER_DEFAULT", "").strip()
    if explicit:
        return explicit
    if os.environ.get("ENV", "dev") == "test":
        return "synthetic"
    return "yfinance"


def get_provider(provider_id: str, user_id: str | None = None) -> DataProvider:
    """Resolve a provider instance; raises ProviderError for unknown or
    disabled ids (validated against DATA_PROVIDERS_ENABLED).

    ``user_id`` is the verified JWT subject. Per-user providers (csv_upload)
    require it; public providers ignore it. It is never read from the request
    body, so a caller cannot select another tenant's namespace.
    """
    if provider_id not in _ALL:
        raise ProviderError(
            provider_id or "-", "BAD_INPUT", f"unknown data provider {provider_id!r}"
        )
    if provider_id not in enabled_ids():
        raise ProviderError(
            provider_id,
            "BAD_INPUT",
            f"data provider {provider_id!r} is not enabled (DATA_PROVIDERS_ENABLED)",
        )
    inst = _ALL[provider_id]()
    inst.user_id = user_id  # type: ignore[attr-defined]
    return inst


def resolve_for_request(requested: str | None, user_id: str | None = None) -> DataProvider:
    """Validate the optional request `data_provider` field; fall back to the
    configured default when omitted. Errors name the provider."""
    if requested is None or requested == "":
        requested = default_provider_id()
    return get_provider(requested, user_id=user_id)


def provider_infos() -> dict[str, Any]:
    """Payload for GET /api/v1/data-providers.

    Building the payload performs optional upstream health probes, so it is
    cached for ``PROVIDER_CATALOG_TTL_S`` (default 60s) in every environment.
    When a snapshot is stale it is still returned immediately and a single
    background thread refreshes it, keeping the public endpoint responsive even
    when an upstream is slow or unreachable.
    """
    global _info_refreshing
    if not _CATALOG_CACHE_ENABLED:
        return copy.deepcopy(_build_provider_infos())
    now = time.monotonic()
    with _info_lock:
        cached = _info_cache
        if cached is not None and now - cached[0] < _CATALOG_TTL_S:
            return copy.deepcopy(cached[1])
        if cached is not None:
            # Serve stale immediately; revalidate once in the background.
            if not _info_refreshing:
                _info_refreshing = True
                threading.Thread(
                    target=_background_refresh, name="provider-catalog-refresh", daemon=True
                ).start()
            return copy.deepcopy(cached[1])
    return copy.deepcopy(_build_and_store())


def _background_refresh() -> None:
    global _info_refreshing
    try:
        _build_and_store()
    finally:
        with _info_lock:
            _info_refreshing = False


def _build_and_store() -> dict[str, Any]:
    """Build once under a lock; concurrent callers share the same snapshot."""
    global _info_cache
    with _build_lock:
        with _info_lock:
            cached = _info_cache
            if cached is not None and time.monotonic() - cached[0] < _CATALOG_TTL_S:
                return cached[1]
        payload = _build_provider_infos()
        with _info_lock:
            _info_cache = (time.monotonic(), payload)
        return payload


def _safe_health(inst: DataProvider) -> dict[str, Any]:
    try:
        return inst.health_check()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "detail": redact(e)}


def _build_provider_infos() -> dict[str, Any]:
    enabled = enabled_ids()
    default = default_provider_id()
    entries: list[tuple[str, DataProvider]] = [(pid, cls()) for pid, cls in _ALL.items()]

    # Probe providers in parallel with a hard per-provider budget. A single
    # hanging upstream must not make the whole catalog slow.
    healths: dict[str, dict[str, Any]] = {}
    if entries:
        pool = ThreadPoolExecutor(max_workers=min(8, len(entries)))
        futures = {pool.submit(_safe_health, inst): pid for pid, inst in entries}
        for future, pid in futures.items():
            try:
                healths[pid] = future.result(timeout=_HEALTH_TIMEOUT_S)
            except FutureTimeout:
                healths[pid] = {
                    "available": False,
                    "detail": f"health check timed out after {_HEALTH_TIMEOUT_S:g}s",
                }
        # Do not block the response on stragglers; their own HTTP timeouts are
        # bounded and the next refresh will pick up the result.
        pool.shutdown(wait=False)

    items = []
    for pid, inst in entries:
        health = healths.get(pid, {"available": False, "detail": "not checked"})
        caps = inst.capabilities
        available = bool(health.get("available"))
        detail = redact(health.get("detail", ""))
        cooldown = cooldown_status(pid)
        if cooldown["active"]:
            available = False
            detail = f"cooling down after {cooldown['reason'] or 'upstream block'}"
        items.append(
            {
                "id": inst.id,
                "nameEn": inst.name_en,
                "nameAr": inst.name_ar,
                "category": caps.category.value
                if hasattr(caps.category, "value")
                else str(caps.category),
                "markets": inst.list_supported_markets(),
                "intervals": list(inst.intervals),
                "assetClasses": list(caps.asset_classes),
                "supportsAdjusted": caps.supports_adjusted,
                "requiresKey": inst.requires_key,
                "requiresPackage": caps.requires_package,
                "requiresKeyEnv": caps.requires_key_env,
                "requiresKeyEnvLegacy": getattr(caps, "requires_key_env_legacy", None),
                "rateLimitPerMinute": caps.rate_limit_per_minute,
                "descriptionEn": caps.description_en,
                "descriptionAr": caps.description_ar,
                "available": available,
                "availableDetail": detail,
                "retryAfter": int(cooldown["retryAfter"]) if cooldown["active"] else 0,
                "licenseClass": inst.license_class,
                "enabled": pid in enabled,
                "isDefault": pid == default,
            }
        )
        store_summary = getattr(inst, "store_summary", None)
        if callable(store_summary):
            try:
                items[-1]["storeSummary"] = store_summary()
            except Exception as e:  # noqa: BLE001
                items[-1]["storeSummary"] = {"error": redact(e)}
    return {"items": items, "default": default, "enabled": enabled}


FALLBACK_ENABLED = os.environ.get("DATA_PROVIDER_FALLBACK", "1") not in (
    "0",
    "false",
    "False",
    "no",
)

log = logging.getLogger("backtestlab.data_providers")

_REAL_CATEGORIES = {"equities", "crypto", "fx", "macro"}
_NON_RETRYABLE_CODES = {
    "UNKNOWN_SYMBOL",
    "BAD_INPUT",
    "PROVIDER_NOT_CONFIGURED",
    "EMPTY_DATA",
    "PROVIDER_NO_DATA",
    "DATA_NOT_IN_STORE",
}


def _provider_asset_class(pid: str) -> str | None:
    """Best-effort provider category for a provider id."""
    try:
        inst = _ALL[pid]()
        return inst.capabilities.category.value
    except Exception:  # noqa: BLE001
        return None


def _is_real_market_provider(pid: str) -> bool:
    """True for providers that serve real market/economic data."""
    return _provider_asset_class(pid) in _REAL_CATEGORIES


def _provider_capabilities(pid: str) -> Capabilities | None:
    cls = _ALL.get(pid)
    if cls is None:
        return None
    return cls().capabilities


def _validate_provider_for_instrument(provider: DataProvider, symbol: str, interval: str) -> None:
    """Reject a real provider that cannot serve this exact instrument.

    Local/synthetic/upload providers are development transports and are
    intentionally not constrained here; they never masquerade as production
    market data and cannot participate in fallback.
    """
    from ..instruments import get_instrument

    inst = get_instrument(symbol)
    if not _is_real_market_provider(provider.id):
        return
    if inst is None:
        raise ProviderError(
            provider.id,
            "BAD_INPUT",
            f"provider {provider.id!r} requires a registered instrument, got {symbol!r}",
        )
    if provider.id not in inst.providers:
        raise ProviderError(
            provider.id,
            "BAD_INPUT",
            f"provider {provider.id!r} does not support instrument {inst.symbol!r} "
            f"({inst.asset_class}, quote={inst.quote_currency}); supported: "
            f"{', '.join(inst.providers)}",
        )
    if interval not in provider.intervals:
        raise ProviderError(
            provider.id,
            "BAD_INPUT",
            f"provider {provider.id!r} does not support interval {interval!r} "
            f"(supported: {provider.intervals})",
        )
    capabilities = provider.capabilities
    if capabilities.asset_classes and inst.asset_class not in capabilities.asset_classes:
        raise ProviderError(
            provider.id,
            "BAD_INPUT",
            f"provider {provider.id!r} does not serve asset class {inst.asset_class!r}",
        )
    market_type = str(inst.metadata.get("market_type", "spot"))
    if market_type not in provider.market_types:
        raise ProviderError(
            provider.id,
            "BAD_INPUT",
            f"provider {provider.id!r} does not serve market type {market_type!r} "
            f"for {inst.symbol!r}",
        )


def _providers_compatible(primary_id: str, alt_id: str, symbol: str, interval: str) -> bool:
    """True when ``alt_id`` may substitute for ``primary_id`` without changing
    the economic meaning of the dataset.

    Requirements enforced here:
      - both providers must be registered and support the exact instrument
      - identical asset class (equity/crypto/fx/macro) and market type
      - identical quote currency (guaranteed by the instrument provider list)
      - identical timeframe
      - identical price-adjustment semantics (adjusted vs unadjusted vs unknown)
      - real market data only falls back to real market data; local/synthetic/
        upload datasets never substitute for production data (and vice versa)
      - no cross-provider FX substitution: FX feeds differ in price basis
        (bid vs mid) and volume semantics (traded volume vs quote counts), so
        a fallback would silently change the dataset's economic meaning
    """
    from ..instruments import get_instrument

    if primary_id == alt_id:
        return False
    inst = get_instrument(symbol)
    if inst is None:
        return False
    if primary_id not in inst.providers or alt_id not in inst.providers:
        return False

    primary_cls = _ALL.get(primary_id)
    alt_cls = _ALL.get(alt_id)
    if primary_cls is None or alt_cls is None:
        return False
    primary = primary_cls()
    alt = alt_cls()

    # Real vs non-real data must never be mixed in either direction.
    if _is_real_market_provider(primary_id) != _is_real_market_provider(alt_id):
        return False
    if not _is_real_market_provider(alt_id):
        return False

    # FX feeds are not semantically interchangeable: Polygon forex bars are
    # built from bid quotes (volume repeats the quote count), while other
    # vendors publish mid/tick-derived series. Until price basis and volume
    # semantics are modelled per provider, never substitute FX data.
    if inst.asset_class == "fx":
        return False

    if inst.asset_class not in primary.capabilities.asset_classes:
        return False
    if inst.asset_class not in alt.capabilities.asset_classes:
        return False
    if interval not in primary.intervals or interval not in alt.intervals:
        return False

    # Adjusted vs unadjusted vs unknown must match exactly for equities.
    # Spot crypto has no corporate split/dividend actions, so crypto spot prices
    # are intrinsically unadjusted raw trades across all vendors.
    if inst.asset_class != "crypto" and primary.adjusted != alt.adjusted:
        return False

    market_type = str(inst.metadata.get("market_type", "spot"))
    return market_type in primary.market_types and market_type in alt.market_types


def _coverage_compatible(start: str, end: str, interval: str, frame: Any) -> bool:
    """Require a fallback frame to cover the requested window (bounded slack).

    A fallback that silently returns a materially shorter history would change
    the backtest's information set even when the instrument/semantics match.
    """
    is_intraday = interval in ("1m", "5m", "15m", "30m", "1H", "4H")
    min_bars = 1 if is_intraday else 10
    try:
        if frame is None or len(frame) < min_bars:
            return False
    except Exception:  # noqa: BLE001
        return False
    if is_intraday:
        return True
    if not start or not end:
        return True
    try:
        requested_start = dt.date.fromisoformat(str(start)[:10])
        requested_end = dt.date.fromisoformat(str(end)[:10])
        first = frame.index[0].date()
        last = frame.index[-1].date()
    except Exception:  # noqa: BLE001
        # Non-ISO/unparseable request: the provider already validated it.
        return True
    # Weekend/holiday slack for daily data; wider for weekly/monthly bars.
    slack_days = {"1D": 31, "1W": 62, "1M": 93}.get(interval, 31)
    return bool(
        first <= requested_start + dt.timedelta(days=slack_days)
        and last >= requested_end - dt.timedelta(days=slack_days)
    )


def _original_message(provider_id: str, error: ProviderError) -> str:
    prefix = f"data provider '{provider_id}': "
    text = str(error)
    return text[len(prefix) :] if text.startswith(prefix) else text


def _cooldown_error(provider: DataProvider) -> ProviderError | None:
    status = cooldown_status(provider.id)
    if not status["active"]:
        return None
    reason = status["reason"] or "upstream block"
    return ProviderError(
        provider.id,
        ERR_PROVIDER_COOLDOWN,
        f"provider {provider.id!r} cooling down for {status['retryAfter']}s after {reason}",
        retry_after=float(status["retryAfter"]),
        details={"provider": provider.id},
    )


def fetch_bars(
    requested: str | None,
    symbol: str,
    start: str,
    end: str,
    interval: str = "1D",
    user_id: str | None = None,
    allow_fallback: bool | None = None,
) -> tuple[DataProvider, BarsResult]:
    """Resolve + fetch with cache/retry/rate-limit/cooldown.

    Errors always name the provider; there is no fallback to synthetic.
    Only transient failures may fall back, and only to a provider that is
    provably compatible with the exact instrument, timeframe and data
    semantics. The original failure reason is preserved.

    ``user_id`` scopes per-user providers to the authenticated tenant.
    """
    from ..instruments import normalize_symbol
    from .routing import get_asset_routing_candidates, resolve_provider_for_instrument

    use_fallback = FALLBACK_ENABLED if allow_fallback is None else allow_fallback
    symbol = normalize_symbol(symbol)

    if requested is None or requested == "":
        provider = resolve_provider_for_instrument(symbol, requested=None, interval=interval, user_id=user_id)
    else:
        provider = resolve_for_request(requested, user_id=user_id)
    primary_id = provider.id
    _validate_provider_for_instrument(provider, symbol, interval)

    try:
        cooling = _cooldown_error(provider)
        if cooling is not None:
            raise cooling
        result = provider.fetch_ohlcv_cached(symbol, start, end, interval)
        return provider, result
    except ProviderError as e:
        record_failure(primary_id, e.code, provider.cooldown_s)
        if e.code in _NON_RETRYABLE_CODES or not use_fallback:
            raise

        routing_pref = get_asset_routing_candidates(symbol, interval)
        compatible_set = {
            pid
            for pid in enabled_ids()
            if pid != primary_id and _providers_compatible(primary_id, pid, symbol, interval)
        }
        # Order alternatives by asset routing preferences first, then any other enabled compatibles
        alternatives = [pid for pid in routing_pref if pid in compatible_set] + [
            pid for pid in enabled_ids() if pid in compatible_set and pid not in routing_pref
        ]
        if not alternatives:
            raise

        original = _original_message(primary_id, e)
        attempted: list[str] = []
        for alt_id in alternatives:
            attempted.append(alt_id)
            alt_provider: DataProvider | None = None
            try:
                alt_provider = get_provider(alt_id, user_id=user_id)
                cooling = _cooldown_error(alt_provider)
                if cooling is not None:
                    raise cooling
                result = alt_provider.fetch_ohlcv_cached(symbol, start, end, interval)
                if not _coverage_compatible(start, end, interval, result.frame):
                    log.warning(
                        "fallback rejected: incompatible historical coverage",
                        extra={"primary": primary_id, "alternative": alt_id, "symbol": symbol},
                    )
                    continue
                prov = dict(result.provenance)
                prov.update(
                    {
                        "fallback": True,
                        "fallback_from": primary_id,
                        "requested_provider": primary_id,
                        "fallback_reason": f"{primary_id}: {e.code}: {original}",
                        "provider": alt_id,
                    }
                )
                result.provenance = prov
                log.info(
                    "provider fallback used",
                    extra={"primary": primary_id, "alternative": alt_id, "symbol": symbol},
                )
                return alt_provider, result
            except ProviderError as ae:
                if alt_provider is not None:
                    record_failure(alt_id, ae.code, alt_provider.cooldown_s)
                log.warning(
                    "fallback provider failed",
                    extra={
                        "primary": primary_id,
                        "alternative": alt_id,
                        "code": ae.code,
                    },
                )
                continue

        # Preserve the primary failure as the raised error, with the fallback
        # attempt trail appended for operators.
        trail = ", ".join(attempted) or "none"
        raise ProviderError(
            primary_id,
            e.code,
            f"{original} (fallback attempted: {trail}; no compatible provider succeeded)",
        ) from e
