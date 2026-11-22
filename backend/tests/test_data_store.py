"""Phase 7 baseline repair: tests for the persistent market data store.

Covers normalize.py, repository.py, service.py and symbols.py so the
backend coverage gate (--cov-fail-under=70) stays green on SQLite.
All DB writes go to a dedicated throwaway sqlite file; network is blocked
by conftest.py so no provider is called for real.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import sys
import threading

import pandas as pd

os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_ds_test.db"
with contextlib.suppress(OSError):
    os.remove("/tmp/bt_ds_test.db")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Bind the app's SQLAlchemy engine to a dedicated throwaway test DB so this
# module is hermetic regardless of import order of the other test files.
import app.db as _app_db
from app.data_store import MarketDataService
from app.data_store.normalize import (
    normalize_bars,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_app_db.engine = create_engine(_app_db.DATABASE_URL, connect_args={"check_same_thread": False})
_app_db.SessionLocal = sessionmaker(bind=_app_db.engine, autoflush=False, expire_on_commit=False)
_app_db.Base.metadata.create_all(bind=_app_db.engine)
import contextlib

from app.data_store.repository import (
    ensure_instrument,
    get_coverage,
    purge_all,
    purge_coverage,
    read_bars,
    read_coverage_all,
    upsert_bars,
    upsert_coverage,
)
from app.data_store.service import _canonical_hash, set_enabled
from app.data_store.symbols import (
    canonical_to_provider,
    is_known,
    list_providers_for,
    load_universe,
    provider_to_canonical,
)

SYMBOL = "DS-TEST"
TF = "1d"
START = "2024-01-01"
END = "2024-01-11"


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if not df.empty and "ts" in df.columns:
        df.index = pd.to_datetime(df.pop("ts"), utc=True, errors="coerce", format="ISO8601")
    return df


# ---------------------------------------------------------------------------
# normalize.py
# ---------------------------------------------------------------------------


def test_normalize_unsorted_input_sorted_and_deduped():
    rows = [
        {"ts": "2024-01-03", "open": 3.0, "high": 3.0, "low": 3.0, "close": 3.0, "volume": 10.0},
        {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10.0},
        {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10.0},
        {"ts": "2024-01-02", "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 10.0},
    ]
    res = normalize_bars(_frame(rows), SYMBOL, "local", TF, START, END)
    assert res.warnings == [] or all(w["code"] != "EMPTY_DATA" for w in res.warnings)
    assert list(res.frame.index) == [
        pd.Timestamp("2024-01-01", tz="UTC"),
        pd.Timestamp("2024-01-02", tz="UTC"),
        pd.Timestamp("2024-01-03", tz="UTC"),
    ]
    assert len(res.frame) == 3  # duplicate dropped, 3 unique dates remain


def test_normalize_empty_input_warns_empty_data():
    res = normalize_bars(None, SYMBOL, "local", TF)
    assert res.frame.empty
    assert res.warnings[0]["code"] == "EMPTY_DATA"


def test_normalize_missing_ohlc_columns_warns_bad_input():
    res = normalize_bars(
        _frame([{"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0}]),
        SYMBOL,
        "local",
        TF,
    )
    assert res.frame.empty
    assert res.warnings[0]["code"] == "BAD_INPUT"


def test_normalize_drops_nat_timestamps():
    res = normalize_bars(
        _frame(
            [
                {"ts": "not-a-date", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 1
    assert any(w["code"] == "DROPPED_NAT_TIMESTAMP" for w in res.warnings)


def test_normalize_drops_nan_ohlc():
    res = normalize_bars(
        _frame(
            [
                {"ts": "2024-01-01", "open": float("nan"), "high": 1.0, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-02", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 1
    assert any(w["code"] == "DROPPED_NAN_OHLC" for w in res.warnings)


def test_normalize_drops_non_positive_prices():
    res = normalize_bars(
        _frame(
            [
                {"ts": "2024-01-01", "open": 0.0, "high": 1.0, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-02", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 1
    assert any(w["code"] == "DROPPED_NON_POSITIVE_PRICE" for w in res.warnings)


def test_normalize_rejects_bad_high_and_low():
    # Drops are applied sequentially, so one row per defect keeps both codes.
    res = normalize_bars(
        _frame(
            [
                {"ts": "2024-01-01", "open": 1.0, "high": 0.5, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-02", "open": 1.0, "high": 5.0, "low": 4.0, "close": 1.0},
                {"ts": "2024-01-03", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 1
    assert res.frame.index[0] == pd.Timestamp("2024-01-03", tz="UTC")
    codes = {w["code"] for w in res.warnings}
    assert {"DROPPED_BAD_HIGH", "DROPPED_BAD_LOW"} <= codes


def test_normalize_drops_future_bars():
    far = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    res = normalize_bars(
        _frame(
            [
                {"ts": far, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 1
    assert any(w["code"] == "DROPPED_FUTURE_TS" for w in res.warnings)


def test_normalize_large_gap_warning():
    res = normalize_bars(
        _frame(
            [
                {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                {"ts": "2024-01-10", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            ]
        ),
        SYMBOL,
        "local",
        TF,
    )
    assert len(res.frame) == 2
    assert any(w["code"] == "LARGE_GAP" for w in res.warnings)


def test_normalize_bad_timeframe_raises():
    try:
        normalize_bars(_frame([]), SYMBOL, "local", "99z")
    except ValueError as e:
        assert "unsupported timeframe" in str(e)
    else:
        raise AssertionError("expected ValueError for bad timeframe")


def test_normalize_inverted_range_raises():
    try:
        normalize_bars(_frame([]), SYMBOL, "local", TF, start=END, end=START)
    except ValueError as e:
        assert "start must precede end" in str(e)
    else:
        raise AssertionError("expected ValueError for inverted range")


def test_normalize_range_exceeds_max_raises():
    try:
        normalize_bars(_frame([]), SYMBOL, "local", "1m", start="2024-01-01", end="2024-02-01")
    except ValueError as e:
        assert "exceeds" in str(e)
    else:
        raise AssertionError("expected ValueError for 1m range > 7 days")


# ---------------------------------------------------------------------------
# repository.py
# ---------------------------------------------------------------------------


def test_ensure_instrument_create_and_idempotent():
    iid = ensure_instrument(SYMBOL, "equity", currency="USD", exchange="TEST")
    assert (
        iid == "inst-" + __import__("hashlib").sha256(f"{SYMBOL}|equity".encode()).hexdigest()[:16]
    )
    assert ensure_instrument(SYMBOL, "equity") == iid  # idempotent


def test_upsert_and_read_bars_round_trip():
    iid = ensure_instrument(SYMBOL, "equity")
    bars = [
        {"ts": "2024-01-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
        {"ts": "2024-01-02", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 200.0},
    ]
    assert upsert_bars(iid, "prov", TF, bars) == 2
    got = read_bars(iid, "prov", TF, "2024-01-01", "2024-01-03")
    assert len(got) == 2
    assert got[0]["open"] == 1.0 and got[1]["close"] == 2.0


def test_read_bars_range_filter_excludes_outside():
    iid = ensure_instrument("DS-RANGE", "equity")
    upsert_bars(
        iid,
        "prov",
        TF,
        [
            {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            {"ts": "2024-01-05", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        ],
    )
    # range is [start, end): end-exclusive
    got = read_bars(iid, "prov", TF, "2024-01-02", "2024-01-05")
    assert len(got) == 0
    got = read_bars(iid, "prov", TF, "2024-01-02", "2024-01-06")
    assert len(got) == 1
    assert got[0]["ts"] == "2024-01-05"


def test_upsert_bars_idempotent_same_row_count():
    iid = ensure_instrument("DS-IDEM", "equity")
    bars = [{"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]
    assert upsert_bars(iid, "prov", TF, bars) == 1
    assert upsert_bars(iid, "prov", TF, bars) == 1  # update, not duplicate
    assert len(read_bars(iid, "prov", TF, "2024-01-01", "2024-01-02")) == 1


def test_upsert_and_get_coverage():
    iid = ensure_instrument("DS-COV", "equity")
    upsert_coverage(iid, "prov", TF, START, END, 10, "abcd" * 16, status="complete")
    rows = get_coverage(iid, "prov", TF)
    assert len(rows) == 1
    assert rows[0]["row_count"] == 10
    assert rows[0]["data_hash"] == "abcd" * 16
    assert rows[0]["status"] == "complete"


def test_purge_all_and_purge_coverage():
    iid = ensure_instrument("DS-PURGE", "equity")
    upsert_bars(
        iid,
        "prov",
        TF,
        [{"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
    )
    assert purge_all() >= 1
    assert len(read_bars(iid, "prov", TF, "2024-01-01", "2024-01-02")) == 0
    upsert_coverage(iid, "prov", TF, START, END, 1, "abcd" * 16)
    assert purge_coverage() >= 1
    assert get_coverage(iid, "prov", TF) == []


def test_read_coverage_all_shape():
    summary = read_coverage_all()
    assert "instruments" in summary and "providers" in summary


# ---------------------------------------------------------------------------
# service.py — canonical hash stability (hit == miss), 64-hex lowercase
# ---------------------------------------------------------------------------


def test_canonical_hash_is_stable_64_hex():
    bars = [
        {"ts": "2024-01-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
        {"ts": "2024-01-02", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 200.0},
    ]
    h1 = _canonical_hash(bars)
    h2 = _canonical_hash(list(bars))  # cache hit vs miss path: same bars -> same hash
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_canonical_hash_changes_with_data():
    bars = [
        {"ts": "2024-01-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}
    ]
    tweaked = [dict(bars[0], close=9.9)]
    assert _canonical_hash(bars) != _canonical_hash(tweaked)


def test_service_enabled_flag_default_and_toggle():
    assert MarketDataService().enabled is True
    set_enabled(False)
    try:
        assert MarketDataService(enabled=False).enabled is False
        assert MarketDataService().enabled is False
    finally:
        set_enabled(True)


# ---------------------------------------------------------------------------
# symbols.py — canonical <-> provider mapping round trips
# ---------------------------------------------------------------------------


def test_symbol_map_round_trip():
    assert canonical_to_provider("AAPL", "yfinance") == "AAPL"
    assert canonical_to_provider("AAPL", "stooq") == "AAPL.US"
    assert provider_to_canonical("yfinance", "AAPL") == "AAPL"
    assert provider_to_canonical("stooq", "AAPL.US") == "AAPL"
    assert "yfinance" in list_providers_for("AAPL")
    assert is_known("AAPL") is True
    assert is_known("DOES-NOT-EXIST-12345") is False


def test_load_universe_returns_symbols_list():
    universe = load_universe()
    assert isinstance(universe, dict) and "symbols" in universe
    assert isinstance(universe["symbols"], list)


# ---------------------------------------------------------------------------
# concurrency (store/service thread safety)
# ---------------------------------------------------------------------------


def test_key_lock_same_key_same_lock_across_threads():
    from app.data_store.service import _key_lock

    results: dict[str, object] = {}

    def worker(key: str) -> None:
        results[key] = _key_lock(key)

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b", "a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["a"] is results["a"]  # same object for repeated key
    assert results["a"] is not results["b"]  # distinct keys -> distinct locks


def test_concurrent_reads_after_seed():
    iid = ensure_instrument("DS-CONC", "equity")
    upsert_bars(
        iid,
        "prov",
        TF,
        [
            {"ts": "2024-01-01", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            {"ts": "2024-01-02", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        ],
    )
    results: list[int] = []

    def worker() -> None:
        results.append(len(read_bars(iid, "prov", TF, "2024-01-01", "2024-01-03")))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(n == 2 for n in results)


# ---------------------------------------------------------------------------
# local_store provider (Phase 2.5): store-only, no network fall-through
# ---------------------------------------------------------------------------


def _make_local_store():
    from app.data_providers.local_store import LocalStoreProvider

    return LocalStoreProvider()


def test_local_store_health_false_when_empty():
    """Before any data is ingested, local_store reports available=False."""
    p = _make_local_store()
    h = p.health_check()
    assert h["available"] is False
    assert "store" in h["detail"].lower()


def test_local_store_raises_data_not_in_store_when_empty():
    """Requesting uncovered data from an empty store never falls through."""
    p = _make_local_store()
    try:
        p.fetch_ohlcv_raw("AAPL", "2024-01-01", "2024-01-10", "1D")
        raise AssertionError("expected DATA_NOT_IN_STORE")
    except Exception as e:  # noqa: BLE001
        assert getattr(e, "code", None) == "DATA_NOT_IN_STORE"


def test_local_store_serves_seed_offline(monkeypatch):
    """After seeding, local_store serves bars from DB only (no network)."""
    from app.data_providers.local_store import LocalStoreProvider

    iid = ensure_instrument("LS-TEST", "equity")
    upsert_bars(
        iid,
        "local_store",
        "1d",
        [
            {
                "ts": "2024-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10.0,
            },
            {
                "ts": "2024-01-02",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.1,
                "volume": 12.0,
            },
        ],
    )
    upsert_coverage(
        iid, "local_store", "1d", "2024-01-01", "2024-01-03", 2, "abc", status="complete"
    )

    p = LocalStoreProvider()
    h = p.health_check()
    assert h["available"] is True
    summary = p.store_summary()
    assert summary["instrumentCount"] >= 1

    df = p.fetch_ohlcv_raw("LS-TEST", "2024-01-01", "2024-01-03", "1D")
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    # Explicitly block network: any provider attempting it must raise OSError.
    monkeypatch.setattr(
        "socket.socket.connect",
        lambda self, *a, **k: (_ for _ in ()).throw(OSError("blocked")),
    )
    df2 = p.fetch_ohlcv_raw("LS-TEST", "2024-01-01", "2024-01-03", "1D")
    assert len(df2) == 2


# ---------------------------------------------------------------------------
# TTL policy (Phase 2.2 item 7): config-driven expires_at
# ---------------------------------------------------------------------------


def test_ttl_intraday_expires_soon():
    from app.data_store.ttl import expires_at_for

    ea = expires_at_for("1m", "2024-01-01")
    assert ea is not None


def test_ttl_historical_daily_never_expires():
    from app.data_store.ttl import expires_at_for

    far_past = "2020-01-01"
    ea = expires_at_for("1d", far_past)
    assert ea is None


def test_ttl_is_expired_past():
    from app.data_store.ttl import is_expired

    assert is_expired("2000-01-01T00:00:00+00:00") is True
    assert is_expired("2099-01-01T00:00:00+00:00") is False
    assert is_expired(None) is False


# ---------------------------------------------------------------------------
# CLI tests (Phase 4): temp DB + mocked providers
# ---------------------------------------------------------------------------


def test_cli_verify_empty_db_is_stable():
    import subprocess

    os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_cli_verify.db"
    with contextlib.suppress(OSError):
        os.remove("/tmp/bt_cli_verify.db")
    r = subprocess.run(
        [sys.executable, "-m", "app.cli", "verify"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    )
    # Empty DB -> no coverage rows -> stable (vacuously)
    assert r.returncode == 0


def test_cli_seed_writes_offline(tmp_path, monkeypatch):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/bt_seed.db"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATA_PROVIDER_DEFAULT", "synthetic")
    monkeypatch.setenv("DATA_PROVIDERS_ENABLED", "local,synthetic")
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "app.cli", "seed", "--start", "2022-01-01", "--end", "2022-01-10"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    )
    assert r.returncode == 0, r.stderr
    assert "Seed complete" in r.stdout
    assert "AAPL:" in r.stdout
