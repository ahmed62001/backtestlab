"""Canonical symbol <-> provider-specific symbol mapping.

Table-driven from backend/data/symbol_map.yaml plus hard-coded rules.
Supports round-trip lookup for common instruments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

MAP_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_map.yaml"

# Hard-coded fallback mappings (canonical -> {provider: provider_symbol})
_DEFAULT_MAP: dict[str, dict[str, str]] = {
    "BTC-USD": {
        "ccxt": "BTC/USDT",
        "binance": "BTCUSDT",
        "coingecko": "bitcoin",
        "yfinance": "BTC-USD",
    },
    "ETH-USD": {
        "ccxt": "ETH/USDT",
        "binance": "ETHUSDT",
        "coingecko": "ethereum",
        "yfinance": "ETH-USD",
    },
    "AAPL": {"yfinance": "AAPL", "stooq": "AAPL.US"},
    "EURUSD": {"yfinance": "EURUSD=X", "frankfurter": "EUR"},
    "GBPUSD": {"yfinance": "GBPUSD=X", "frankfurter": "GBP"},
}

# Reverse index: provider_symbol -> canonical
_REVERSE: dict[str, dict[str, str]] = {}


def _load_map() -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = dict(_DEFAULT_MAP)
    if MAP_PATH.exists():
        with open(MAP_PATH) as f:
            file_map = yaml.safe_load(f) or {}
        for canon, providers in file_map.items():
            data.setdefault(canon, {}).update(providers)
    return data


def _build_reverse() -> None:
    global _REVERSE
    _REVERSE = {}
    for canon, providers in _load_map().items():
        for prov, sym in providers.items():
            _REVERSE.setdefault(prov, {})[sym] = canon


_build_reverse()


def canonical_to_provider(canonical: str, provider: str) -> str | None:
    """Map a canonical symbol to a provider-specific symbol."""
    return _load_map().get(canonical, {}).get(provider)


def provider_to_canonical(provider: str, provider_symbol: str) -> str | None:
    """Map a provider-specific symbol back to canonical."""
    return _REVERSE.get(provider, {}).get(provider_symbol)


def list_providers_for(canonical: str) -> list[str]:
    """List providers that have a mapping for this canonical symbol."""
    return list(_load_map().get(canonical, {}).keys())


def is_known(canonical: str) -> bool:
    return canonical in _load_map()


# ---- Universe YAML (data/universe.yaml or data/universe/<name>.yaml) --------

UNIVERSE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "universe"
UNIVERSE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "universe.yaml"


def load_universe(name: str | None = None) -> dict[str, Any]:
    """Load a symbol universe.

    ``name=None`` loads ``data/universe.yaml``. Otherwise ``name`` may be an
    explicit path or a short name resolved inside ``data/universe/`` (the
    ``.yaml`` suffix is optional), e.g. ``load_universe("crypto_majors")``.

    Returns a dict with a 'symbols' key whose value is a list of
    {canonical, providers: {provider: provider_symbol}} entries.
    Returns {'symbols': []} if the file is missing or empty.
    """
    path = UNIVERSE_PATH
    if name:
        candidate = Path(name)
        if candidate.is_file():
            path = candidate
        else:
            if not candidate.suffix:
                candidate = candidate.with_suffix(".yaml")
            path = candidate if candidate.is_file() else UNIVERSE_DIR / candidate.name
    if not path.exists():
        return {"symbols": []}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {"symbols": []}
    if not isinstance(data, dict):
        return {"symbols": []}
    syms = data.get("symbols")
    if not isinstance(syms, list):
        return {"symbols": []}
    return {"symbols": syms}
