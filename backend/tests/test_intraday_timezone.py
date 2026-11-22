"""Phase 3 — intraday timestamps must be true UTC instants.

Root cause: the vendor yfinance loader strips the exchange timezone from
intraday frames, so 09:30 New York was labelled 09:30 UTC (a 4–5 hour error)
and freshness/session math was computed against the wrong instant.
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_providers.vendor_shim import localize_intraday_index  # noqa: E402


def frame(*stamps: str) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(list(stamps)))
    return pd.DataFrame(
        {
            "open": [1.0] * len(idx),
            "high": [1.0] * len(idx),
            "low": [1.0] * len(idx),
            "close": [1.0] * len(idx),
            "volume": [1.0] * len(idx),
        },
        index=idx,
    )


def test_new_york_summer_time_is_converted_to_utc():
    out = localize_intraday_index(
        frame("2026-09-18 09:30"), asset_class="equity", exchange="NASDAQ", interval="1H"
    )
    assert str(out.index[0]) == "2026-09-18 13:30:00+00:00"


def test_new_york_winter_time_is_converted_to_utc():
    out = localize_intraday_index(
        frame("2026-12-18 09:30"), asset_class="equity", exchange="NASDAQ", interval="1H"
    )
    assert str(out.index[0]) == "2026-12-18 14:30:00+00:00"


def test_daily_bars_are_left_as_date_only():
    src = frame("2026-11-16")
    out = localize_intraday_index(
        src, asset_class="equity", exchange="NASDAQ", interval="1D"
    )
    assert out.index.equals(src.index)
    assert out.index.tz is None


def test_already_aware_frames_are_untouched():
    idx = pd.DatetimeIndex(pd.to_datetime(["2026-09-18 13:30:00+00:00"]))
    src = pd.DataFrame({"close": [1.0]}, index=idx)
    out = localize_intraday_index(
        src, asset_class="equity", exchange="NASDAQ", interval="1H"
    )
    assert out.index.equals(src.index)


def test_crypto_intraday_is_utc():
    out = localize_intraday_index(
        frame("2026-09-18 09:00"), asset_class="crypto", exchange="Binance spot", interval="1H"
    )
    assert str(out.index[0]) == "2026-09-18 09:00:00+00:00"


def test_futures_use_new_york_time():
    out = localize_intraday_index(
        frame("2026-09-18 18:00"), asset_class="commodity", exchange="CME", interval="1H"
    )
    assert str(out.index[0]) == "2026-09-18 22:00:00+00:00"


def test_ambiguous_dst_hour_is_dropped_not_guessed():
    # 2026-11-01 01:30 occurs twice in New York; guessing would fabricate a bar.
    src = frame("2026-11-01 01:30", "2026-11-01 03:30")
    out = localize_intraday_index(
        src, asset_class="equity", exchange="NASDAQ", interval="1H"
    )
    assert len(out) == 1
    assert str(out.index[0]) == "2026-11-01 08:30:00+00:00"  # 03:30 EST
