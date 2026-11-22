"""Tests for Section 4 Data Quality and Reliability Validation (all 12 criteria)."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from app.data_providers.validation import validate_ohlcv_data, ValidationReport


def _make_valid_df(periods=20, freq="D") -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(periods)],
            "high": [105.0 + i for i in range(periods)],
            "low": [95.0 + i for i in range(periods)],
            "close": [102.0 + i for i in range(periods)],
            "volume": [1000.0 + i * 10 for i in range(periods)],
        },
        index=dates,
    )


def test_rule1_empty_data_rejection():
    # Empty DataFrame
    df = pd.DataFrame()
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("empty" in e.lower() for e in report.anomalies)
    assert report.checked_rules["non_empty"] is False


def test_rule3_missing_ohlcv_columns():
    df = _make_valid_df().drop(columns=["close"])
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("missing" in e.lower() for e in report.anomalies)
    assert report.checked_rules["ohlcv_structure"] is False


def test_rule4_non_positive_prices():
    df = _make_valid_df()
    df.loc[df.index[2], "close"] = -5.0  # negative price
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("non_positive" in e.lower() or "non-positive" in e.lower() for e in report.anomalies)
    assert report.checked_rules["positive_prices"] is False

    df2 = _make_valid_df()
    df2.loc[df2.index[2], "open"] = 0.0  # zero price
    report2 = validate_ohlcv_data(df2, "AAPL", "yfinance", "equity", "1D")
    assert report2.is_valid is False
    assert report2.checked_rules["positive_prices"] is False


def test_rule5_candle_envelope_violation():
    # High < Open
    df = _make_valid_df()
    df.loc[df.index[3], "high"] = df.loc[df.index[3], "open"] - 1.0
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("envelope" in e.lower() for e in report.anomalies)
    assert report.checked_rules["valid_envelope"] is False

    # Low > Close
    df2 = _make_valid_df()
    df2.loc[df2.index[3], "low"] = df2.loc[df2.index[3], "close"] + 1.0
    report2 = validate_ohlcv_data(df2, "AAPL", "yfinance", "equity", "1D")
    assert report2.is_valid is False
    assert report2.checked_rules["valid_envelope"] is False


def test_rule6_monotonic_timestamp_ordering():
    df = _make_valid_df()
    # Scramble dates
    reversed_idx = df.index[::-1]
    df.index = reversed_idx
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("unsorted" in e.lower() or "monotonic" in e.lower() for e in report.anomalies)
    assert report.checked_rules["chronological_order"] is False


def test_rule7_duplicate_timestamps():
    df = _make_valid_df()
    # Duplicate first timestamp
    df = pd.concat([df.iloc[[0]], df])
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("duplicate" in e.lower() for e in report.anomalies)
    assert report.checked_rules["no_duplicates"] is False


def test_rule8_timezone_handling():
    # Naive timestamp (no tz)
    dates_naive = pd.date_range("2024-01-01", periods=20, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "close": [102.0] * 20,
            "volume": [1000.0] * 20,
        },
        index=dates_naive,
    )
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is False
    assert any("timezone" in e.lower() or "utc" in e.lower() for e in report.anomalies)
    assert report.checked_rules["utc_index"] is False


def test_rule11_gap_detection_vs_market_schedule():
    # 24/7 Crypto market with a 5-day unexpected gap
    crypto_dates = list(pd.date_range("2024-01-01", "2024-01-05", freq="D", tz="UTC")) + list(
        pd.date_range("2024-01-12", "2024-01-17", freq="D", tz="UTC")
    )
    df_crypto = pd.DataFrame(
        {
            "open": [40000.0] * len(crypto_dates),
            "high": [41000.0] * len(crypto_dates),
            "low": [39000.0] * len(crypto_dates),
            "close": [40500.0] * len(crypto_dates),
            "volume": [500.0] * len(crypto_dates),
        },
        index=crypto_dates,
    )
    report_crypto = validate_ohlcv_data(df_crypto, "BTC-USD", "twelvedata", "crypto", "1D")
    assert any("gap" in w.lower() for w in report_crypto.warnings)


def test_valid_dataset_all_criteria_met():
    df = _make_valid_df(periods=50)
    report = validate_ohlcv_data(df, "AAPL", "yfinance", "equity", "1D")
    assert report.is_valid is True
    assert len(report.anomalies) == 0
    assert report.bar_count == 50
    assert report.checked_rules["non_empty"] is True
    assert report.checked_rules["ohlcv_structure"] is True
    assert report.checked_rules["utc_index"] is True
    assert report.checked_rules["chronological_order"] is True
    assert report.checked_rules["no_duplicates"] is True
    assert report.checked_rules["no_nan"] is True
    assert report.checked_rules["positive_prices"] is True
    assert report.checked_rules["valid_envelope"] is True
    assert report.checked_rules["valid_volume"] is True
