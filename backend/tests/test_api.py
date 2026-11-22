import contextlib
import os
import pathlib
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_test.db"
with contextlib.suppress(OSError):
    os.remove("/tmp/bt_test.db")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.main import create_app
from app.synthetic_engine import run_backtest
from fastapi.testclient import TestClient

BASE = pathlib.Path(__file__).resolve().parent.parent
app = create_app()
c = TestClient(app, raise_server_exceptions=False)


def test_health():
    assert c.get("/health").status_code == 200


def test_register_login_run_flow():
    r = c.post(
        "/api/v1/auth/register", json={"name": "QA", "email": "qa@t.com", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    tok = r.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/v1/templates").json()["total"] == 11
    rb = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "from": "2022-01-01",
            "to": "2023-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
        },
        headers=h,
    )
    assert rb.status_code == 201, rb.text
    bid = rb.json()["id"]
    d = c.get(f"/api/v1/backtests/{bid}", headers=h).json()
    assert len(d["equity"]) > 100 and "disclaimer" in d
    assert c.get("/api/v1/usage", headers=h).json()["usedToday"] >= 1


def test_auth_isolation_and_limits():
    a = c.post(
        "/api/v1/auth/register", json={"name": "A2", "email": "a2@t.com", "password": "password123"}
    ).json()
    b = c.post(
        "/api/v1/auth/register", json={"name": "B2", "email": "b2@t.com", "password": "password123"}
    ).json()
    ha, hb = {"Authorization": "Bearer " + a["token"]}, {"Authorization": "Bearer " + b["token"]}
    rb = c.post("/api/v1/backtests", json={"templateId": "rsi", "asset": "SPY"}, headers=ha).json()
    assert c.get(f"/api/v1/backtests/{rb['id']}", headers=hb).status_code == 404
    bad = c.post("/api/v1/backtests", json={"templateId": "nope", "asset": "AAPL"}, headers=ha)
    assert bad.status_code == 422
    lev = c.post(
        "/api/v1/backtests", json={"templateId": "rsi", "asset": "AAPL", "leverage": 5}, headers=ha
    )
    assert lev.status_code == 422 and lev.json()["code"] == "LEVERAGE_NOT_ALLOWED"


def test_engine_determinism_and_banned_terms():
    cfg = {
        "templateId": "ma-crossover",
        "asset": "AAPL",
        "initialCapital": 10000,
        "feePct": 0.1,
        "params": {},
    }
    assert run_backtest(cfg)["totalReturnPct"] == run_backtest(cfg)["totalReturnPct"]
    banned = ["buy now", "sell now", "guaranteed", "sure profit", "risk-free", "will earn"]
    from app import synthetic_engine as _eng

    blob = ((_eng.DISCLAIMER.get("en", "") or "") + (_eng.DISCLAIMER.get("ar", "") or "")).lower()
    assert not any(b in blob for b in banned)
