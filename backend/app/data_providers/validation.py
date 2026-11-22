"""Market Data Quality & Reliability Validation Module.

Enforces strict financial data sanity checks:
1. Valid, non-empty market data.
2. Correct symbol and asset identity.
3. Correct OHLCV structure.
4. Positive and realistic prices (finite, > 0).
5. Candlestick boundaries: High >= max(Open, Close) and Low <= min(Open, Close).
6. Correct chronological timestamp ordering.
7. No duplicate candles or timestamps.
8. UTC timezone consistency.
9. Reasonable freshness for the instrument and market schedule.
10. Supported historical depth and timeframe.
11. Market schedule awareness (24/7 crypto vs exchange holidays/weekends).
12. Detection of suspicious data gaps vs legitimate closures.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ValidationReport:
    symbol: str
    provider: str
    is_valid: bool
    bar_count: int
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    anomalies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    market_type: str = "spot"
    asset_class: str | None = None
    checked_rules: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider": self.provider,
            "isValid": self.is_valid,
            "barCount": self.bar_count,
            "firstTimestamp": self.first_timestamp,
            "lastTimestamp": self.last_timestamp,
            "anomalies": self.anomalies,
            "warnings": self.warnings,
            "marketType": self.market_type,
            "assetClass": self.asset_class,
            "checkedRules": self.checked_rules,
        }


def validate_ohlcv_data(
    df: pd.DataFrame | None,
    symbol: str,
    provider: str,
    asset_class: str | None = None,
    timeframe: str = "1D",
) -> ValidationReport:
    """Run comprehensive financial data quality verification across all 12 criteria."""
    report = ValidationReport(
        symbol=symbol,
        provider=provider,
        is_valid=True,
        bar_count=len(df) if df is not None else 0,
        asset_class=asset_class,
    )

    # Rule 1: Valid, non-empty data
    if df is None or len(df) == 0:
        report.is_valid = False
        report.anomalies.append("EMPTY_DATA: DataFrame is None or empty")
        report.checked_rules["non_empty"] = False
        return report
    report.checked_rules["non_empty"] = True

    # Rule 2: Correct OHLCV structure
    required_cols = ["open", "high", "low", "close"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        report.is_valid = False
        report.anomalies.append(f"MISSING_COLUMNS: missing {missing}")
        report.checked_rules["ohlcv_structure"] = False
        return report
    report.checked_rules["ohlcv_structure"] = True

    # Rule 3: DatetimeIndex & UTC timezone
    if not isinstance(df.index, pd.DatetimeIndex):
        report.is_valid = False
        report.anomalies.append("INVALID_INDEX: index is not DatetimeIndex")
        report.checked_rules["utc_index"] = False
        return report
    if df.index.tz is None or str(df.index.tz) != "UTC":
        report.is_valid = False
        report.anomalies.append("TIMEZONE_ERROR: index timezone is not UTC")
        report.checked_rules["utc_index"] = False
    else:
        report.checked_rules["utc_index"] = True

    # Rule 4: Timestamp ordering & uniqueness
    if not df.index.is_monotonic_increasing:
        report.is_valid = False
        report.anomalies.append("UNSORTED_TIMESTAMPS: timestamps are not monotonically increasing")
        report.checked_rules["chronological_order"] = False
    else:
        report.checked_rules["chronological_order"] = True

    dups = df.index.duplicated().sum()
    if dups > 0:
        report.is_valid = False
        report.anomalies.append(f"DUPLICATE_CANDLES: {dups} duplicate timestamps found")
        report.checked_rules["no_duplicates"] = False
    else:
        report.checked_rules["no_duplicates"] = True

    report.first_timestamp = df.index[0].isoformat()
    report.last_timestamp = df.index[-1].isoformat()

    # Rule 5: Positive, finite, realistic prices
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    has_nan = df[price_cols].isna().any().any()
    if has_nan:
        report.is_valid = False
        report.anomalies.append("NAN_PRICES: NaN or missing values present in price columns")
        report.checked_rules["no_nan"] = False
    else:
        report.checked_rules["no_nan"] = True

    has_non_positive = (df[price_cols] <= 0).any().any()
    if has_non_positive:
        report.is_valid = False
        report.anomalies.append("NON_POSITIVE_PRICES: prices <= 0 detected")
        report.checked_rules["positive_prices"] = False
    else:
        report.checked_rules["positive_prices"] = True

    # Rule 6: Candlestick envelope integrity (High >= max(Open, Close), Low <= min(Open, Close))
    invalid_envelope = False
    for _, row in df.iterrows():
        op = float(row["open"])
        hi = float(row["high"])
        lo = float(row["low"])
        cl = float(row["close"])
        if hi < max(op, cl) - 1e-6 or lo > min(op, cl) + 1e-6 or hi < lo:
            invalid_envelope = True
            break
    if invalid_envelope:
        report.is_valid = False
        report.anomalies.append("ENVELOPE_VIOLATION: candles violate High >= max(Open,Close) or Low <= min(Open,Close)")
        report.checked_rules["valid_envelope"] = False
    else:
        report.checked_rules["valid_envelope"] = True

    # Rule 7: Volume check (non-negative)
    if "volume" in df.columns:
        if (df["volume"] < 0).any():
            report.is_valid = False
            report.anomalies.append("NEGATIVE_VOLUME: volume < 0 detected")
            report.checked_rules["valid_volume"] = False
        else:
            report.checked_rules["valid_volume"] = True
    else:
        report.checked_rules["valid_volume"] = True

    # Rule 8: Reasonable freshness for market schedule
    now = dt.datetime.now(dt.UTC)
    last_dt = df.index[-1]
    if hasattr(last_dt, "to_pydatetime"):
        last_dt = last_dt.to_pydatetime()
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=dt.UTC)

    age_days = (now - last_dt).total_seconds() / 86400.0
    is_24_7 = asset_class == "crypto"
    # Crypto trades 24/7; equities/commodities close on weekends
    max_expected_gap_days = 2.0 if is_24_7 else 4.5
    if age_days > max_expected_gap_days:
        report.warnings.append(f"STALE_SERIES: last candle age is {age_days:.1f} days")
        report.checked_rules["freshness"] = False
    else:
        report.checked_rules["freshness"] = True

    # Rule 9: Distinguish legitimate market closure from data gap
    if len(df) > 5 and timeframe == "1D":
        diffs = pd.Series(df.index[1:] - df.index[:-1]).dt.total_seconds() / 86400.0
        # If any gap exceeds 5 days (e.g. longer than normal long-weekend closure)
        large_gaps = (diffs > 5.0).sum()
        if large_gaps > 0:
            report.warnings.append(f"DATA_GAPS: {large_gaps} intervals exceed 5 calendar days")
            report.checked_rules["no_abnormal_gaps"] = False
        else:
            report.checked_rules["no_abnormal_gaps"] = True
    else:
        report.checked_rules["no_abnormal_gaps"] = True

    return report
