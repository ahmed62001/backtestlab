"""Backward-compatible facade over app/data_providers (Phase 2 refactor).

The provider layer now lives in backend/app/data_providers/ (interface,
registry, cache/retry/rate-limit, one module per optional provider). This
module keeps the old import surface working: BarsResult, DataProvider,
LocalCsvProvider (fixture files), quality_guards, get_provider.
"""

from __future__ import annotations

import pandas as pd

from .data_providers import BarsResult, DataProvider
from .data_providers.local_fixtures import LocalFixturesProvider
from .data_providers.registry import get_provider as _registry_get


class LocalCsvProvider(LocalFixturesProvider):
    """Legacy name for the fixture provider (license_class=dev_only)."""

    def fetch(self, symbol: str, start: str = "", end: str = "") -> BarsResult:
        res = self.fetch_ohlcv_cached(symbol, start, end)
        prov = dict(res.provenance)
        prov.setdefault("adjustments", "split_div_adjusted_unknown")
        return BarsResult(frame=res.frame, provenance=prov, warnings=res.warnings)


def quality_guards(df: pd.DataFrame) -> list[dict[str, str]]:
    w: list[dict[str, str]] = []
    if df.isna().values.any():
        w.append({"code": "DATA_GAPS"})
    if not df.index.is_monotonic_increasing:
        w.append({"code": "DATA_GAPS"})
    if len(df) < 60:
        w.append({"code": "SHORT_HISTORY"})
    if (df.get("volume", pd.Series([1])).fillna(1) == 0).any():
        w.append({"code": "DATA_GAPS"})
    return w


def get_provider(name: str = "local") -> DataProvider:
    """Legacy accessor. 'local' returns the fixture provider with the old
    `.fetch(symbol, start, end)` method; other ids go through the registry."""
    if name == "local":
        return LocalCsvProvider()
    return _registry_get(name)
