"""Reuse Vibe-Trading's own data loaders through a thin adapter.

Vibe-Trading ships ready-made loaders under agent/backtest/loaders/
(yfinance_loader, ccxt_loader, stooq_loader, alphavantage_loader, ...). Per the
Phase-2 decision we REUSE them through this adapter instead of re-implementing
the vendor APIs. Two shims make them usable in our tree:

1. sys.path: the vendor loaders live under vendor/Vibe-Trading/agent.
2. src.config.accessor: several vendor loaders lazily import the vendor repo's
   own config object (env accessors). That package is NOT importable from our
   layout, so we register a minimal stand-in backed by real env vars — only
   when the real module is unavailable. We never edit vendor/.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .base import (
    ERR_BAD_INPUT,
    ERR_UNKNOWN_SYMBOL,
    ERR_UPSTREAM_BAD_RESPONSE,
    ERR_UPSTREAM_BLOCKED,
    DataProvider,
    ProviderError,
    classify_error,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_DIR = REPO_ROOT / "vendor" / "Vibe-Trading" / "agent"

_PLACEHOLDER_KEYS = {"", "your-alphavantage-api-key", "demo"}

# Intraday vendor frames are exchange-local wall clock with the timezone
# stripped by the vendor loader. Map the exchange to the zone needed to restore
# a true UTC instant. (Phase 3 root cause: a 09:30 New York bar was labelled
# 09:30 UTC, a 4–5 hour lie.)
_EXCHANGE_TZ = {
    "NASDAQ": "America/New_York",
    "NYSE": "America/New_York",
    "NYSE ARCA": "America/New_York",
    "AMEX": "America/New_York",
    "CBOE": "America/New_York",
    "CME": "America/New_York",
    "COMEX": "America/New_York",
    "NYMEX": "America/New_York",
    "CBOT": "America/New_York",
    "ICE": "America/New_York",
    "TADAWUL": "Asia/Riyadh",
    "LSE": "Europe/London",
    "XETRA": "Europe/Berlin",
    "TSE": "Asia/Tokyo",
    "HKEX": "Asia/Hong_Kong",
    "KRX": "Asia/Seoul",
    "FOREX": "UTC",
}


def _zone_for(asset_class: str | None, exchange: str | None) -> ZoneInfo | None:
    if asset_class == "crypto":
        return ZoneInfo("UTC")  # Yahoo crypto intraday is UTC
    if exchange:
        ex_key = exchange.upper()
        if ex_key in _EXCHANGE_TZ:
            return ZoneInfo(_EXCHANGE_TZ[ex_key])
    if asset_class in ("equity", "etf", "index", "commodity"):
        return ZoneInfo("America/New_York")
    if asset_class == "fx":
        return ZoneInfo("Europe/London")
    return None


def localize_intraday_index(
    frame: pd.DataFrame,
    *,
    asset_class: str | None,
    exchange: str | None,
    interval: str,
) -> pd.DataFrame:
    """Restore the exchange timezone on a naive intraday index, then use UTC.

    Daily/weekly/monthly bars are date-only and stay naive (normalized to UTC
    midnight by the caller), which is how daily charts key them. Only intraday
    bars need the wall-clock -> real-instant conversion.
    """
    if interval not in ("1m", "5m", "15m", "30m", "1H", "4H"):
        return frame
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        return frame
    zone = _zone_for(asset_class, exchange)
    if zone is None:
        return frame
    idx = frame.index.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
    mask = ~idx.isna()
    if not mask.any():
        return frame
    out = frame.loc[mask].copy()
    out.index = idx[mask].tz_convert("UTC")
    return out



def env_key_configured(env_var: str | None) -> bool:
    """True when a required key env var is present and not a placeholder."""
    if not env_var:
        return True
    value = os.environ.get(env_var, "").strip()
    return bool(value) and value.lower() not in _PLACEHOLDER_KEYS


def ensure_vendor_path() -> None:
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))


def ensure_config_shim() -> None:
    """Register a minimal `src.config.accessor.get_env_config()` stand-in so
    vendor loaders can read env config (ccxt exchange id, API keys)."""
    try:
        import src.config.accessor  # noqa: F401

        return
    except Exception:  # noqa: BLE001, S110
        pass

    class _Data:
        def __init__(self) -> None:
            self.ccxt_exchange = os.environ.get("CCXT_EXCHANGE", "binance")
            self.alphavantage_api_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")

    class _Cfg:
        def __init__(self) -> None:
            self.data = _Data()

    acc = types.ModuleType("src.config.accessor")
    acc.get_env_config = lambda: _Cfg()  # type: ignore[attr-defined]
    cfg = types.ModuleType("src.config")
    cfg.accessor = acc  # type: ignore[attr-defined]
    src_mod = sys.modules.get("src")
    if src_mod is None:
        src_mod = types.ModuleType("src")
        sys.modules["src"] = src_mod
    sys.modules["src.config"] = cfg
    sys.modules["src.config.accessor"] = acc


class VendorLoaderProvider(DataProvider):
    """Adapter over a vendor DataLoader (fetch(codes, start, end, interval=)
    -> {symbol: DataFrame} with a trade_date DatetimeIndex)."""

    vendor_module: str = ""  # e.g. "backtest.loaders.stooq_loader"
    vendor_loader_attr = "DataLoader"
    no_data_code: str = ERR_UNKNOWN_SYMBOL  # override for stooq challenge
    # The vendor loader strips the exchange timezone from intraday frames
    # (yfinance does); set True only for providers where that is verified.
    localize_intraday: bool = False

    def _loader(self) -> Any:
        ensure_vendor_path()
        ensure_config_shim()
        try:
            mod = __import__(self.vendor_module, fromlist=[self.vendor_loader_attr])
            return getattr(mod, self.vendor_loader_attr)()
        except Exception as e:
            raise ProviderError(
                self.id, "PROVIDER_DOWN", f"vendor loader {self.vendor_module} unavailable: {e}"
            ) from e

    def health_check(self) -> dict[str, Any]:
        key_env = self.capabilities.requires_key_env
        if self.requires_key and not env_key_configured(key_env):
            return {"available": False, "detail": f"{key_env} not configured"}
        package = self.capabilities.requires_package
        if package and importlib.util.find_spec(package) is None:
            return {"available": False, "detail": f"package {package} not installed"}
        try:
            loader = self._loader()
            ok = bool(loader.is_available())
            return {"available": ok, "detail": "" if ok else "dependency/key missing"}
        except ProviderError as e:
            return {"available": False, "detail": str(e)}

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        key_env = self.capabilities.requires_key_env
        if self.requires_key and not env_key_configured(key_env):
            # A missing key is a configuration error, not a bad symbol (D-PH2-02).
            raise ProviderError(self.id, "PROVIDER_NOT_CONFIGURED", f"{key_env} not configured")
        loader = self._loader()
        try:
            out = loader.fetch(
                [symbol], start or "1990-01-01", end or "2100-01-01", interval=interval
            )
        except ValueError as e:
            raise ProviderError(self.id, ERR_BAD_INPUT, str(e)) from e
        except ProviderError:
            raise
        except Exception as e:
            raise classify_error(self.id, e) from e
        frame = self._extract_frame(out, symbol, start, end)
        if not self.localize_intraday:
            return frame
        # Restore the true UTC instant for intraday bars (vendor strips the tz).
        try:
            from ..instruments import get_instrument

            inst = get_instrument(symbol)
            asset_class = inst.asset_class if inst else None
            exchange = str(inst.metadata.get("exchange")) if inst and inst.metadata.get("exchange") else None
        except Exception:  # noqa: BLE001
            asset_class, exchange = None, None
        return localize_intraday_index(
            frame, asset_class=asset_class, exchange=exchange, interval=interval
        )

    def _extract_frame(self, out: Any, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Pull the frame for `symbol` from a vendor loader response, mapping
        missing/HTML bodies to the right typed code (never a bare
        UNKNOWN_SYMBOL for an anti-bot challenge)."""
        frame = (out or {}).get(symbol) if isinstance(out, dict) else None
        if isinstance(frame, str):
            # A non-DataFrame body (HTML challenge / plain-text refusal) is an
            # upstream block, not "no such symbol".
            text = frame.lstrip().lower()
            if text.startswith("<") or "challenge" in text or "proof of work" in text:
                raise ProviderError(
                    self.id, ERR_UPSTREAM_BLOCKED, "upstream returned an anti-bot/challenge page"
                )
            raise ProviderError(
                self.id,
                ERR_UPSTREAM_BAD_RESPONSE,
                f"upstream returned a non-CSV body for {symbol!r}",
            )
        if frame is None or len(frame) == 0:
            # Distinguish a genuine "no such symbol" from an upstream that
            # refused (latched challenge) -> the latter must not masquerade as
            # a bad ticker. Subclasses may override via `no_data_code`.
            raise ProviderError(
                self.id, self.no_data_code, f"no bars for {symbol!r} in {start}..{end}"
            )
        return frame
