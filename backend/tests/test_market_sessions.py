"""Phase 3 — session-aware freshness rules, tested with an injectable clock.

No host clock, no sleeps: every case passes ``now`` explicitly.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.market_sessions import (  # noqa: E402
    EquitySession,
    FuturesSession,
    freshness_metadata,
    session_for,
)

UTC = dt.UTC


def at(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=UTC)


def meta(asset_class, symbol, interval, candles, now, provider="yfinance", **kw):
    return freshness_metadata(
        provider=provider,
        interval=interval,
        asset_class=asset_class,
        symbol=symbol,
        candle_timestamps=list(candles),
        now=now,
        fetched_at=kw.pop("fetched_at", now - dt.timedelta(minutes=5)),
        served_from_cache=kw.pop("served_from_cache", False),
        cache_age_s=kw.pop("cache_age_s", 0),
    )


def test_market_open_fresh_intraday():
    # Monday 2026-11-16 16:00 UTC = 11:00 ET, session open.
    now = at(2026, 11, 16, 16, 0)
    candles = [at(2026, 11, 16, 14, 30), at(2026, 11, 16, 15, 30), at(2026, 11, 16, 16, 0)]
    m = meta("equity", "AAPL", "1H", candles, now)
    assert m["session"] == "us_equity"
    assert m["session_open"] is True
    assert m["is_stale"] is False
    # yfinance is a delayed provider by design.
    assert m["data_status"] == "delayed"
    assert m["last_candle_timestamp"] == at(2026, 11, 16, 16, 0).isoformat()
    # The in-progress 16:00 candle must not be reported as completed.
    assert m["last_completed_candle_timestamp"] == at(2026, 11, 16, 14, 30).isoformat()


def test_market_open_stale_when_a_completed_candle_is_missing():
    now = at(2026, 11, 16, 16, 0)  # Monday 11:00 ET
    # Last data is Friday's final hour: Monday morning candles are missing.
    candles = [at(2026, 11, 13, 20, 0)]
    m = meta("equity", "AAPL", "1H", candles, now)
    assert m["session_open"] is True
    assert m["is_stale"] is True
    assert m["data_status"] == "stale"


def test_weekend_is_not_stale_and_not_a_failure():
    now = at(2026, 11, 14, 15, 0)  # Saturday
    candles = [at(2026, 11, 13, 20, 0)]  # Friday's last completed hour
    m = meta("equity", "AAPL", "1H", candles, now)
    assert m["session_open"] is False
    assert m["is_stale"] is False


def test_holiday_is_not_stale():
    now = at(2026, 11, 26, 16, 0)  # Thanksgiving Thursday, 11:00 ET
    candles = [at(2026, 11, 25, 20, 0)]  # Wednesday close
    m = meta("equity", "AAPL", "1D", candles, now)
    assert m["session_open"] is False
    assert m["is_stale"] is False
    assert m["expected_completed_open"].startswith("2026-11-25")


def test_early_close_uses_13_00_et():
    # 2026-11-27 is an early close: 13:00 ET = 18:00 UTC.
    session = EquitySession()
    assert session.is_open(at(2026, 11, 27, 17, 30)) is True  # 12:30 ET, before the early close
    assert session.is_open(at(2026, 11, 27, 18, 30)) is False  # 13:30 ET, closed
    now = at(2026, 11, 28, 0, 0)  # 19:00 ET Friday, well after the 13:00 ET early close
    candles = [at(2026, 11, 27, 0, 0), at(2026, 11, 25, 0, 0)]
    m = meta("equity", "AAPL", "1D", candles, now)
    assert m["session_open"] is False
    assert m["expected_completed_open"].startswith("2026-11-27")


def test_provider_delay_inside_allowance_is_fresh():
    # Monday 15:00 UTC (10:00 ET); the daily bar for Friday is the last one due.
    now = at(2026, 11, 16, 15, 0)
    candles = [at(2026, 11, 13, 0, 0)]
    m = meta("equity", "AAPL", "1D", candles, now)
    assert m["is_stale"] is False


def test_cache_age_is_reported_without_changing_status():
    now = at(2026, 11, 16, 16, 0)
    candles = [at(2026, 11, 16, 16, 0)]
    m = meta(
        "equity",
        "AAPL",
        "1H",
        candles,
        now,
        served_from_cache=True,
        cache_age_s=90_000,  # 25 hours, beyond the 24-hour data-cache TTL
    )
    assert m["served_from_cache"] is True
    assert m["cache_age_seconds"] == 90_000
    assert m["is_stale"] is False  # cached data is not automatically stale
    assert m["data_status"] == "delayed"


def test_btc_around_day_boundary():
    now = at(2026, 11, 17, 0, 10)  # 10 minutes after the UTC day rolled over
    candles = [at(2026, 11, 16, 0, 0), at(2026, 11, 17, 0, 0)]
    m = meta("crypto", "BTC-USD", "1D", candles, now)
    assert m["session"] == "crypto_24_7"
    assert m["session_open"] is True
    assert m["last_completed_candle_timestamp"] == at(2026, 11, 16, 0, 0).isoformat()
    assert m["is_stale"] is False


def test_gc_f_daily_break_uses_futures_calendar():
    now = at(2026, 11, 16, 22, 30)  # Monday 17:30 ET, inside the daily break
    candles = [at(2026, 11, 16, 0, 0)]
    m = meta("commodity", "GC=F", "1D", candles, now)
    assert m["session"] == "cme_futures"
    assert m["session_open"] is False
    # Monday's settlement (17:00 ET) completed, so data is current.
    assert m["last_completed_candle_timestamp"] == at(2026, 11, 16, 0, 0).isoformat()
    assert m["is_stale"] is False


def test_futures_are_not_judged_with_the_equity_calendar():
    friday_evening_utc = at(2026, 11, 14, 2, 0)  # Friday 21:00 ET
    assert session_for("commodity", "GC=F").is_open(friday_evening_utc) is False
    assert session_for("crypto", "BTC-USD").is_open(friday_evening_utc) is True
    assert FuturesSession().is_open(at(2026, 11, 16, 22, 30)) is False  # break
    assert EquitySession().is_open(at(2026, 11, 16, 22, 30)) is False  # after close


def test_equity_daily_weekend_missing_friday_is_stale():
    now = at(2026, 11, 16, 16, 0)  # Monday 11:00 ET
    candles = [at(2026, 11, 12, 0, 0)]  # Thursday only; Friday is missing
    m = meta("equity", "AAPL", "1D", candles, now)
    assert m["is_stale"] is True


def test_empty_series_is_unavailable():
    m = meta("equity", "AAPL", "1D", [], at(2026, 11, 16, 16, 0))
    assert m["data_status"] == "unavailable"
    assert m["last_candle_timestamp"] is None
