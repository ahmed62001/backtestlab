"""Template for a new BacktestLab data provider.

Copy this file to ``backend/app/data_providers/<id>.py``, rename the class,
fill in the metadata and implement ``fetch_ohlcv_raw``. Then register the class
in ``backend/app/data_providers/registry.py`` and follow the 10-step guide in
``docs/DATA_PROVIDERS.md``.

Rules:
- Return a pandas DataFrame with open/high/low/close(/volume) columns and a
  DatetimeIndex. The shared base class normalizes timezone, sorting, dtypes,
  duplicates and the MAX_BARS cap.
- Translate every failure with ``classify_error`` or an explicit
  ``ProviderError``. Never return synthetic data and never fall back to another
  provider.
- ``health_check`` must be cheap, must not leak credentials, and must report
  missing optional packages/keys as ``available=False`` with a reason.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from app.data_providers.base import (
    Capabilities,
    Category,
    DataProvider,
    ProviderError,
    classify_error,
    get_httpx_client,
)

_BASE_URL = "https://api.example.com/v1"
_KEY_ENV = "EXAMPLE_API_KEY"
_INTERVALS = ("1D",)


class ExampleProvider(DataProvider):
    id = "example"
    name_en = "Example (keyed)"
    name_ar = "مثال (يتطلب مفتاح)"
    markets = ("us_equity",)
    intervals = _INTERVALS
    requires_key = True
    license_class = "commercial_ok"  # replace with the real license class
    adjusted = False
    min_interval_s = 1.0

    capabilities = Capabilities(
        category=Category.EQUITIES,
        asset_classes=("equity",),
        timeframes=_INTERVALS,
        supports_adjusted=False,
        requires_package=None,
        requires_key_env=_KEY_ENV,
        rate_limit_per_minute=60,
        description_en="Example provider (replace me)",
        description_ar="مزود بيانات مثال (استبدلني)",
    )

    def _key(self) -> str:
        value = os.environ.get(_KEY_ENV, "").strip()
        return "" if value.lower() in {"", "demo", "changeme"} else value

    def health_check(self) -> dict[str, Any]:
        if not self._key():
            return {"available": False, "detail": f"{_KEY_ENV} not configured"}
        try:
            client = get_httpx_client(self.id, timeout=10.0)
            response = client.get(f"{_BASE_URL}/ping")
            if response.status_code == 200:
                return {"available": True, "detail": ""}
            return {"available": False, "detail": f"HTTP {response.status_code}"}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "detail": str(exc)}

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        if interval not in self.intervals:
            raise ProviderError(
                self.id, "BAD_INPUT", f"interval {interval!r} unsupported (supported: {self.intervals})"
            )
        key = self._key()
        if not key:
            raise ProviderError(
                self.id, "PROVIDER_NOT_CONFIGURED", f"{_KEY_ENV} is not configured"
            )

        client = get_httpx_client(self.id, timeout=30.0)
        params = {"symbol": symbol, "start": start, "end": end, "apikey": key}
        try:
            response = client.get(f"{_BASE_URL}/bars", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise classify_error(self.id, exc) from exc
        except httpx.RequestError as exc:
            raise classify_error(self.id, exc) from exc

        rows = payload.get("bars", [])
        if not rows:
            raise ProviderError(
                self.id, "UNKNOWN_SYMBOL", f"no bars for {symbol!r} in {start}..{end}"
            )

        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp").sort_index()
        return frame[["open", "high", "low", "close", "volume"]].astype(float)
