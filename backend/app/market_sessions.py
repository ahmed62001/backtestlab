"""Asset-aware market sessions and truthful data-freshness metadata.

The application serves three very different session types:

* equities / ETFs / indices — US regular session (09:30–16:00 America/New_York,
  weekday holidays, early closes),
* crypto — continuous 24/7 trading,
* futures (``GC=F``, ``CL=F`` …) — near-continuous CME trading with a daily
  break and a weekend closure. They must **not** be judged with an equity
  calendar.

The rule implemented here is deliberately narrow: data is only ``stale`` when a
newer *completed* candle should already exist, allowing for a documented
provider publication delay. A closed market is never treated as a failure.

Holiday coverage is an explicit static table (no heavy calendar dependency,
per the release rules). Unlisted one-off closures are a documented limitation.
"""

from __future__ import annotations

import datetime as dt

try:  # pragma: no cover - zoneinfo is available on every supported Python
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = dt.timezone(dt.timedelta(hours=-5))


# Full-day US equity closures. Source: NYSE published calendars.
US_HOLIDAYS: frozenset[dt.date] = frozenset(
    {
        # 2025
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 20),
        dt.date(2025, 2, 17),
        dt.date(2025, 4, 18),
        dt.date(2025, 5, 26),
        dt.date(2025, 6, 19),
        dt.date(2025, 7, 4),
        dt.date(2025, 9, 1),
        dt.date(2025, 11, 27),
        dt.date(2025, 12, 25),
        # 2026
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 19),
        dt.date(2026, 2, 16),
        dt.date(2026, 4, 3),
        dt.date(2026, 5, 25),
        dt.date(2026, 6, 19),
        dt.date(2026, 7, 3),
        dt.date(2026, 9, 7),
        dt.date(2026, 11, 26),
        dt.date(2026, 12, 25),
        # 2027
        dt.date(2027, 1, 1),
        dt.date(2027, 1, 18),
        dt.date(2027, 2, 15),
        dt.date(2027, 3, 26),
        dt.date(2027, 5, 31),
        dt.date(2027, 6, 18),
        dt.date(2027, 7, 5),
        dt.date(2027, 9, 6),
        dt.date(2027, 11, 25),
        dt.date(2027, 12, 24),
    }
)

# 13:00 ET early closes.
US_EARLY_CLOSES: frozenset[dt.date] = frozenset(
    {
        dt.date(2025, 7, 3),
        dt.date(2025, 11, 28),
        dt.date(2025, 12, 24),
        dt.date(2026, 11, 27),
        dt.date(2026, 12, 24),
        dt.date(2027, 11, 26),
    }
)

# Documented upstream publication delay allowance (seconds). A candle younger
# than this is not called stale even if a newer bucket exists.
PROVIDER_DELAY_S = {
    "yfinance": 6 * 3600,
    "stooq": 12 * 3600,
    "twelvedata": 5 * 60,
    "polygon": 5 * 60,
    "binance_public": 2 * 60,
    "frankfurter": 18 * 3600,
    "local": 0,
    "synthetic": 0,
}


def provider_delay_allowance(provider: str, interval: str) -> dt.timedelta:
    base = PROVIDER_DELAY_S.get(provider, 15 * 60)
    if interval in ("1m", "5m", "15m", "30m"):
        base = min(base, 30 * 60)
    elif interval in ("1H", "4H"):
        # Intraday bars must not wait a full day; allow at most two hours.
        base = min(base, 2 * 3600)
    elif interval in ("1W", "1M"):
        base = max(base, 24 * 3600)
    return dt.timedelta(seconds=base)


def interval_delta(interval: str) -> dt.timedelta:
    if interval.endswith("m") and interval[:-1].isdigit():
        return dt.timedelta(minutes=int(interval[:-1]))
    if interval.endswith("H") and interval[:-1].isdigit():
        return dt.timedelta(hours=int(interval[:-1]))
    if interval == "1W":
        return dt.timedelta(days=7)
    if interval == "1M":
        return dt.timedelta(days=30)
    return dt.timedelta(days=1)


def _et_close(date_: dt.date) -> dt.datetime:
    if date_ in US_EARLY_CLOSES:
        return dt.datetime.combine(date_, dt.time(13, 0), tzinfo=ET)
    return dt.datetime.combine(date_, dt.time(16, 0), tzinfo=ET)


def _et_open(date_: dt.date) -> dt.datetime:
    return dt.datetime.combine(date_, dt.time(9, 30), tzinfo=ET)


class Session:
    """A market session calendar. All inputs/outputs are timezone-aware UTC."""

    name = "generic"

    def is_open(self, now: dt.datetime) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def last_close(self, now: dt.datetime) -> dt.datetime | None:
        """Most recent session close at or before ``now``."""
        raise NotImplementedError

    def last_daily_bar_date(self, now: dt.datetime) -> dt.date | None:
        """Most recent trading date whose daily bar is complete at ``now``."""
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------
    def _covers(self, start: dt.datetime, end: dt.datetime) -> bool:
        """True when [start, end) is fully inside one continuous session."""
        if not self.is_open(start):
            return False
        probe = start
        step = dt.timedelta(minutes=15)
        while probe < end:
            probe = min(probe + step, end)
            if probe < end and not self.is_open(probe):
                return False
        return True


class EquitySession(Session):
    name = "us_equity"

    def is_open(self, now: dt.datetime) -> bool:
        local = now.astimezone(ET)
        if local.weekday() >= 5 or local.date() in US_HOLIDAYS:
            return False
        return _et_open(local.date()) <= local < _et_close(local.date())

    def last_close(self, now: dt.datetime) -> dt.datetime | None:
        local = now.astimezone(ET)
        for i in range(0, 14):
            d = local.date() - dt.timedelta(days=i)
            if d.weekday() >= 5 or d in US_HOLIDAYS:
                continue
            close = _et_close(d)
            if close <= local:
                return close.astimezone(dt.UTC)
        return None

    def last_daily_bar_date(self, now: dt.datetime) -> dt.date | None:
        close = self.last_close(now)
        return close.astimezone(ET).date() if close else None


class Cryptosession(Session):
    name = "crypto_24_7"

    def is_open(self, now: dt.datetime) -> bool:
        return True

    def last_close(self, now: dt.datetime) -> dt.datetime | None:
        return None

    def last_daily_bar_date(self, now: dt.datetime) -> dt.date | None:
        # Today's UTC daily bucket is still in progress.
        return now.astimezone(dt.UTC).date() - dt.timedelta(days=1)


class FuturesSession(Session):
    """CME-style near-continuous futures (Sun 18:00 ET – Fri 17:00 ET).

    A daily maintenance break runs 17:00–18:00 ET. The daily bar completes at
    the 17:00 ET settlement, not at an equity close.
    """

    name = "cme_futures"

    def is_open(self, now: dt.datetime) -> bool:
        local = now.astimezone(ET)
        wd = local.weekday()  # Mon=0 … Sun=6
        t = local.time()
        if wd == 5:  # Saturday
            return False
        if wd == 6:  # Sunday: opens 18:00
            return t >= dt.time(18, 0)
        if wd == 4:  # Friday: closes 17:00
            return t < dt.time(17, 0)
        return not (dt.time(17, 0) <= t < dt.time(18, 0))

    def last_close(self, now: dt.datetime) -> dt.datetime | None:
        local = now.astimezone(ET)
        for i in range(0, 10):
            d = local.date() - dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            settle = dt.datetime.combine(d, dt.time(17, 0), tzinfo=ET)
            if settle <= local:
                return settle.astimezone(dt.UTC)
        return None

    def last_daily_bar_date(self, now: dt.datetime) -> dt.date | None:
        close = self.last_close(now)
        return close.astimezone(ET).date() if close else None


class FxSession(Session):
    """Spot FX: Sunday 17:00 ET to Friday 17:00 ET, continuous."""

    name = "fx_24_5"

    def is_open(self, now: dt.datetime) -> bool:
        local = now.astimezone(ET)
        wd = local.weekday()
        t = local.time()
        if wd == 5:
            return False
        if wd == 6:
            return t >= dt.time(17, 0)
        if wd == 4:
            return t < dt.time(17, 0)
        return True

    def last_close(self, now: dt.datetime) -> dt.datetime | None:
        local = now.astimezone(ET)
        for i in range(0, 10):
            d = local.date() - dt.timedelta(days=i)
            if d.weekday() < 5:
                close = dt.datetime.combine(d, dt.time(17, 0), tzinfo=ET)
                if close <= local:
                    return close.astimezone(dt.UTC)
        return None

    def last_daily_bar_date(self, now: dt.datetime) -> dt.date | None:
        close = self.last_close(now)
        return close.astimezone(ET).date() if close else None


_EQUITY_CLASSES = {"equity", "etf", "index"}
_FUTURES_SYMBOLS = {"GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "KC=F", "CC=F"}

_DELAYED_PROVIDERS = frozenset({"yfinance", "stooq", "frankfurter"})


def session_for(asset_class: str | None, symbol: str = "") -> Session:
    if asset_class == "crypto":
        return Cryptosession()
    if asset_class == "commodity":
        return FuturesSession()
    if asset_class == "fx":
        return FxSession()
    if asset_class in _EQUITY_CLASSES:
        return EquitySession()
    if symbol in _FUTURES_SYMBOLS:
        return FuturesSession()
    return EquitySession()


def candle_completed(
    open_ts: dt.datetime, interval: str, now: dt.datetime, session: Session
) -> bool:
    """True when the candle window has fully completed."""
    if interval.endswith("m") or interval.endswith("H"):
        end = open_ts + interval_delta(interval)
        return end <= now and session._covers(open_ts, end)
    if interval in ("1D", "1W", "1M"):
        # Daily bars are stamped at 00:00 UTC of the trading date, regardless
        # of the exchange timezone.
        date_ = open_ts.astimezone(dt.UTC).date()
        if isinstance(session, Cryptosession):
            close = dt.datetime.combine(date_, dt.time(0, 0), tzinfo=dt.UTC) + dt.timedelta(days=1)
        elif isinstance(session, (FuturesSession, FxSession)):
            close = dt.datetime.combine(date_, dt.time(17, 0), tzinfo=ET)
        else:
            close = _et_close(date_)
        return close.astimezone(dt.UTC) <= now
    return False


def _expected_completed_open(
    session: Session, interval: str, now: dt.datetime, allowance: dt.timedelta
) -> dt.datetime | None:
    if interval.endswith("m") or interval.endswith("H"):
        if session.is_open(now):
            return now - interval_delta(interval) - allowance
        close = session.last_close(now)
        return close - interval_delta(interval) if close else None
    d = session.last_daily_bar_date(now - allowance)
    if d is None:
        return None
    return dt.datetime.combine(d, dt.time(0, 0), tzinfo=dt.UTC)


def freshness_metadata(
    *,
    provider: str,
    interval: str,
    asset_class: str | None,
    symbol: str,
    candle_timestamps: list[dt.datetime],
    now: dt.datetime,
    fetched_at: dt.datetime | None,
    served_from_cache: bool,
    cache_age_s: int,
) -> dict[str, object]:
    """Build the freshness contract (Phase 3) for a series response."""
    session = session_for(asset_class, symbol)
    candles = sorted(candle_timestamps)
    last_candle = candles[-1] if candles else None
    last_completed = None
    for ts in reversed(candles):
        if candle_completed(ts, interval, now, session):
            last_completed = ts
            break

    allowance = provider_delay_allowance(provider, interval)
    expected = _expected_completed_open(session, interval, now, allowance)

    if last_candle is None:
        stale = False
        status = "unavailable"
    elif interval in ("1D", "1W", "1M"):
        expected_date = expected.date() if expected is not None else None
        stale = bool(
            expected_date is not None
            and (last_completed is None or last_completed.date() < expected_date)
        )
        status = "stale" if stale else (
            "delayed" if provider in _DELAYED_PROVIDERS else "fresh"
        )
    else:
        if session.is_open(now):
            stale = expected is not None and last_candle < expected
        else:
            # Market closed: the final candle of the completed session is due,
            # but allow the documented publication delay before calling it stale.
            threshold = expected - allowance if expected is not None else None
            stale = bool(
                threshold is not None
                and (last_completed is None or last_completed < threshold)
            )
        status = "stale" if stale else (
            "delayed" if provider in _DELAYED_PROVIDERS else "fresh"
        )

    if interval == "1W" and last_candle is not None and last_completed is None:
        status = "incomplete"
        stale = False

    return {
        "provider": provider,
        "interval": interval,
        "last_candle_timestamp": last_candle.isoformat() if last_candle else None,
        "last_completed_candle_timestamp": (
            last_completed.isoformat() if last_completed else None
        ),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "cache_age_seconds": max(0, int(cache_age_s)),
        "served_from_cache": bool(served_from_cache),
        "data_status": status,
        "is_stale": status == "stale",
        "session": session.name,
        "session_open": session.is_open(now),
        "expected_completed_open": expected.isoformat() if expected else None,
    }
