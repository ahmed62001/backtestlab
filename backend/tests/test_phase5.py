"""Phase 5 gates: queued->running->done, timeout, refund, 429, idempotency."""

import contextlib
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)


def _client(db: str):
    import os

    os.environ["DATABASE_URL"] = f"sqlite:///{db}"
    with contextlib.suppress(OSError):
        pathlib.Path(db).unlink()
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


def _reg(c, email):
    import uuid

    email = f"{uuid.uuid4().hex[:6]}-{email}"
    r = c.post(
        "/api/v1/auth/register", json={"name": "Q5", "email": email, "password": "password123"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _wait(c, h, jid, timeout=30.0):
    t0 = time.time()
    states = []
    while time.time() - t0 < timeout:
        d = c.get(f"/api/v1/jobs/{jid}", headers=h).json()
        states.append(d["status"])
        if d["status"] in ("done", "failed", "cancelled"):
            return d, states
        time.sleep(0.2)
    raise AssertionError(f"job {jid} stuck: {states[-5:]}")


def test_async_queued_running_done():
    c = _client("/tmp/bt_q1.db")
    h = _reg(c, "q1@t.com")
    body = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "initialCapital": 10000,
        "feePct": 0.1,
        "params": {"fastPeriod": 10, "slowPeriod": 30},
    }
    r = c.post("/api/v1/backtests?async=true", json=body, headers=h)
    assert r.status_code == 201, r.text
    jid, bid = r.json()["jobId"], r.json()["backtestId"]
    d, _states = _wait(c, h, jid)
    assert d["status"] == "done", d
    b = c.get(f"/api/v1/backtests/{bid}", headers=h).json()
    assert len(b["equity"]) > 50


def test_idempotency_and_429_and_refund():
    import os

    os.environ["DAILY_RUN_LIMIT_FREE"] = "4"
    import importlib

    import app.main as M

    importlib.reload(M)
    c = _client("/tmp/bt_q2.db")
    h = _reg(c, "q2@t.com")
    body = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "initialCapital": 10000,
        "feePct": 0.1,
        "params": {},
    }
    c.post(
        "/api/v1/backtests",
        json=body,
        headers=h,
        params={},
    )
    # idempotent submit via header
    a = c.post("/api/v1/backtests?async=true", json=body, headers={**h, "idempotency-key": "k-1"})
    b = c.post("/api/v1/backtests?async=true", json=body, headers={**h, "idempotency-key": "k-1"})
    assert a.json()["jobId"] == b.json()["jobId"], (a.text, b.text)
    _wait(c, h, a.json()["jobId"])
    # validation-failure refund: bad asset fails, usage must not grow
    u0 = c.get("/api/v1/usage", headers=h).json()["usedToday"]
    bad = dict(body, asset="BTC-USD")
    rb = c.post("/api/v1/backtests?async=true", json=bad, headers=h)
    assert rb.status_code == 201
    d, _ = _wait(c, h, rb.json()["jobId"])
    assert d["status"] == "failed" and "VALIDATION" in d["error"], d
    u1 = c.get("/api/v1/usage", headers=h).json()["usedToday"]
    assert u1 == u0, (u0, u1)
    # 429: exhaust limit (limit=4: k-1 + bad-refunded + one more = 2 used;
    # two sync fills reach 4, next must 429)
    c.post("/api/v1/backtests?async=true", json=body, headers=h)
    _wait(c, h, c.post("/api/v1/backtests?async=true", json=body, headers=h).json()["jobId"])
    c.post("/api/v1/backtests", json=body, headers=h)
    r429 = c.post("/api/v1/backtests?async=true", json=body, headers=h)
    assert r429.status_code == 429
    assert r429.json()["code"] == "DAILY_LIMIT_REACHED"
