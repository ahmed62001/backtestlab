"""Normalization & validation pipeline for market data bars.

Every bar set, from any provider, passes through the same pipeline:
- sort ascending by ts, drop exact duplicates, convert to UTC, enforce numeric dtypes
- reject/repair rows with NaN OHLC, non-positive prices, high < max(open, close, low)
  or low > min(open, close, high)
- detect large gaps / unsorted / future timestamps; reject future bars
- never silently fabricate bars
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("backtestlab.data_store.normalize")

VALID_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")

MAX_RANGE_BY_TIMEFRAME: dict[str, int] = {
    "1m": 7,
    "5m": 30,
    "15m": 60,
    "30m": 90,
    "1h": 180,
    "4h": 365,
    "1d": 3650,
    "1w": 3650,
    "1M": 3650,
}


@dataclass
class NormalizationResult:
    frame: pd.DataFrame
    warnings: list[dict[str, str]] = field(default_factory=list)
    rows_dropped: int = 0
    # Subset of ``rows_dropped`` removed because the row itself was invalid
    # (bad timestamp/price/volume). Duplicate-timestamp de-duplication is not
    # counted here: collapsing exact duplicates loses no bar coverage.
    rows_invalid: int = 0


def _validate_timeframe(timeframe: str) -> None:
    if timeframe not in VALID_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe {timeframe!r} (valid: {VALID_TIMEFRAMES})")


def _validate_range(start: str, end: str, timeframe: str) -> None:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    if start_ts >= end_ts:
        raise ValueError(f"start must precede end: {start} >= {end}")
    max_days = MAX_RANGE_BY_TIMEFRAME.get(timeframe, 365)
    if (end_ts - start_ts).days > max_days:
        raise ValueError(
            f"range for {timeframe} exceeds {max_days} days: {(end_ts - start_ts).days} days"
        )


def normalize_bars(
    raw: pd.DataFrame | None,
    symbol: str,
    provider: str,
    timeframe: str,
    start: str | None = None,
    end: str | None = None,
) -> NormalizationResult:
    """Normalize + validate a provider's OHLCV bars."""
    _validate_timeframe(timeframe)
    if start and end:
        _validate_range(start, end, timeframe)

    warns: list[dict[str, str]] = []
    rows_dropped = 0
    rows_invalid = 0

    if raw is None or len(raw) == 0:
        return NormalizationResult(
            frame=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
            warnings=[{"code": "EMPTY_DATA", "message": f"no bars for {symbol!r}"}],
            rows_dropped=0,
        )

    out = raw.copy()
    rename = {c: str(c).strip().lower() for c in out.columns}
    out = out.rename(columns=rename)

    missing = [c for c in ("open", "high", "low", "close") if c not in out.columns]
    if missing:
        return NormalizationResult(
            frame=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
            warnings=[
                {"code": "BAD_INPUT", "message": f"missing OHLC columns {missing} for {symbol!r}"}
            ],
            rows_dropped=len(out),
            rows_invalid=len(out),
        )

    if "volume" not in out.columns:
        out["volume"] = 0.0

    if not isinstance(out.index, pd.DatetimeIndex):
        date_col = None
        for cand in ("date", "trade_date", "datetime", "timestamp", "ts"):
            if cand in out.columns:
                date_col = cand
                break
        if date_col:
            parsed = pd.to_datetime(out[date_col], utc=True, errors="coerce")
            out = out.assign(**{date_col: parsed}).set_index(date_col)
        else:
            # A frame with OHLCV columns but no timestamp is ambiguous. Never
            # coerce a RangeIndex/ordinal into nanoseconds (that fabricates
            # bars at 1970-01-01). Reject the batch instead.
            return NormalizationResult(
                frame=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
                warnings=[
                    {
                        "code": "BAD_INPUT",
                        "message": (
                            f"missing date/timestamp column for {symbol!r}; "
                            "refusing to fabricate timestamps"
                        ),
                    }
                ],
                rows_dropped=len(out),
                rows_invalid=len(out),
            )

    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")

    nat_mask = out.index.isna()
    if nat_mask.any():
        n = int(nat_mask.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_NAT_TIMESTAMP",
                "message": f"dropped {n} rows with NaT timestamps for {symbol!r}",
            }
        )
        out = out[~nat_mask]

    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    nan_mask = out[["open", "high", "low", "close"]].isna().any(axis=1)
    if nan_mask.any():
        n = int(nan_mask.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_NAN_OHLC",
                "message": f"dropped {n} rows with NaN OHLC for {symbol!r}",
            }
        )
        out = out[~nan_mask]

    # Reject any non-finite OHLC value (NaN already dropped above; this also
    # catches +Inf/-Inf which otherwise poison metrics and hashes).
    finite_mask = np.isfinite(out[["open", "high", "low", "close"]].to_numpy(dtype=float)).all(
        axis=1
    )
    if not finite_mask.all():
        n = int((~finite_mask).sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_NON_FINITE_PRICE",
                "message": f"dropped {n} rows with non-finite prices for {symbol!r}",
            }
        )
        out = out[finite_mask]

    pos_mask = (out[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if pos_mask.any():
        n = int(pos_mask.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_NON_POSITIVE_PRICE",
                "message": f"dropped {n} rows with non-positive prices for {symbol!r}",
            }
        )
        out = out[~pos_mask]

    # Volume is optional but must be finite and non-negative when present.
    # Coerce invalid volume to 0 (prices remain valid) and report it; this
    # also keeps the canonical hash deterministic (None/NaN -> 0.000000).
    vol = pd.to_numeric(out["volume"], errors="coerce")
    vol_bad = ~np.isfinite(vol.to_numpy(dtype=float)) | (vol < 0)
    if bool(vol_bad.any()):
        n = int(vol_bad.sum())
        warns.append(
            {
                "code": "COERCED_INVALID_VOLUME",
                "message": f"coerced {n} invalid volume values to 0 for {symbol!r}",
            }
        )
        out["volume"] = vol.where(~vol_bad, 0.0)
    high_bad = out["high"] < out[["open", "close", "low"]].max(axis=1)
    if high_bad.any():
        n = int(high_bad.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_BAD_HIGH",
                "message": f"dropped {n} rows with high < max(open, close, low) for {symbol!r}",
            }
        )
        out = out[~high_bad]

    low_bad = out["low"] > out[["open", "close", "high"]].min(axis=1)
    if low_bad.any():
        n = int(low_bad.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_BAD_LOW",
                "message": f"dropped {n} rows with low > min(open, close, high) for {symbol!r}",
            }
        )
        out = out[~low_bad]

    out = out.sort_index()

    dup_mask = out.index.duplicated(keep="first")
    if dup_mask.any():
        n = int(dup_mask.sum())
        rows_dropped += n
        warns.append(
            {
                "code": "DROPPED_DUPLICATE_TS",
                "message": f"dropped {n} duplicate timestamps for {symbol!r}",
            }
        )
        out = out[~dup_mask]

    now = pd.Timestamp.now(tz="UTC")
    future_mask = out.index > now
    if future_mask.any():
        n = int(future_mask.sum())
        rows_dropped += n
        rows_invalid += n
        warns.append(
            {
                "code": "DROPPED_FUTURE_TS",
                "message": f"dropped {n} future-dated bars for {symbol!r}",
            }
        )
        out = out[~future_mask]

    if len(out) > 1:
        diffs = out.index.to_series().diff().dropna()
        expected = {
            "1m": pd.Timedelta(minutes=1),
            "5m": pd.Timedelta(minutes=5),
            "15m": pd.Timedelta(minutes=15),
            "30m": pd.Timedelta(minutes=30),
            "1h": pd.Timedelta(hours=1),
            "4h": pd.Timedelta(hours=4),
            "1d": pd.Timedelta(days=1),
            "1w": pd.Timedelta(days=7),
            "1M": pd.Timedelta(days=31),
        }.get(timeframe, pd.Timedelta(days=1))
        large_gap_mask = diffs > expected * 3
        if large_gap_mask.any():
            n = int(large_gap_mask.sum())
            warns.append(
                {
                    "code": "LARGE_GAP",
                    "message": f"{n} large time gaps detected for {symbol!r} ({timeframe})",
                }
            )

    if len(out) == 0:
        return NormalizationResult(
            frame=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
            warnings=[
                {"code": "EMPTY_DATA", "message": f"all rows dropped while normalizing {symbol!r}"}
            ],
            rows_dropped=rows_dropped,
            rows_invalid=rows_invalid,
        )

    out = out[["open", "high", "low", "close", "volume"]].astype(float)
    return NormalizationResult(
        frame=out, warnings=warns, rows_dropped=rows_dropped, rows_invalid=rows_invalid
    )
