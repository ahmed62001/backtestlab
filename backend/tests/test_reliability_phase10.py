"""Phase 10 — reliability & database quality acceptance tests.

Covers:
* SQLite WAL + busy_timeout PRAGMAs (dev concurrency).
* Worker lease/heartbeat recovery after a simulated crash.
* Graceful-shutdown release of an in-flight job.
* Per-job runtime timeout (compute thread is abandoned safely).
* Idempotent processing (replay never double-writes results).
* Bounded retries for transient provider failures.
* Pagination on list endpoints and bounded equity/trade payloads.
* A single Alembic head and a working downgrade on every migration.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app import db as dbmod
from app import worker
from app.main import create_app


def _iso(delta_s: float = 0.0) -> str:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delta_s)).isoformat()


@pytest.fixture(autouse=True)
def _clean_tables():
    dbmod.init_db()
    s = dbmod.SessionLocal()
    try:
        s.execute(text("DELETE FROM jobs"))
        s.execute(text("DELETE FROM backtests"))
        s.execute(text("DELETE FROM usage"))
        s.execute(text("DELETE FROM password_resets"))
        s.execute(text("DELETE FROM billing_customers"))
        s.execute(text("DELETE FROM refresh_tokens"))
        s.execute(text("DELETE FROM users"))
        s.commit()
    finally:
        s.close()
    yield
    worker._current_jobs.clear()
    worker._current_job_id = ""


def _add_user(uid: str = "u-phase10") -> None:
    s = dbmod.SessionLocal()
    try:
        s.add(dbmod.User(id=uid, email=f"{uid}@t.com", name="P10", password_hash="x"))
        s.commit()
    finally:
        s.close()


def _add_job(
    jid: str = "job-p10",
    bid: str = "bt-p10",
    *,
    status: str = "queued",
    attempts: int = 0,
    max_attempts: int = 3,
    lease_expires_at: str = "",
    config: dict | None = None,
) -> None:
    s = dbmod.SessionLocal()
    try:
        s.add(
            dbmod.Backtest(
                id=bid,
                user_id="u-phase10",
                status=status if status in ("queued", "running", "failed") else "queued",
                result_json="{}",
            )
        )
        s.add(
            dbmod.Job(
                id=jid,
                user_id="u-phase10",
                backtest_id=bid,
                status=status,
                attempts=attempts,
                max_attempts=max_attempts,
                lease_expires_at=lease_expires_at,
                created_at=_iso(-120),
                config_json=json.dumps(config or {"asset": "AAPL"}),
            )
        )
        s.commit()
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 1. DB engine settings
# ---------------------------------------------------------------------------


def test_sqlite_wal_and_busy_timeout(tmp_path):
    # Build a dedicated engine: other test modules swap the process-global
    # engine during collection, so asserting on it would be order-dependent.
    url = f"sqlite:///{tmp_path / 'pragma.db'}"
    eng = dbmod._build_engine(url)
    try:
        with eng.connect() as conn:
            journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        assert str(journal).lower() == "wal"
        assert int(busy) == dbmod.SQLITE_BUSY_TIMEOUT_MS
    finally:
        eng.dispose()


def test_engine_uses_pre_ping(tmp_path):
    eng = dbmod._build_engine(f"sqlite:///{tmp_path / 'preping.db'}")
    try:
        assert eng.pool._pre_ping is True
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# 2. Crash recovery via leases
# ---------------------------------------------------------------------------


def test_recover_stale_running_job_requeues():
    _add_user()
    _add_job(status="running", attempts=1, lease_expires_at=_iso(-120))
    out = worker.recover_stale_jobs(stale_seconds=30)
    assert out["recovered"] == 1 and out["failed"] == 0
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        b = s.get(dbmod.Backtest, "bt-p10")
        assert j.status == "queued"
        assert j.error.startswith("LEASE_EXPIRED")
        assert j.next_attempt_at
        assert b.status == "queued"
    finally:
        s.close()


def test_recover_stale_job_fails_when_retries_exhausted():
    _add_user()
    _add_job(status="running", attempts=3, max_attempts=3, lease_expires_at=_iso(-120))
    out = worker.recover_stale_jobs(stale_seconds=30)
    assert out == {"recovered": 0, "failed": 1}
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        b = s.get(dbmod.Backtest, "bt-p10")
        assert j.status == "failed"
        assert "LEASE_EXPIRED" in j.error
        assert b.status == "failed"
    finally:
        s.close()


def test_recover_only_touches_expired_leases():
    _add_user()
    _add_job(status="running", attempts=1, lease_expires_at=_iso(120))
    assert worker.recover_stale_jobs(stale_seconds=30) == {"recovered": 0, "failed": 0}


# ---------------------------------------------------------------------------
# 3. Graceful shutdown release
# ---------------------------------------------------------------------------


def test_release_current_job_requeues_inflight_work():
    _add_user()
    _add_job(status="running", attempts=1, lease_expires_at=_iso(60), config={"asset": "AAPL"})
    with worker._current_job_lock:
        worker._current_jobs.add("job-p10")
        worker._current_job_id = "job-p10"
    assert worker.release_current_job("TEST") is True
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        assert j.status == "queued"
        assert j.error == "RELEASED:TEST"
        assert j.lease_expires_at == ""
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 4. Timeout / idempotency / bounded retries
# ---------------------------------------------------------------------------


def _fake_result() -> dict:
    return {
        "totalReturnPct": 1.5,
        "maxDrawdownPct": -2.0,
        "sharpe": 0.3,
        "winRatePct": 50.0,
        "trades": 4,
        "vsBuyHoldPct": 0.5,
        "provenance": {
            "provider": "local",
            "symbol": "AAPL",
            "interval": "1D",
            "start": "2022-01-01",
            "end": "2022-12-31",
            "rows": 250,
            "dataHash": "a" * 64,
        },
    }


def test_job_timeout_fails_safely(monkeypatch):
    _add_user()
    _add_job()

    def _slow(_cfg, _uid=None):
        time.sleep(1.0)
        return _fake_result()

    monkeypatch.setattr(worker, "_compute", _slow)
    outcome = worker.execute_job("job-p10", timeout_s=0.1)
    assert outcome == "timeout"
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        b = s.get(dbmod.Backtest, "bt-p10")
        assert j.status == "failed"
        assert j.error.startswith("TIMEOUT:")
        assert b.status == "failed"
        assert b.result_json == "{}"
    finally:
        s.close()


def test_execute_job_is_idempotent(monkeypatch):
    _add_user()
    _add_job()
    monkeypatch.setattr(worker, "_compute", lambda _cfg, _uid=None: _fake_result())

    assert worker.execute_job("job-p10", timeout_s=5) == "done"
    s = dbmod.SessionLocal()
    try:
        first = s.get(dbmod.Backtest, "bt-p10").result_json
        job = s.get(dbmod.Job, "job-p10")
        assert job.status == "done" and job.attempts == 1
    finally:
        s.close()

    # Replaying the same job (e.g. duplicate queue delivery) is a no-op.
    assert worker.execute_job("job-p10", timeout_s=5) == "skipped"
    s = dbmod.SessionLocal()
    try:
        job = s.get(dbmod.Job, "job-p10")
        assert job.attempts == 1
        assert s.get(dbmod.Backtest, "bt-p10").result_json == first
    finally:
        s.close()


def test_transient_failure_is_bounded(monkeypatch):
    _add_user()
    _add_job(max_attempts=2)
    monkeypatch.setattr(
        worker,
        "_compute",
        lambda _cfg, _uid=None: (_ for _ in ()).throw(
            RuntimeError("data provider 'x': UPSTREAM_UNAVAILABLE")
        ),
    )

    assert worker.execute_job("job-p10", timeout_s=5) == "requeued"
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        assert j.status == "queued" and j.attempts == 1
        assert j.next_attempt_at
        j.next_attempt_at = ""  # make it immediately claimable again
        s.commit()
    finally:
        s.close()

    assert worker.execute_job("job-p10", timeout_s=5) == "failed"
    s = dbmod.SessionLocal()
    try:
        j = s.get(dbmod.Job, "job-p10")
        assert j.status == "failed" and j.attempts == 2
        assert j.error.startswith("OUR_FAULT:")
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 5. Pagination + bounded payloads
# ---------------------------------------------------------------------------


def _auth_headers(c: TestClient, email: str) -> dict[str, str]:
    r = c.post(
        "/api/v1/auth/register", json={"name": "P10", "email": email, "password": "password123"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_backtests_list_is_paginated():
    c = TestClient(create_app(), raise_server_exceptions=False)
    h = _auth_headers(c, f"page-{int(time.time() * 1000)}@t.com")
    me = c.get("/api/v1/auth/me", headers=h).json()
    s = dbmod.SessionLocal()
    try:
        for i in range(7):
            s.add(
                dbmod.Backtest(
                    id=f"bt-page-{i}",
                    user_id=me["id"],
                    name=f"run {i}",
                    created_at=_iso(i),
                    result_json="{}",
                )
            )
        s.commit()
    finally:
        s.close()

    first = c.get("/api/v1/backtests?limit=3&offset=0", headers=h).json()
    assert first["total"] == 7
    assert first["limit"] == 3 and first["offset"] == 0
    assert len(first["items"]) == 3
    second = c.get("/api/v1/backtests?limit=3&offset=3", headers=h).json()
    assert len(second["items"]) == 3
    assert {x["id"] for x in first["items"]}.isdisjoint({x["id"] for x in second["items"]})
    # Clamp absurd input instead of returning the whole table.
    huge = c.get("/api/v1/backtests?limit=100000&offset=-5", headers=h).json()
    assert huge["limit"] <= 200 and huge["offset"] == 0


def test_backtest_detail_bounds_equity_and_trades():
    c = TestClient(create_app(), raise_server_exceptions=False)
    h = _auth_headers(c, f"bound-{int(time.time() * 1000)}@t.com")
    me = c.get("/api/v1/auth/me", headers=h).json()
    equity = [
        {"date": f"2020-01-{i:04d}", "strategy": i, "benchmark": 0, "drawdown": 0}
        for i in range(5000)
    ]
    trades = [
        {"id": i, "date": "2020-01-01", "side": "buy", "price": 1.0, "qty": 1, "pnl": 0.0}
        for i in range(1200)
    ]
    s = dbmod.SessionLocal()
    try:
        s.add(
            dbmod.Backtest(
                id="bt-big",
                user_id=me["id"],
                status="done",
                created_at=_iso(),
                result_json=json.dumps(
                    {"equity": equity, "tradesList": trades, "engine": {}, "provenance": {}}
                ),
            )
        )
        s.commit()
    finally:
        s.close()

    d = c.get("/api/v1/backtests/bt-big", headers=h).json()
    meta = d["resultMeta"]
    assert meta["equityDownsampled"] is True
    assert meta["equityTotalPoints"] == 5000
    assert len(d["equity"]) <= 1000
    assert len(d["equity"]) == 1000
    assert d["equity"][0]["date"] == "2020-01-0000"
    assert d["equity"][-1]["date"] == "2020-01-4999"
    assert meta["tradesTruncated"] is True
    assert len(d["tradesList"]) <= 500
    # Newest trades are retained (tail), not silently dropped from the front.
    assert d["tradesList"][-1]["id"] == 1199


def test_compare_is_bounded():
    c = TestClient(create_app(), raise_server_exceptions=False)
    h = _auth_headers(c, f"cmp-{int(time.time() * 1000)}@t.com")
    ids = ",".join(f"missing-{i}" for i in range(40))
    d = c.get(f"/api/v1/compare?ids={ids}", headers=h).json()
    assert d["requested"] == 10
    assert d["truncated"] is True


def test_account_delete_handles_foreign_key_children():
    """SQLite now enforces FKs, so account deletion must clear dependants."""
    c = TestClient(create_app(), raise_server_exceptions=False)
    email = f"del-{int(time.time() * 1000)}@t.com"
    h = _auth_headers(c, email)
    # Login creates a refresh_tokens row that references users.id.
    r = c.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200 and r.json().get("refresh_token")
    d = c.delete("/api/v1/auth/me", headers=h)
    assert d.status_code == 200 and d.json() == {"ok": True}
    assert c.get("/api/v1/auth/me", headers=h).status_code == 401


# ---------------------------------------------------------------------------
# 6. Migration hygiene
# ---------------------------------------------------------------------------


def test_single_alembic_head_and_downgrades_present():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one alembic head, got {heads}"
    for rev in script.walk_revisions():
        src = pathlib.Path(rev.path).read_text(encoding="utf-8")
        assert "def downgrade()" in src, f"{rev.revision} has no downgrade"
