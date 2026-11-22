"""Phase 4: data provenance must survive persistence and a process restart."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pandas as pd


def _bars(symbol: str, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    rows = []
    for i, _ts in enumerate(idx):
        close = 30000.0 * (1.0 + 0.0003 * i)
        rows.append((close, close * 1.002, close * 0.998, close, 1000.0 + i))
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


def _client():
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


def _auth(c, email: str) -> dict:
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Provenance", "email": email, "password": "password123"},
    )
    if r.status_code != 201:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_provenance_survives_database_and_process_restart(monkeypatch, tmp_path):
    import app.data_providers.base as base_mod
    import app.data_providers.registry as reg
    from app.data_providers.binance_public import BinancePublicProvider
    from app.db import Backtest, SessionLocal, engine

    monkeypatch.setattr(base_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(base_mod, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(reg, "FALLBACK_ENABLED", False)
    monkeypatch.setattr(
        BinancePublicProvider,
        "fetch_ohlcv_raw",
        lambda self, symbol, start, end, interval="1D": _bars(symbol, start, end),
    )

    email = f"prov-{uuid.uuid4().hex[:12]}@t.com"
    c = _client()
    h = _auth(c, email)
    r = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "buy-hold",
            "asset": "BTC/USDT",
            "from": "2022-01-01",
            "to": "2022-12-31",
            "initialCapital": 10000,
            "feePct": 0.1,
            "interval": "1D",
            "params": {},
            "dataProvider": "binance_public",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    bid = created["id"]
    original = created["provenance"]

    expected = {
        "provider": "binance_public",
        "requested_provider": "binance_public",
        "symbol": "BTC-USDT",
        "requested_symbol": "BTC/USDT",
        "asset_class": "crypto",
        "base_currency": "BTC",
        "quote_currency": "USDT",
        "market_type": "spot",
        "interval": "1D",
        "requested_start": "2022-01-01",
        "requested_end": "2022-12-31",
        "price_adjustment": "unadjusted",
        "fallback": False,
        "timezone": "UTC",
    }
    for key, value in expected.items():
        assert original[key] == value, (key, original.get(key), value)
    assert original["dataHash"] and len(original["dataHash"]) == 64
    assert original["start"] and original["end"] and original["retrieved_at"]

    # Persisted scalar columns match the provenance record.
    s = SessionLocal()
    try:
        row = s.get(Backtest, bid)
        assert row is not None
        assert row.data_provider == "binance_public"
        assert row.data_symbol == "BTC-USDT"
        assert row.data_interval == "1D"
        assert row.data_start == original["start"]
        assert row.data_end == original["end"]
        assert row.data_hash == original["dataHash"]
        assert row.data_rows == original["rows"]
    finally:
        s.close()

    # Simulate an application restart: drop the engine pool and rebuild the app.
    engine.dispose()
    reg.clear_provider_info_cache()
    c2 = _client()
    h2 = _auth(c2, email)
    again = c2.get(f"/api/v1/backtests/{bid}", headers=h2)
    assert again.status_code == 200, again.text
    persisted = again.json()["provenance"]
    for key in expected:
        assert persisted[key] == expected[key], (key, persisted.get(key))
    assert persisted["dataHash"] == original["dataHash"]
    assert persisted["retrieved_at"] == original["retrieved_at"]

    # A genuinely separate process must read the same provenance.
    script = f"""
import json
from fastapi.testclient import TestClient
from app.main import create_app
c = TestClient(create_app(), raise_server_exceptions=False)
r = c.post('/api/v1/auth/login', json={{'email': {email!r}, 'password': 'password123'}})
assert r.status_code == 200, r.text
h = {{'Authorization': 'Bearer ' + r.json()['token']}}
d = c.get('/api/v1/backtests/{bid}', headers=h)
assert d.status_code == 200, d.text
print('RESULT:' + json.dumps(d.json()['provenance'], sort_keys=True))
"""
    env = dict(os.environ)
    env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    backend_dir = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    line = next(x for x in proc.stdout.splitlines() if x.startswith("RESULT:"))
    from_subprocess = json.loads(line[len("RESULT:") :])
    assert from_subprocess["provider"] == "binance_public"
    assert from_subprocess["symbol"] == "BTC-USDT"
    assert from_subprocess["dataHash"] == original["dataHash"]
    assert from_subprocess["asset_class"] == "crypto"
    assert from_subprocess["quote_currency"] == "USDT"
