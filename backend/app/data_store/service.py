"""MarketDataService: read-through cache over the persistent market data store."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from typing import Any

import pandas as pd

from ..data_providers.base import (
    ERR_DATA_STORE_UNAVAILABLE,
    ProviderError,
    classify_error,
)
from ..data_providers.registry import get_provider
from .normalize import NormalizationResult, normalize_bars
from .repository import (
    ensure_instrument,
    get_coverage,
    read_bars,
    upsert_bars,
    upsert_coverage,
)
from .symbols import canonical_to_provider
from .ttl import expires_at_for, is_expired

log = logging.getLogger("backtestlab.data_store.service")

_DATA_STORE_ENABLED = True
_lock = threading.RLock()
_per_key_locks: dict[str, threading.Lock] = {}


def _key_lock(key: str) -> threading.Lock:
    with _lock:
        if key not in _per_key_locks:
            _per_key_locks[key] = threading.Lock()
        return _per_key_locks[key]


def is_enabled() -> bool:
    return _DATA_STORE_ENABLED


def set_enabled(flag: bool) -> None:
    global _DATA_STORE_ENABLED
    _DATA_STORE_ENABLED = flag


def _store_timeframe(timeframe: str) -> str:
    """Map provider-style intervals to the store's canonical timeframe keys.

    Providers use "1D"/"1H"/"1W"/"1M"; the store uses lowercase keys, except
    monthly "1M" which must stay uppercase so it is not confused with "1m"
    (one minute).
    """
    if timeframe == "1M":
        return "1M"
    return str(timeframe).lower()


def _provider_timeframe(timeframe: str) -> str:
    """Inverse of :func:`_store_timeframe` for provider fetch calls."""
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
        "1w": "1W",
        "1M": "1M",
    }
    return mapping.get(str(timeframe), str(timeframe))


def _active_coverage(cov_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop coverage rows whose TTL has elapsed (they must be re-fetched)."""
    return [c for c in cov_rows if not is_expired(c.get("expires_at"))]


def _canonical_hash(bars: list[dict[str, Any]]) -> str:
    """SHA-256 over canonical serialization: fixed column order, UTC ISO ts, fixed float formatting."""
    payload = []
    for b in bars:
        vol = b.get("volume")
        try:
            vol_f = float(vol) if vol is not None else 0.0
        except (TypeError, ValueError):
            vol_f = 0.0
        if not math.isfinite(vol_f):
            vol_f = 0.0
        payload.append(
            f"{b['ts']}|{b['open']:.6f}|{b['high']:.6f}|{b['low']:.6f}|{b['close']:.6f}|{vol_f:.6f}"
        )
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()


def _ts(value: str) -> pd.Timestamp:
    """Parse any ISO-ish boundary to an aware UTC timestamp for comparison."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _iso(value: str) -> str:
    """Canonical UTC ISO-8601 form used by the store (instant comparison)."""
    return str(_ts(value).isoformat())


_STEP = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
    "1w": pd.Timedelta(days=7),
    "1M": pd.Timedelta(days=31),
}


def coverage_end_exclusive(timeframe: str, requested_end: str, last_ts: str | None) -> str:
    """Return a half-open coverage end that includes the last ingested bar.

    Coverage/read semantics are ``[start, end)``. A provider commonly returns a
    bar exactly at the requested ``end``; storing that hash against the bare
    ``end`` makes verification read one fewer bar. Extend the exclusive end by
    one timeframe step in that case.
    """
    end_ts = _ts(requested_end)
    if last_ts:
        last = _ts(last_ts)
        if last >= end_ts:
            return str((last + _STEP.get(timeframe, pd.Timedelta(days=1))).isoformat())
    return str(end_ts.isoformat())


def coverage_end_after_last_bar(timeframe: str, last_ts: str) -> str:
    """Exclusive end that includes exactly ``last_ts`` (used by CLI ingestion)."""
    return str((_ts(last_ts) + _STEP.get(timeframe, pd.Timedelta(days=1))).isoformat())


def _frame_to_list(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for ts, row in df.iterrows():
        rows.append(
            {
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if row["volume"] is not None else None,
            }
        )
    return rows


def _coverage_covers_full(cov_rows: list[dict[str, Any]], start: str, end: str) -> bool:
    """True if any single *complete* row fully covers [start, end) by instant."""
    start_ts, end_ts = _ts(start), _ts(end)
    for c in cov_rows:
        if c.get("status") != "complete":
            continue
        try:
            if _ts(c["range_start"]) <= start_ts and _ts(c["range_end"]) >= end_ts:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _find_missing_subranges(
    cov_rows: list[dict[str, Any]], start: str, end: str
) -> list[tuple[str, str]]:
    """Return sub-ranges of [start, end) not covered by *complete* rows.

    Non-complete (partial/failed) rows are ignored by design so a failed fetch
    is retried on the next request.
    """
    cover = []
    for c in cov_rows:
        if c.get("status") != "complete" or not c.get("range_start") or not c.get("range_end"):
            continue
        try:
            cover.append((_ts(c["range_start"]), _ts(c["range_end"])))
        except Exception:  # noqa: BLE001
            continue
    start_ts, end_ts = _ts(start), _ts(end)
    missing: list[tuple[str, str]] = []
    cursor = start_ts
    for c_start, c_end in sorted(cover):
        if c_end <= cursor:
            continue
        if c_start > cursor:
            missing.append((cursor.isoformat(), c_start.isoformat()))
        cursor = max(cursor, c_end)
        if cursor >= end_ts:
            break
    if cursor < end_ts:
        missing.append((cursor.isoformat(), end_ts.isoformat()))
    return missing


class MarketDataService:
    """Read-through cache over the persistent market data store."""

    def __init__(self, enabled: bool | None = None):
        self.enabled = is_enabled() if enabled is None else enabled

    def get_bars(
        self,
        provider_id: str,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        adjusted: bool = False,
        refresh: bool = False,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Coalesce identical concurrent requests, then read/fetch.

        Without this lock, N identical concurrent callers each miss the cache
        and issue N provider calls (D-PH3-11).
        """
        key = f"{provider_id}|{symbol}|{timeframe}|{start}|{end}|{adjusted}|{refresh}"
        with _key_lock(key):
            return self._get_bars_locked(
                provider_id, symbol, timeframe, start, end, adjusted, refresh
            )

    def _get_bars_locked(
        self,
        provider_id: str,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        adjusted: bool = False,
        refresh: bool = False,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Fetch bars, using the store as a read-through cache.

        Returns (frame, provenance) where provenance includes:
          retrieval: "store" | "live" | "partial"
          provider: the provider that actually produced the data
          data_hash: canonical SHA-256
          warnings: normalization warnings
        """
        store_tf = _store_timeframe(timeframe)
        provider_tf = _provider_timeframe(timeframe)
        prov_sym = canonical_to_provider(symbol, provider_id) or symbol

        # Canonicalize boundaries once so every comparison, fetch and coverage
        # write uses the same instant representation (D-PH3-10).
        try:
            start = _iso(start)
            end = _iso(end)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(
                provider_id, "BAD_INPUT", f"invalid range {start!r}..{end!r}: {e}"
            ) from e
        if _ts(start) >= _ts(end):
            raise ProviderError(
                provider_id, "BAD_INPUT", f"start must precede end: {start} >= {end}"
            )

        prov: dict[str, Any] = {
            "provider": provider_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "adjusted": adjusted,
            "retrieval": "live",
            "data_hash": "",
            "warnings": [],
            "rows": 0,
        }

        # `local_store` is a read-only view over the database: never write back
        # (that would duplicate rows under a second provider id) and never
        # touch the network.
        if provider_id == "local_store":
            frame = get_provider(provider_id).fetch_ohlcv(prov_sym, start, end, provider_tf)
            bars = _frame_to_list(frame)
            prov["retrieval"] = "store"
            prov["data_hash"] = _canonical_hash(bars)
            prov["rows"] = len(bars)
            return frame, prov

        if not self.enabled:
            return self._fetch_and_store(
                provider_id, symbol, store_tf, provider_tf, start, end, adjusted, prov
            )

        # Ensure instrument exists. A storage failure is infrastructure, not a
        # missing API key (D-PH3-14).
        try:
            inst_id = ensure_instrument(symbol, "equity")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(provider_id, ERR_DATA_STORE_UNAVAILABLE, str(e)) from e

        # Check coverage (expired rows are treated as missing so TTL refreshes work)
        cov_rows = _active_coverage(get_coverage(inst_id, provider_id, store_tf, adjusted))

        if not refresh and _coverage_covers_full(cov_rows, start, end):
            # Full cache hit
            bars = read_bars(inst_id, provider_id, store_tf, start, end, adjusted)
            if bars:
                df = pd.DataFrame(bars)
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.set_index("ts").sort_index()
                prov["retrieval"] = "store"
                prov["data_hash"] = _canonical_hash(bars)
                prov["rows"] = len(bars)
                # Prefer the stored hash for the covering row (stability).
                start_ts, end_ts = _ts(start), _ts(end)
                for c in cov_rows:
                    try:
                        covers = _ts(c["range_start"]) <= start_ts and _ts(c["range_end"]) >= end_ts
                    except Exception:  # noqa: BLE001
                        covers = False
                    if covers and c.get("status") == "complete":
                        prov["data_hash"] = c["data_hash"] or prov["data_hash"]
                        break
                return df, prov

        # refresh=True always refetches the full range (D-PH3-07).
        missing = [(start, end)] if refresh else _find_missing_subranges(cov_rows, start, end)
        all_bars: dict[str, dict] = {}

        # First, read what we have from store
        store_row_count = 0
        if not refresh and cov_rows:
            store_bars = read_bars(inst_id, provider_id, store_tf, start, end, adjusted)
            store_row_count = len(store_bars)
            for b in store_bars:
                all_bars[b["ts"]] = b

        # Fetch missing ranges from provider
        provider = get_provider(provider_id)
        incomplete = False
        fetched_row_count = 0
        for m_start, m_end in missing:
            try:
                df = provider.fetch_ohlcv(prov_sym, m_start, m_end, provider_tf)
            except ProviderError:
                raise
            except Exception as e:  # noqa: BLE001
                raise classify_error(provider_id, e) from e

            norm: NormalizationResult = normalize_bars(
                df, symbol, provider_id, store_tf, m_start, m_end
            )
            prov["warnings"].extend(norm.warnings)
            if norm.frame.empty or norm.rows_invalid:
                # Empty or partially-invalid sub-range: the range is NOT
                # complete and must be retried next time (D-PH3-13).
                incomplete = True
            if norm.frame.empty:
                continue

            bars_list = _frame_to_list(norm.frame)
            fetched_row_count += len(bars_list)

            # Store missing bars
            upsert_bars(inst_id, provider_id, store_tf, bars_list, adjusted)
            for b in bars_list:
                all_bars[b["ts"]] = b

        # Build final result from all bars (store + newly fetched)
        if not all_bars:
            raise ProviderError(
                provider_id, "DATA_NOT_IN_STORE", f"no data for {symbol!r} in {start}..{end}"
            )

        sorted_bars = sorted(all_bars.values(), key=lambda x: x["ts"])
        df = pd.DataFrame(sorted_bars)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()

        # Update coverage for the full range. Never mark a range complete when
        # a missing sub-range produced invalid/empty data. Hash exactly the
        # bars that verification will read back: [range_start, range_end).
        cov_end = coverage_end_exclusive(store_tf, end, sorted_bars[-1]["ts"])
        range_bars = [b for b in sorted_bars if _ts(start) <= _ts(b["ts"]) < _ts(cov_end)]
        prov_hash = _canonical_hash(range_bars)
        upsert_coverage(
            inst_id,
            provider_id,
            store_tf,
            start,
            cov_end,
            len(range_bars),
            prov_hash,
            adjusted,
            status="partial" if incomplete else "complete",
            expires_at=expires_at_for(store_tf, end),
            last_error_code="EMPTY_DATA" if incomplete else None,
        )

        # Retrieval provenance reflects where the bytes actually came from:
        # no provider call -> store; nothing pre-existing -> live; a mix of
        # pre-existing and freshly fetched bars -> partial (D-PH3-06/09).
        if refresh:
            prov["retrieval"] = "live"
        elif not missing:
            prov["retrieval"] = "store"
        elif store_row_count and fetched_row_count:
            prov["retrieval"] = "partial"
        elif fetched_row_count:
            prov["retrieval"] = "live"
        else:
            prov["retrieval"] = "store"
        prov["data_hash"] = prov_hash
        prov["rows"] = len(sorted_bars)
        return df, prov

    def _fetch_and_store(
        self,
        provider_id: str,
        symbol: str,
        store_tf: str,
        provider_tf: str,
        start: str,
        end: str,
        adjusted: bool,
        prov: dict[str, Any],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Fetch from provider, store, and return (frame, prov)."""
        prov_sym = canonical_to_provider(symbol, provider_id) or symbol
        try:
            provider = get_provider(provider_id)
            df = provider.fetch_ohlcv(prov_sym, start, end, provider_tf)
        except Exception as e:  # noqa: BLE001
            raise classify_error(provider_id, e) from e

        # Normalize
        norm: NormalizationResult = normalize_bars(df, symbol, provider_id, store_tf, start, end)
        if norm.frame.empty:
            raise ProviderError(
                provider_id, "DATA_NOT_IN_STORE", f"no bars for {symbol!r} in {start}..{end}"
            )

        bars_list = _frame_to_list(norm.frame)
        prov["warnings"] = list(norm.warnings)

        # Ensure instrument exists
        try:
            inst_id = ensure_instrument(symbol, "equity")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(provider_id, ERR_DATA_STORE_UNAVAILABLE, str(e)) from e

        # Store bars
        upsert_bars(inst_id, provider_id, store_tf, bars_list, adjusted)

        # Update coverage. Extend the exclusive end when the provider returned a
        # bar at/after the requested end so verification reads the same bars
        # (D-PH3-15).
        cov_end = coverage_end_exclusive(store_tf, end, bars_list[-1]["ts"])
        range_bars = [b for b in bars_list if _ts(start) <= _ts(b["ts"]) < _ts(cov_end)]
        prov_hash = _canonical_hash(range_bars)
        upsert_coverage(
            inst_id,
            provider_id,
            store_tf,
            start,
            cov_end,
            len(range_bars),
            prov_hash,
            adjusted,
            status="complete",
            expires_at=expires_at_for(store_tf, end),
        )

        prov["retrieval"] = "live"
        prov["data_hash"] = prov_hash
        prov["rows"] = len(bars_list)
        return df, prov
