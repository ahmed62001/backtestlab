"""Repository layer: DB operations for the market data store."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from ..db import (
    MarketBar,
    MarketCoverage,
    MarketInstrument,
    SessionLocal,
    engine,
)


def _instant(value: Any) -> pd.Timestamp:
    """Parse any ISO-ish boundary to an aware UTC timestamp."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _canonical(value: Any) -> str:
    return str(_instant(value).isoformat())


def _instrument_id(symbol: str, asset_class: str) -> str:
    return "inst-" + hashlib.sha256(f"{symbol}|{asset_class}".encode()).hexdigest()[:16]


def ensure_instrument(
    symbol: str,
    asset_class: str,
    currency: str | None = None,
    exchange: str | None = None,
    name: str | None = None,
) -> str:
    iid = _instrument_id(symbol, asset_class)
    with SessionLocal() as s:
        existing = s.get(MarketInstrument, iid)
        if existing:
            return iid
        s.add(
            MarketInstrument(
                id=iid,
                symbol=symbol,
                asset_class=asset_class,
                currency=currency,
                exchange=exchange,
                name=name,
            )
        )
        try:
            s.commit()
        except IntegrityError:
            # Concurrent creator won the race; the row now exists.
            s.rollback()
    return iid


def upsert_bars(
    instrument_id: str,
    provider: str,
    timeframe: str,
    bars: list[dict[str, Any]],
    adjusted: bool = False,
) -> int:
    if not bars:
        return 0
    now = datetime.now(UTC).isoformat()
    rows = []
    for b in bars:
        rows.append(
            {
                "instrument_id": instrument_id,
                "provider": provider,
                "timeframe": timeframe,
                "ts": b["ts"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b.get("volume"),
                "adjusted": adjusted,
                "ingested_at": now,
            }
        )
    dialect = engine.dialect.name
    table = cast(Any, MarketBar.__table__)
    stmt: Any
    with SessionLocal() as s:
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(table).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="market_bars_pkey",
                set_={
                    c: getattr(stmt.excluded, c)
                    for c in ("open", "high", "low", "close", "volume", "ingested_at")
                },
            )
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(table).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    MarketBar.instrument_id,
                    MarketBar.provider,
                    MarketBar.timeframe,
                    MarketBar.ts,
                    MarketBar.adjusted,
                ],
                set_={
                    c: getattr(stmt.excluded, c)
                    for c in ("open", "high", "low", "close", "volume", "ingested_at")
                },
            )
        s.execute(stmt)
        s.commit()
    return len(rows)


def read_bars(
    instrument_id: str,
    provider: str | None,
    timeframe: str,
    start: str,
    end: str,
    adjusted: bool = False,
) -> list[dict[str, Any]]:
    """Read bars for an instrument. `provider=None` means "any provider"
    (used by the local_store provider, export and verify helpers).

    Timestamps are compared as instants, not as lexicographic strings, so
    ``2024-01-11`` and ``2024-01-11T00:00:00+00:00`` are equivalent (D-PH3-10).
    """
    start_ts, end_ts = _instant(start), _instant(end)
    if start_ts >= end_ts:
        return []
    # Stored timestamps may use different-but-equivalent textual forms (date
    # only, naive, ``Z`` vs ``+00:00``). Query a padded candidate window and
    # filter exactly in Python.
    pad = pd.Timedelta(days=2)
    with SessionLocal() as s:
        conditions = [
            MarketBar.instrument_id == instrument_id,
            MarketBar.timeframe == timeframe,
            MarketBar.adjusted == adjusted,
            MarketBar.ts >= (start_ts - pad).isoformat(),
            MarketBar.ts < (end_ts + pad).isoformat(),
        ]
        if provider is not None:
            conditions.append(MarketBar.provider == provider)
        stmt = select(MarketBar).where(and_(*conditions)).order_by(MarketBar.ts)
        rows = s.scalars(stmt).all()
    out = []
    for r in rows:
        try:
            ts = _instant(r.ts)
        except Exception:  # noqa: BLE001
            continue
        if not (start_ts <= ts < end_ts):
            continue
        out.append(
            {
                "ts": r.ts,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "provider": r.provider,
            }
        )
    return out


def get_coverage(
    instrument_id: str, provider: str | None, timeframe: str, adjusted: bool = False
) -> list[dict[str, Any]]:
    with SessionLocal() as s:
        conditions = [
            MarketCoverage.instrument_id == instrument_id,
            MarketCoverage.timeframe == timeframe,
            MarketCoverage.adjusted == adjusted,
        ]
        if provider is not None:
            conditions.append(MarketCoverage.provider == provider)
        stmt = select(MarketCoverage).where(and_(*conditions))
        rows = s.scalars(stmt).all()
    return [
        {
            "id": r.id,
            "range_start": r.range_start,
            "range_end": r.range_end,
            "row_count": r.row_count,
            "data_hash": r.data_hash,
            "fetched_at": r.fetched_at,
            "expires_at": r.expires_at,
            "status": r.status,
            "last_error_code": r.last_error_code,
        }
        for r in rows
    ]


def upsert_coverage(
    instrument_id: str,
    provider: str,
    timeframe: str,
    range_start: str,
    range_end: str,
    row_count: int,
    data_hash: str | None,
    adjusted: bool = False,
    status: str = "complete",
    expires_at: str | None = None,
    last_error_code: str | None = None,
) -> None:
    """Atomically insert-or-update the single logical coverage row.

    A database-level unique constraint plus a dialect-native upsert removes the
    lookup-then-insert race that produced duplicate coverage rows (D-PH3-12).
    """
    range_start = _canonical(range_start)
    range_end = _canonical(range_end)
    if _instant(range_start) >= _instant(range_end):
        raise ValueError(f"coverage range must be non-empty: {range_start} >= {range_end}")

    now = datetime.now(UTC).isoformat()
    values = {
        "id": "cov-" + uuid.uuid4().hex[:12],
        "instrument_id": instrument_id,
        "provider": provider,
        "timeframe": timeframe,
        "adjusted": adjusted,
        "range_start": range_start,
        "range_end": range_end,
        "row_count": row_count,
        "data_hash": data_hash,
        "fetched_at": now,
        "expires_at": expires_at,
        "status": status,
        "last_error_code": last_error_code,
    }
    update_cols = (
        "row_count",
        "data_hash",
        "fetched_at",
        "expires_at",
        "status",
        "last_error_code",
    )
    dialect = engine.dialect.name
    table = cast(Any, MarketCoverage.__table__)
    stmt: Any
    with SessionLocal() as s:
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(table).values([values])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_market_coverage_key",
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(table).values([values])
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    MarketCoverage.instrument_id,
                    MarketCoverage.provider,
                    MarketCoverage.timeframe,
                    MarketCoverage.adjusted,
                    MarketCoverage.range_start,
                    MarketCoverage.range_end,
                ],
                set_={c: getattr(stmt.excluded, c) for c in update_cols},
            )
        s.execute(stmt)
        s.commit()


def read_coverage_all(limit: int | None = None, offset: int = 0) -> dict[str, Any]:
    """Return instruments and their coverage summaries.

    ``limit``/``offset`` bound the instrument page (the API always passes a
    limit); CLI callers omit them to read everything.
    """
    from sqlalchemy import func

    with SessionLocal() as s:
        total = s.scalar(select(func.count()).select_from(MarketInstrument)) or 0
        stmt = select(MarketInstrument).order_by(MarketInstrument.symbol, MarketInstrument.id)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        if limit is not None:
            stmt = stmt.limit(max(1, int(limit)))
        inst_rows = s.scalars(stmt).all()
        instruments = [
            {
                "id": r.id,
                "symbol": r.symbol,
                "asset_class": r.asset_class,
                "currency": r.currency,
                "exchange": r.exchange,
                "name": r.name,
            }
            for r in inst_rows
        ]
        # Provider/timeframe counts describe the whole store (cheap aggregate).
        bar_counts = s.execute(
            select(
                MarketBar.instrument_id,
                MarketBar.provider,
                MarketBar.timeframe,
                func.count(MarketBar.instrument_id),
            ).group_by(MarketBar.instrument_id, MarketBar.provider, MarketBar.timeframe)
        ).all()
        providers: dict[str, dict[str, int]] = {}
        for _inst_id, provider, timeframe, count in bar_counts:
            key = provider
            if key not in providers:
                providers[key] = {}
            providers[key][timeframe] = count

    return {
        "instruments": instruments,
        "providers": providers,
        "total": int(total),
    }


def purge_all() -> int:
    """Delete all market bars. Returns count deleted."""
    with SessionLocal() as s:
        count = s.query(MarketBar).delete()
        s.commit()
    return count


def purge_coverage() -> int:
    """Delete all coverage rows. Returns count deleted."""
    with SessionLocal() as s:
        count = s.query(MarketCoverage).delete()
        s.commit()
    return count


def purge_bars(
    provider: str | None = None, symbol: str | None = None, older_than: str | None = None
) -> int:
    """Delete bars matching optional provider/symbol/older-than filters."""
    with SessionLocal() as s:
        stmt = s.query(MarketBar)
        if provider is not None:
            stmt = stmt.filter(MarketBar.provider == provider)
        if symbol is not None:
            ids = [
                r.id
                for r in s.scalars(
                    select(MarketInstrument).where(MarketInstrument.symbol == symbol)
                ).all()
            ]
            stmt = stmt.filter(MarketBar.instrument_id.in_(ids))
        if older_than is not None:
            stmt = stmt.filter(MarketBar.ts < older_than)
        count = stmt.delete(synchronize_session=False)
        s.commit()
    return count


def read_coverage() -> dict[str, Any]:
    """Backwards-compatible alias used by the CLI/API verify helpers."""
    return read_coverage_all()


def find_instrument_ids(symbol: str) -> list[str]:
    """All instrument ids for a canonical symbol (any asset class)."""
    with SessionLocal() as s:
        return [
            r.id
            for r in s.scalars(
                select(MarketInstrument).where(MarketInstrument.symbol == symbol)
            ).all()
        ]


def read_bars_for_symbol(
    symbol: str, timeframe: str, start: str, end: str, adjusted: bool = False
) -> list[dict[str, Any]]:
    """Read bars for a symbol across every provider, deduplicated by timestamp.

    Used by the `local_store` provider: it serves the database only and never
    falls through to the network.
    """
    ids = find_instrument_ids(symbol)
    merged: dict[str, dict[str, Any]] = {}
    for iid in ids:
        for bar in read_bars(iid, None, timeframe, start, end, adjusted):
            existing = merged.get(bar["ts"])
            # Prefer a row that actually has volume; otherwise keep the latest.
            if existing is None or (
                existing.get("volume") is None and bar.get("volume") is not None
            ):
                merged[bar["ts"]] = bar
    return sorted(merged.values(), key=lambda b: b["ts"])


def coverage_summary(limit: int | None = None, offset: int = 0) -> dict[str, Any]:
    """Compact summary of what exists in the store (used by local_store catalog).

    The instrument list can be paged (`limit`/`offset`); aggregate timeframes and
    providers always describe the whole store.
    """
    with SessionLocal() as s:
        rows = s.scalars(select(MarketCoverage).where(MarketCoverage.status == "complete")).all()
        instruments: dict[str, dict[str, Any]] = {
            r.instrument_id: {
                "id": r.instrument_id,
                "symbol": None,
                "timeframes": set(),
                "providers": set(),
                "range_start": r.range_start,
                "range_end": r.range_end,
                "row_count": r.row_count,
            }
            for r in rows
        }
        for inst_id, summary in instruments.items():
            inst = s.get(MarketInstrument, inst_id)
            if inst is not None:
                summary["symbol"] = inst.symbol
                summary["asset_class"] = inst.asset_class
        for r in rows:
            summary = instruments[r.instrument_id]
            summary["timeframes"].add(r.timeframe)
            summary["providers"].add(r.provider)
            summary["range_start"] = min(summary["range_start"], r.range_start)
            summary["range_end"] = max(summary["range_end"], r.range_end)
            summary["row_count"] = max(summary["row_count"], r.row_count)

    instruments_out = [
        {
            "id": v["id"],
            "symbol": v["symbol"],
            "assetClass": v.get("asset_class"),
            "timeframes": sorted(v["timeframes"]),
            "providers": sorted(v["providers"]),
            "rangeStart": v["range_start"],
            "rangeEnd": v["range_end"],
            "rowCount": v["row_count"],
        }
        for v in instruments.values()
    ]
    total_instruments = len(instruments_out)
    start = max(0, int(offset))
    if limit is not None:
        instruments_out = instruments_out[start : start + max(1, int(limit))]
    elif start:
        instruments_out = instruments_out[start:]
    timeframes = sorted({tf for v in instruments.values() for tf in v["timeframes"]})
    providers = sorted({p for v in instruments.values() for p in v["providers"]})
    return {
        "instruments": instruments_out,
        "timeframes": timeframes,
        "providers": providers,
        "instrumentCount": total_instruments,
        "total": total_instruments,
        "completeCoverageRows": len(rows),
    }


def store_stats() -> dict[str, Any]:
    """Row/range counts for the `stats` CLI command."""
    from sqlalchemy import func

    with SessionLocal() as s:
        bars = s.scalar(select(func.count()).select_from(MarketBar)) or 0
        coverage = s.scalar(select(func.count()).select_from(MarketCoverage)) or 0
        instruments = s.scalar(select(func.count()).select_from(MarketInstrument)) or 0
        oldest = s.scalar(select(func.min(MarketBar.ts)))
        newest = s.scalar(select(func.max(MarketBar.ts)))
        ingested = s.scalar(select(func.max(MarketBar.ingested_at)))
    return {
        "instruments": instruments,
        "bars": bars,
        "coverageRows": coverage,
        "oldest": oldest,
        "newest": newest,
        "lastIngestedAt": ingested,
    }


def verify_coverage_hashes(limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    """Recompute each complete coverage row's canonical hash and compare.

    Paged so the HTTP diagnostic can bound its response on large stores.
    """
    from .service import _canonical_hash

    results: list[dict[str, Any]] = []
    with SessionLocal() as s:
        stmt = select(MarketCoverage).order_by(MarketCoverage.id)
        start = max(0, int(offset))
        if start:
            stmt = stmt.offset(start)
        if limit is not None:
            stmt = stmt.limit(max(1, int(limit)))
        rows = s.scalars(stmt).all()
        for r in rows:
            if not r.data_hash:
                continue
            bars = read_bars(
                r.instrument_id, r.provider, r.timeframe, r.range_start, r.range_end, r.adjusted
            )
            actual = _canonical_hash(bars) if bars else ""
            results.append(
                {
                    "id": r.id,
                    "instrumentId": r.instrument_id,
                    "provider": r.provider,
                    "timeframe": r.timeframe,
                    "rangeStart": r.range_start,
                    "rangeEnd": r.range_end,
                    "expected": r.data_hash,
                    "actual": actual,
                    "ok": actual == r.data_hash,
                    "rows": len(bars),
                }
            )
    return results
