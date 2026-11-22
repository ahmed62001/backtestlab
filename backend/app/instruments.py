"""Instrument metadata and asset-class eligibility registry.

Defines the universe of tradable instruments that BacktestLab can backtest.
Each instrument carries:
  - canonical symbol (used with providers and stored in results)
  - display symbol (shown in the UI)
  - asset class: equity / crypto / fx / macro_reference
  - base currency / quote currency
  - applicable providers (provider ids that can serve this instrument)
  - supported timeframes
  - backtest_eligible: True when a genuine OHLCV source exists for backtesting

A symbol is tradable only if it is registered here AND an enabled, available
provider supports its asset class and the requested timeframe. This replaces
the old hardcoded equity allowlist with capability-based validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Instrument:
    symbol: str  # canonical symbol, e.g. "AAPL", "BTC-USD", "EURUSD"
    display: str  # UI-friendly label
    asset_class: str  # "equity" | "crypto" | "fx" | "fx_reference" | "macro_reference"
    base_currency: str | None
    quote_currency: str | None
    providers: tuple[str, ...]  # provider ids that can serve this instrument
    timeframes: tuple[str, ...]  # supported timeframes
    backtest_eligible: bool  # True when genuine OHLCV data exists for backtesting
    metadata: dict[str, Any]  # exchange, sector, etc.


# ---------------------------------------------------------------------------
# Tradable instrument universe
# ---------------------------------------------------------------------------

_ALL_TF = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M")

# Equities (existing, preserved)
_EQUITIES = (
    Instrument(
        symbol="AAPL",
        display="Apple Inc.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Technology"},
    ),
    Instrument(
        symbol="MSFT",
        display="Microsoft Corp.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Technology"},
    ),
    Instrument(
        symbol="NVDA",
        display="NVIDIA Corp.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Technology"},
    ),
    Instrument(
        symbol="TSLA",
        display="Tesla Inc.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Consumer Cyclical"},
    ),
    Instrument(
        symbol="AMD",
        display="Advanced Micro Devices",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Technology"},
    ),
    Instrument(
        symbol="SPY",
        display="SPDR S&P 500 ETF Trust",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NYSE Arca", "sector": "ETF"},
    ),
    Instrument(
        symbol="GOOGL",
        display="Alphabet Inc.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Technology"},
    ),
    Instrument(
        symbol="AMZN",
        display="Amazon.com Inc.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Consumer Cyclical"},
    ),
    Instrument(
        symbol="META",
        display="Meta Platforms Inc.",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon", "twelvedata"),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "sector": "Communication Services"},
    ),
    Instrument(
        symbol="2222.SR",
        display="Saudi Aramco",
        asset_class="equity",
        base_currency=None,
        quote_currency="SAR",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "Tadawul", "sector": "Energy", "halal_screened": True},
    ),
    Instrument(
        symbol="1120.SR",
        display="Al Rajhi Bank",
        asset_class="equity",
        base_currency=None,
        quote_currency="SAR",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "Tadawul", "sector": "Financial Services", "halal_screened": True},
    ),
)

# Cryptocurrency spot (Twelve Data primary when configured, with Binance public / CCXT fallback)
_CRYPTO = (
    Instrument(
        symbol="BTC-USD",
        display="Bitcoin / US Dollar",
        asset_class="crypto",
        base_currency="BTC",
        quote_currency="USD",
        providers=("twelvedata", "binance_public", "ccxt", "polygon", "yfinance"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        backtest_eligible=True,
        metadata={"exchange": "Binance spot", "market_type": "spot", "stream_symbol": "BTC/USD"},
    ),
    Instrument(
        symbol="ETH-USD",
        display="Ethereum / US Dollar",
        asset_class="crypto",
        base_currency="ETH",
        quote_currency="USD",
        providers=("twelvedata", "binance_public", "ccxt", "polygon", "yfinance"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        backtest_eligible=True,
        metadata={"exchange": "Binance spot", "market_type": "spot", "stream_symbol": "ETH/USD"},
    ),
    Instrument(
        symbol="BTC-USDT",
        display="Bitcoin / Tether",
        asset_class="crypto",
        base_currency="BTC",
        quote_currency="USDT",
        providers=("twelvedata", "binance_public", "ccxt", "polygon"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        backtest_eligible=True,
        metadata={"exchange": "Binance spot", "market_type": "spot"},
    ),
    Instrument(
        symbol="ETH-USDT",
        display="Ethereum / Tether",
        asset_class="crypto",
        base_currency="ETH",
        quote_currency="USDT",
        providers=("twelvedata", "binance_public", "ccxt", "polygon"),
        timeframes=("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"),
        backtest_eligible=True,
        metadata={"exchange": "Binance spot", "market_type": "spot"},
    ),
)

# FX pairs - backtest-eligible only when a genuine OHLCV source is configured.
# Frankfurter supplies reference rates only (open==high==low==close, volume=0)
# and is NOT eligible for OHLCV backtesting. Twelve Data / Polygon require keys.
_FX = (
    Instrument(
        symbol="EURUSD",
        display="Euro / US Dollar",
        asset_class="fx",
        base_currency="EUR",
        quote_currency="USD",
        providers=("twelvedata", "polygon"),
        timeframes=_ALL_TF,
        backtest_eligible=False,  # no credential-free genuine OHLCV source
        metadata={"market": "FX spot", "note": "reference-only via Frankfurter", "stream_symbol": "EUR/USD"},
    ),
    Instrument(
        symbol="GBPUSD",
        display="British Pound / US Dollar",
        asset_class="fx",
        base_currency="GBP",
        quote_currency="USD",
        providers=("twelvedata", "polygon"),
        timeframes=_ALL_TF,
        backtest_eligible=False,
        metadata={"market": "FX spot", "note": "reference-only via Frankfurter", "stream_symbol": "GBP/USD"},
    ),
    Instrument(
        symbol="USDJPY",
        display="US Dollar / Japanese Yen",
        asset_class="fx",
        base_currency="USD",
        quote_currency="JPY",
        providers=("twelvedata", "polygon"),
        timeframes=_ALL_TF,
        backtest_eligible=False,
        metadata={"market": "FX spot", "note": "reference-only via Frankfurter", "stream_symbol": "USD/JPY"},
    ),
)

# Macro / reference series - NOT tradable, never backtest-eligible.
_MACRO_REFERENCE = (
    Instrument(
        symbol="FRED:GDP",
        display="Gross Domestic Product",
        asset_class="macro_reference",
        base_currency=None,
        quote_currency=None,
        providers=("fred",),
        timeframes=("1D", "1W", "1M"),
        backtest_eligible=False,
        metadata={"source": "FRED", "type": "macro_indicator"},
    ),
    Instrument(
        symbol="FRED:CPI",
        display="Consumer Price Index",
        asset_class="macro_reference",
        base_currency=None,
        quote_currency=None,
        providers=("fred",),
        timeframes=("1D", "1W", "1M"),
        backtest_eligible=False,
        metadata={"source": "FRED", "type": "macro_indicator"},
    ),
)

# Market indices (Yahoo ^-quoted symbols, yfinance only)
_INDICES = (
    Instrument(
        symbol="^GSPC",
        display="S&P 500",
        asset_class="index",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "CBOE"},
    ),
    Instrument(
        symbol="^IXIC",
        display="NASDAQ 100",
        asset_class="index",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ"},
    ),
    Instrument(
        symbol="^DJI",
        display="Dow Jones",
        asset_class="index",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NYSE"},
    ),
)

# Commodity futures (Yahoo =-quoted continuous futures, yfinance only)
_COMMODITIES = (
    Instrument(
        symbol="GC=F",
        display="Gold futures",
        asset_class="commodity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "CME", "market_type": "futures"},
    ),
    Instrument(
        symbol="SI=F",
        display="Silver futures",
        asset_class="commodity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "CME", "market_type": "futures"},
    ),
    Instrument(
        symbol="CL=F",
        display="Crude oil futures",
        asset_class="commodity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "CME", "market_type": "futures"},
    ),
)

# --- Expanded universe (2026-11-13): global equities, indices, commodities,
# FX and crypto. Canonical symbols follow the existing registry conventions
# (Yahoo/yfinance forms for keyless coverage; provider-specific slash forms
# only where the registry already uses them). `metadata["stream_symbol"]`,
# when present, is the symbol the streaming adapter subscribes to on
# Twelve Data (e.g. BTC-USD -> BTC/USD, EURUSD -> EUR/USD). Instruments whose
# only sources are keyed providers are backtest_eligible=False, mirroring the
# existing FX stance: reference/keyed display only, never OHLCV backtests.

_EQUITY_TF = _ALL_TF
_CRYPT_TF = _ALL_TF
_EQ_PROVIDERS = ("yfinance", "stooq", "alphavantage", "polygon", "twelvedata")
_CR_PROVIDERS = ("twelvedata", "binance_public", "ccxt", "polygon", "yfinance")


def _eq(symbol: str, display: str, exchange: str = "NASDAQ", sector: str = "Technology") -> Instrument:
    return Instrument(
        symbol=symbol,
        display=display,
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=_EQ_PROVIDERS,
        timeframes=_EQUITY_TF,
        backtest_eligible=True,
        metadata={"exchange": exchange, "sector": sector},
    )


_EXTRA_EQUITIES = (
    _eq("GOOG", "Alphabet Inc. Class C", "NASDAQ", "Technology"),
    _eq("AVGO", "Broadcom Inc.", "NASDAQ", "Technology"),
    _eq("LLY", "Eli Lilly and Company", "NYSE", "Healthcare"),
    _eq("WMT", "Walmart Inc.", "NYSE", "Consumer Defensive"),
    _eq("JPM", "JPMorgan Chase & Co.", "NYSE", "Financial Services"),
    _eq("V", "Visa Inc.", "NYSE", "Financial Services"),
    _eq("XOM", "Exxon Mobil Corp.", "NYSE", "Energy"),
    _eq("JNJ", "Johnson & Johnson", "NYSE", "Healthcare"),
    _eq("MA", "Mastercard Inc.", "NYSE", "Financial Services"),
    _eq("COST", "Costco Wholesale Corp.", "NASDAQ", "Consumer Defensive"),
    _eq("ORCL", "Oracle Corp.", "NYSE", "Technology"),
    _eq("PLTR", "Palantir Technologies", "NASDAQ", "Technology"),
    _eq("NFLX", "Netflix Inc.", "NASDAQ", "Communication Services"),
    _eq("CVX", "Chevron Corp.", "NYSE", "Energy"),
    _eq("PG", "Procter & Gamble Co.", "NYSE", "Consumer Defensive"),
    _eq("MU", "Micron Technology Inc.", "NASDAQ", "Technology"),
    _eq("INTC", "Intel Corp.", "NASDAQ", "Technology"),
    _eq("TSM", "Taiwan Semiconductor (ADR)", "NYSE", "Technology"),
    _eq("BABA", "Alibaba Group (ADR)", "NYSE", "Consumer Cyclical"),
    _eq("ASML", "ASML Holding (ADR)", "NASDAQ", "Technology"),
    _eq("SAP", "SAP SE (ADR)", "NYSE", "Technology"),
    _eq("TM", "Toyota Motor (ADR)", "NYSE", "Consumer Cyclical"),
    _eq("SHEL", "Shell plc (ADR)", "NYSE", "Energy"),
    _eq("NVO", "Novo Nordisk (ADR)", "NYSE", "Healthcare"),
    _eq("005930.KS", "Samsung Electronics", "KRX", "Technology"),
    _eq("0700.HK", "Tencent Holdings", "HKEX", "Technology"),
    Instrument(
        symbol="BRK-B",
        display="Berkshire Hathaway B",
        asset_class="equity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance", "stooq", "alphavantage", "polygon"),
        timeframes=_EQUITY_TF,
        backtest_eligible=True,
        metadata={"exchange": "NYSE", "sector": "Financial Services", "stream_symbol": "BRK.B"},
    ),
)

_EXTRA_INDICES = (
    Instrument(
        symbol="^NDX",
        display="NASDAQ 100",
        asset_class="index",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NASDAQ", "stream_symbol": "NDX"},
    ),
    Instrument(
        symbol="^RUT",
        display="Russell 2000",
        asset_class="index",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "NYSE", "stream_symbol": "RUT"},
    ),
    Instrument(
        symbol="^FTSE",
        display="FTSE 100",
        asset_class="index",
        base_currency=None,
        quote_currency="GBP",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "LSE", "stream_symbol": "FTSE"},
    ),
    Instrument(
        symbol="^GDAXI",
        display="DAX 40",
        asset_class="index",
        base_currency=None,
        quote_currency="EUR",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "XETRA", "stream_symbol": "GDAXI"},
    ),
    Instrument(
        symbol="^N225",
        display="Nikkei 225",
        asset_class="index",
        base_currency=None,
        quote_currency="JPY",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "TSE", "stream_symbol": "N225"},
    ),
    Instrument(
        symbol="^HSI",
        display="Hang Seng",
        asset_class="index",
        base_currency=None,
        quote_currency="HKD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "HKEX", "stream_symbol": "HSI"},
    ),
    Instrument(
        symbol="^TASI",
        display="Tadawul All Share Index",
        asset_class="index",
        base_currency=None,
        quote_currency="SAR",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": "Tadawul", "stream_symbol": "TASI"},
    ),
)


def _future(symbol: str, display: str, exchange: str = "CME") -> Instrument:
    return Instrument(
        symbol=symbol,
        display=display,
        asset_class="commodity",
        base_currency=None,
        quote_currency="USD",
        providers=("yfinance",),
        timeframes=_ALL_TF,
        backtest_eligible=True,
        metadata={"exchange": exchange, "market_type": "futures"},
    )


_EXTRA_COMMODITIES = (
    _future("BZ=F", "Brent Crude Oil futures", "ICE"),
    _future("NG=F", "Natural Gas futures"),
    _future("RB=F", "RBOB Gasoline futures"),
    _future("HO=F", "Heating Oil futures"),
    _future("HG=F", "Copper Futures contract", "COMEX"),
    _future("ZC=F", "Corn Futures contract", "CBOT"),
    _future("ZW=F", "Wheat Futures contract", "CBOT"),
    _future("ZS=F", "Soybean Futures contract", "CBOT"),
    _future("KC=F", "Coffee Futures contract", "ICE"),
    _future("SB=F", "Sugar Futures contract", "ICE"),
    _future("CC=F", "Cocoa Futures contract", "ICE"),
    _future("PL=F", "Platinum futures", "NYMEX"),
    _future("PA=F", "Palladium futures", "NYMEX"),
)


def _spot_metal(symbol: str, display: str) -> Instrument:
    # Spot metals trade in the keyed providers' FX-style feeds (Twelve Data,
    # Polygon). No credential-free genuine OHLCV source, so these mirror the
    # FX stance: streamable/displayable when credentialed, never backtested.
    return Instrument(
        symbol=symbol,
        display=display,
        asset_class="commodity",
        base_currency=symbol.split("/")[0],
        quote_currency="USD",
        providers=("twelvedata", "polygon"),
        timeframes=_ALL_TF,
        backtest_eligible=False,
        metadata={"exchange": "FOREX", "market_type": "spot", "stream_symbol": symbol},
    )


_SPOT_METALS_PRIMARY = (
    _spot_metal("XAU/USD", "Gold Spot"),
    _spot_metal("XAG/USD", "Silver Spot"),
)

_SPOT_METALS_EXTENDED = (
    _spot_metal("XPT/USD", "Platinum Spot"),
    _spot_metal("XPD/USD", "Palladium Spot"),
)

_SPOT_METALS = (*_SPOT_METALS_PRIMARY, *_SPOT_METALS_EXTENDED)


def _fx(symbol: str, display: str) -> Instrument:
    base = symbol[:3]
    quote = symbol[3:6]
    return Instrument(
        symbol=symbol,
        display=display,
        asset_class="fx",
        base_currency=base,
        quote_currency=quote,
        providers=("twelvedata", "polygon"),
        timeframes=_ALL_TF,
        backtest_eligible=False,
        metadata={
            "market": "FX spot",
            "note": "reference-only via Frankfurter; live via keyed providers",
            "stream_symbol": f"{base}/{quote}",
        },
    )


_EXTRA_FX = (
    _fx("USDCHF", "US Dollar / Swiss Franc"),
    _fx("AUDUSD", "Australian Dollar / US Dollar"),
    _fx("USDCAD", "US Dollar / Canadian Dollar"),
    _fx("EURGBP", "Euro / British Pound"),
    _fx("NZDUSD", "New Zealand Dollar / US Dollar"),
    _fx("USDCNH", "US Dollar / Chinese Yuan (offshore)"),
    _fx("USDEGP", "US Dollar / Egyptian Pound"),
)


def _crypto_usd(symbol: str, display: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        display=display,
        asset_class="crypto",
        base_currency=symbol.split("-")[0],
        quote_currency="USD",
        providers=_CR_PROVIDERS,
        timeframes=_CRYPT_TF,
        backtest_eligible=True,
        metadata={"exchange": "Binance spot", "market_type": "spot", "stream_symbol": f"{symbol.split('-')[0]}/USD"},
    )


_EXTRA_CRYPTO = (
    _crypto_usd("BNB-USD", "Binance Coin / US Dollar"),
    _crypto_usd("SOL-USD", "Solana / US Dollar"),
    _crypto_usd("XRP-USD", "XRP / US Dollar"),
    _crypto_usd("ADA-USD", "Cardano / US Dollar"),
    _crypto_usd("DOGE-USD", "Dogecoin / US Dollar"),
    _crypto_usd("TRX-USD", "Tron / US Dollar"),
)


_ALL_INSTRUMENTS: dict[str, Instrument] = {}
for _inst in (
    *_EQUITIES,
    *_CRYPTO,
    *_FX,
    *_SPOT_METALS_PRIMARY,
    *_MACRO_REFERENCE,
    *_INDICES,
    *_COMMODITIES,
    *_EXTRA_EQUITIES,
    *_EXTRA_INDICES,
    *_EXTRA_COMMODITIES,
    *_SPOT_METALS_EXTENDED,
    *_EXTRA_FX,
    *_EXTRA_CRYPTO,
):
    _ALL_INSTRUMENTS[_inst.symbol] = _inst

# Common user-facing synonyms. Provider loaders accept the canonical dashed
# form (BTC-USDT), while users and CCXT documentation use BTC/USDT. Both must
# resolve to the same registry instrument so validation and provenance agree.
_SYMBOL_ALIASES = {
    "BTC/USD": "BTC-USD",
    "BRK.B": "BRK-B",
    "XAUUSD": "XAU/USD",
    "XAGUSD": "XAG/USD",
    "XPTUSD": "XPT/USD",
    "XPDUSD": "XPD/USD",
    "BTC/USDT": "BTC-USDT",
    "ETH/USD": "ETH-USD",
    "ETH/USDT": "ETH-USDT",
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USD/CHF": "USDCHF",
    "AUD/USD": "AUDUSD",
    "USD/CAD": "USDCAD",
    "EUR/GBP": "EURGBP",
    "NZD/USD": "NZDUSD",
    "USD/CNH": "USDCNH",
    "USD/EGP": "USDEGP",
    "^TASI.SR": "^TASI",
    "TASI.SR": "^TASI",
    "GC": "GC=F",
    "SI": "SI=F",
    "PL": "PL=F",
    "PA": "PA=F",
    "HG": "HG=F",
    "CL": "CL=F",
    "NG": "NG=F",
    "BZ": "BZ=F",
}

_NAME_KEYS = {
    "AAPL": "assets.aapl",
    "MSFT": "assets.msft",
    "NVDA": "assets.nvda",
    "TSLA": "assets.tsla",
    "AMD": "assets.amd",
    "SPY": "assets.spy",
    "2222.SR": "assets.saudiaramco",
    "1120.SR": "assets.alrajhi",
    "BTC-USD": "assets.btc",
    "ETH-USD": "assets.eth",
    "BTC-USDT": "assets.btc",
    "ETH-USDT": "assets.eth",
    "EURUSD": "assets.eurusd",
    "GBPUSD": "assets.gbpusd",
    "USDJPY": "assets.usdjpy",
}


def normalize_symbol(symbol: str) -> str:
    """Return the canonical registry symbol for ``symbol``.

    Aliases such as ``BTC/USDT`` become ``BTC-USDT``. Unknown symbols are
    returned upper-cased without inventing a registry entry.
    """
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    if raw in _ALL_INSTRUMENTS:
        return raw
    if raw in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[raw]
    if "/" in raw:
        base, quote = raw.split("/", 1)
        for candidate in (f"{base}-{quote}", f"{base}{quote}"):
            if candidate in _ALL_INSTRUMENTS:
                return candidate
    return raw


def get_instrument(symbol: str) -> Instrument | None:
    """Return the instrument for ``symbol``, or None if unknown."""
    return _ALL_INSTRUMENTS.get(normalize_symbol(symbol))


def list_instruments(asset_class: str | None = None) -> list[Instrument]:
    """List all instruments, optionally filtered by asset class."""
    insts = list(_ALL_INSTRUMENTS.values())
    if asset_class:
        insts = [i for i in insts if i.asset_class == asset_class]
    return insts


def tradable_symbols() -> list[str]:
    """Symbols that are registered instruments (regardless of eligibility)."""
    return sorted(_ALL_INSTRUMENTS.keys())


def eligible_providers(symbol: str, timeframe: str = "1D") -> list[str]:
    """Provider ids that can serve ``symbol`` at ``timeframe``.

    A provider is eligible only if it is in the instrument's provider list,
    supports the instrument's asset class, and lists the timeframe.
    """
    inst = get_instrument(symbol)
    if inst is None:
        return []
    from .data_providers.registry import _ALL  # lazy import to avoid cycles

    out: list[str] = []
    for pid in inst.providers:
        cls = _ALL.get(pid)
        if cls is None:
            continue
        p = cls()
        if timeframe not in p.intervals:
            continue
        classes = p.capabilities.asset_classes
        if classes and inst.asset_class not in classes:
            continue
        out.append(pid)
    return out


_PLACEHOLDER_KEYS = {
    "",
    "your_twelvedata_api_key",
    "your_massive_api_key",
    "your_polygon_api_key",
    "your-alphavantage-api-key",
    "your_fred_api_key",
    "demo",
    "changeme",
}


def _provider_configured(pid: str) -> bool:
    """True when a provider is enabled AND has its package/key configured.

    This is a configuration probe only: it never performs network I/O, so the
    asset catalog stays network-independent while accurately hiding providers
    (and derived FX eligibility) that cannot possibly work.
    """
    import importlib.util

    from .data_providers.base import resolve_env_key
    from .data_providers.registry import _ALL, enabled_ids

    if pid not in enabled_ids():
        return False
    cls = _ALL.get(pid)
    if cls is None:
        return False
    p = cls()
    caps = p.capabilities
    if caps.requires_package and importlib.util.find_spec(caps.requires_package) is None:
        return False
    if p.requires_key:
        env_var = caps.requires_key_env or ""
        if not resolve_env_key(env_var, caps.requires_key_env_legacy, _PLACEHOLDER_KEYS):
            return False
    return True


def configured_providers(symbol: str, timeframe: str = "1D") -> list[str]:
    """Eligible provider ids that are actually enabled and configured."""
    return [pid for pid in eligible_providers(symbol, timeframe) if _provider_configured(pid)]


def is_backtest_eligible(symbol: str) -> bool:
    """True when the instrument has a genuine, configured OHLCV source.

    Equity/crypto instruments carry a static eligibility flag. FX is only
    eligible when a real OHLCV provider (not ECB reference rates) is enabled
    and credentialed in the current deployment.
    """
    inst = get_instrument(symbol)
    if inst is None:
        return False
    # FX and spot metals have no credential-free genuine OHLCV source: they
    # become tradable only when a configured real provider (Twelve Data / Polygon)
    # is enabled and credentialed in the current deployment.
    if inst.asset_class == "fx" or (inst.asset_class == "commodity" and inst.metadata.get("market_type") == "spot"):
        return bool(configured_providers(inst.symbol, "1D"))
    return inst.backtest_eligible


def backtest_eligible_symbols() -> list[str]:
    """Symbols whose genuine OHLCV source exists in this deployment."""
    return sorted(s for s in _ALL_INSTRUMENTS if is_backtest_eligible(s))


def asset_class_for(symbol: str) -> str | None:
    inst = get_instrument(symbol)
    return inst.asset_class if inst else None


def asset_catalog() -> list[dict[str, Any]]:
    """Frontend instrument catalog derived from the authoritative registry.

    Only instruments the backend can genuinely backtest right now are listed.
    Macro/reference series are never exposed as tradable; FX appears only when
    a real OHLCV provider is enabled and configured. The response shape keeps
    the historical frontend fields and adds capability metadata additively.
    """
    items: list[dict[str, Any]] = []
    for inst in _ALL_INSTRUMENTS.values():
        if inst.asset_class == "macro_reference":
            continue
        if not is_backtest_eligible(inst.symbol):
            continue
        if inst.asset_class == "crypto":
            market = "Crypto"
        elif inst.asset_class == "fx":
            market = "FX spot"
        else:
            market = str(inst.metadata.get("exchange") or inst.asset_class.title())
        items.append(
            {
                "ticker": inst.symbol,
                "nameKey": _NAME_KEYS.get(inst.symbol, "assets.other"),
                "market": market,
                "halalScreened": bool(inst.metadata.get("halal_screened", False)),
                "assetClass": inst.asset_class,
                "providers": list(configured_providers(inst.symbol, "1D")),
                "timeframes": list(inst.timeframes),
            }
        )
    return items
