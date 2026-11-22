"""FRED provider — direct HTTP implementation.

US economic data from Federal Reserve Economic Data (FRED) API.
Requires FRED_API_KEY environment variable.
Provides macro series (GDP, CPI, unemployment, etc.) as pseudo-OHLCV.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

import httpx
import pandas as pd

from .base import (
    ERR_INVALID_KEY,
    ERR_NOT_CONFIGURED,
    ERR_UNKNOWN_SYMBOL,
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    classify_error,
    get_httpx_client,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_META_URL = "https://api.stlouisfed.org/fred/series"
_DEFAULT_MIN_INTERVAL = 0.5

# Common FRED series mapping
_FRED_SERIES = {
    "GDP": "GDP",
    "CPI": "CPIAUCSL",
    "CPIAUCSL": "CPIAUCSL",
    "UNEMPLOYMENT": "UNRATE",
    "UNRATE": "UNRATE",
    "FEDFUNDS": "FEDFUNDS",
    "TREASURY_10Y": "DGS10",
    "DGS10": "DGS10",
    "TREASURY_2Y": "DGS2",
    "DGS2": "DGS2",
    "VIX": "VIXCLS",
    "DXY": "DTWEXBGS",
    "RETAIL_SALES": "RSXFS",
    "INDUSTRIAL_PROD": "INDPRO",
    "M2SL": "M2SL",
}

# Placeholder keys that don't count as configured
_KEY_PLACEHOLDERS = {"", "your_fred_api_key", "demo", "changeme"}


class FredProvider(DataProvider):
    id = "fred"
    name_en = "FRED (US macro data)"
    name_ar = "FRED (بيانات اقتصادية أمريكية)"
    markets = ("macro",)
    intervals = ("1D", "1W", "1M")
    license_class = "public_free"
    adjusted = False
    requires_key = True
    min_interval_s = _DEFAULT_MIN_INTERVAL
    capabilities = Capabilities(
        category=Category.MACRO,
        asset_classes=("macro",),
        timeframes=("1D", "1W", "1M"),
        supports_adjusted=False,
        requires_package=None,
        requires_key_env="FRED_API_KEY",
        rate_limit_per_minute=120,
        description_en="Federal Reserve Economic Data (FRED) US macro series",
        description_ar="بيانات اقتصادية كلية أمريكية من الاحتياطي الفيدرالي (FRED)",
    )

    def _resolve_key(self) -> str:
        key = os.environ.get("FRED_API_KEY", "").strip()
        if key.lower() in _KEY_PLACEHOLDERS:
            return ""
        return key

    def _fred_series_id(self, symbol: str) -> str | None:
        upper = symbol.upper().strip()
        if upper in _FRED_SERIES:
            return _FRED_SERIES[upper]
        # Allow direct FRED series IDs
        if upper.startswith("FRED:") or upper.isalnum():
            return upper.replace("FRED:", "")
        return None

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        api_key = self._resolve_key()
        if not api_key:
            raise ProviderError(
                self.id, ERR_NOT_CONFIGURED, f"FRED_API_KEY not configured (required for {self.id})"
            )

        series_id = self._fred_series_id(symbol)
        if series_id is None:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"unknown FRED series: {symbol!r}")

        client = get_httpx_client(self.id, timeout=30.0)

        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": end,
            "sort_order": "asc",
        }

        try:
            resp = client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise classify_error(self.id, e) from e
        except httpx.RequestError as e:
            raise classify_error(self.id, e) from e

        observations = data.get("observations", [])
        if not observations:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"no data for FRED series {series_id}")

        rows = []
        for obs in observations:
            if obs.get("value") == "." or obs.get("value") is None:
                continue
            try:
                val = float(obs["value"])
                rows.append(
                    {
                        "timestamp": pd.Timestamp(obs["date"], tz="UTC"),
                        "open": val,
                        "high": val,
                        "low": val,
                        "close": val,
                        "volume": 0.0,
                    }
                )
            except (ValueError, KeyError):
                continue

        if not rows:
            raise ProviderError(
                self.id, ERR_UNKNOWN_SYMBOL, f"no valid observations for {series_id}"
            )

        df = pd.DataFrame(rows).set_index("timestamp")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    def fetch_macro_observations(
        self,
        symbol: str,
        start: str = "",
        end: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Dedicated macroeconomic observations interface (not pseudo-OHLCV).

        Preserves observation frequency, units, series metadata, and missing
        observations (`.` in FRED -> None, never fabricated).
        """
        api_key = self._resolve_key()
        if not api_key:
            raise ProviderError(
                self.id, ERR_NOT_CONFIGURED, f"FRED_API_KEY not configured (required for {self.id})"
            )

        series_id = self._fred_series_id(symbol)
        if series_id is None:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"unknown FRED series: {symbol!r}")

        client = get_httpx_client(self.id, timeout=30.0)
        obs_params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": max(1, min(int(limit), 2000)),
        }
        if start:
            obs_params["observation_start"] = start
        if end:
            obs_params["observation_end"] = end

        try:
            obs_resp = client.get(_BASE_URL, params=obs_params)
            if obs_resp.status_code == 400:
                body = obs_resp.text.lower()
                if "api_key" in body:
                    raise ProviderError(self.id, ERR_INVALID_KEY, "invalid FRED API key")
                if "series" in body and "not exist" in body:
                    raise ProviderError(
                        self.id, ERR_UNKNOWN_SYMBOL, f"unknown FRED series: {series_id}"
                    )
            obs_resp.raise_for_status()
            obs_data = obs_resp.json()
        except ProviderError:
            raise
        except httpx.HTTPStatusError as e:
            raise classify_error(self.id, e) from e
        except httpx.RequestError as e:
            raise classify_error(self.id, e) from e

        meta: dict[str, Any] = {}
        try:
            meta_resp = client.get(
                _SERIES_META_URL,
                params={"series_id": series_id, "api_key": api_key, "file_type": "json"},
            )
            if meta_resp.status_code == 200:
                seriess = meta_resp.json().get("seriess") or []
                if seriess:
                    meta = seriess[0]
        except Exception:  # noqa: BLE001 - metadata enrichment is best-effort
            meta = {}

        raw_obs = obs_data.get("observations", [])
        if not raw_obs:
            raise ProviderError(self.id, ERR_UNKNOWN_SYMBOL, f"no data for FRED series {series_id}")

        observations: list[dict[str, Any]] = []
        valid_dates: list[str] = []
        for item in raw_obs:
            date_str = item.get("date")
            if not date_str:
                continue
            raw_val = item.get("value")
            if raw_val in (None, "."):
                observations.append({"date": str(date_str), "value": None, "missing": True})
            else:
                try:
                    val = float(raw_val)
                    observations.append({"date": str(date_str), "value": val, "missing": False})
                    valid_dates.append(str(date_str))
                except (TypeError, ValueError):
                    observations.append({"date": str(date_str), "value": None, "missing": True})

        now_iso = dt.datetime.now(dt.UTC).isoformat()
        return {
            "seriesId": series_id,
            "requestedSymbol": symbol,
            "title": meta.get("title") or series_id,
            "units": meta.get("units") or "",
            "unitsShort": meta.get("units_short") or "",
            "frequency": meta.get("frequency") or "",
            "frequencyShort": meta.get("frequency_short") or "",
            "seasonalAdjustment": meta.get("seasonal_adjustment") or "",
            "lastUpdated": meta.get("last_updated") or "",
            "source": "FRED",
            "dataType": "macroeconomic_observations",
            "backtestEligible": False,
            "observations": observations,
            "count": len(observations),
            "validCount": len(valid_dates),
            "firstDate": valid_dates[0] if valid_dates else None,
            "lastDate": valid_dates[-1] if valid_dates else None,
            "provenance": {
                "provider": self.id,
                "requested_provider": self.id,
                "series_id": series_id,
                "asset_class": "macro_reference",
                "data_type": "macroeconomic_observations",
                "frequency": meta.get("frequency_short") or None,
                "units": meta.get("units") or None,
                "start": valid_dates[0] if valid_dates else None,
                "end": valid_dates[-1] if valid_dates else None,
                "retrieved_at": now_iso,
                "fallback": False,
            },
        }

    def health_check(self) -> dict[str, Any]:
        api_key = self._resolve_key()
        if not api_key:
            return {"available": False, "detail": "FRED_API_KEY not configured"}
        try:
            client = get_httpx_client(self.id, timeout=10.0)
            resp = client.get(
                _BASE_URL,
                params={
                    "series_id": "GDP",
                    "api_key": api_key,
                    "file_type": "json",
                    "limit": 1,
                },
            )
            if resp.status_code == 200:
                return {"available": True, "detail": ""}
            return {"available": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "detail": str(e)}
