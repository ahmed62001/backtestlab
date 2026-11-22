"""Dedicated live-provider verification suite (Section 12 & 13).

Reads credentials from backend/.env in memory (never prints or logs them),
runs minimal date-window probes against TwelveData, Massive, and FRED,
verifies TwelveData WebSocket live tick delivery, and exercises real
BacktestLab API workflows (catalog, backtest creation, macro series, WS ticket).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib
import sys
import time
from typing import Any

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_env_privately() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    allowed = {"TWELVEDATA_API_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY", "FRED_API_KEY"}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in allowed and v and k not in os.environ:
            os.environ[k] = v


def _probe_provider_matrix() -> list[dict[str, Any]]:
    from app.data_providers.base import ProviderError
    from app.data_providers.fred import FredProvider
    from app.data_providers.polygon import PolygonProvider
    from app.data_providers.twelvedata import TwelveDataProvider

    results: list[dict[str, Any]] = []
    td = TwelveDataProvider()
    ms = PolygonProvider()
    fr = FredProvider()

    end_d = dt.date.today()
    start_d = end_d - dt.timedelta(days=10)
    intraday_start = end_d - dt.timedelta(days=3)

    # TwelveData matrix
    for label, sym, iv, s, e in [
        ("AAPL daily", "AAPL", "1D", str(start_d), str(end_d)),
        ("AAPL intraday", "AAPL", "1H", str(intraday_start), str(end_d)),
        ("EUR/USD", "EURUSD", "1D", str(start_d), str(end_d)),
        ("BTC/USD", "BTC-USD", "1D", str(start_d), str(end_d)),
    ]:
        t0 = time.monotonic()
        try:
            df = td.fetch_ohlcv(sym, s, e, iv)
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "twelvedata",
                    "test": label,
                    "symbol": sym,
                    "interval": iv,
                    "status": "PASS",
                    "bars": len(df),
                    "first": str(df.index[0]),
                    "last": str(df.index[-1]),
                    "latency_ms": ms_lat,
                    "note": "",
                }
            )
        except ProviderError as exc:
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "twelvedata",
                    "test": label,
                    "symbol": sym,
                    "interval": iv,
                    "status": "ENTITLEMENT_OR_PLAN" if exc.code in ("PROVIDER_NOT_ENTITLED", "RATE_LIMITED") else "FAIL",
                    "bars": 0,
                    "latency_ms": ms_lat,
                    "note": f"{exc.code}",
                }
            )

    # Massive matrix (respecting 5 req/min spacing on free tier via short sleep if needed)
    for label, sym, iv, s, e in [
        ("AAPL daily", "AAPL", "1D", str(start_d), str(end_d)),
        ("AAPL intraday", "AAPL", "1H", str(intraday_start), str(end_d)),
        ("EUR/USD", "EURUSD", "1D", str(start_d), str(end_d)),
        ("BTC/USD", "BTC-USD", "1D", str(start_d), str(end_d)),
    ]:
        t0 = time.monotonic()
        try:
            df = ms.fetch_ohlcv(sym, s, e, iv)
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "polygon (massive)",
                    "test": label,
                    "symbol": sym,
                    "interval": iv,
                    "status": "PASS",
                    "bars": len(df),
                    "first": str(df.index[0]),
                    "last": str(df.index[-1]),
                    "latency_ms": ms_lat,
                    "note": "",
                }
            )
        except ProviderError as exc:
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "polygon (massive)",
                    "test": label,
                    "symbol": sym,
                    "interval": iv,
                    "status": "NO_DATA_OR_DELAYED" if exc.code in ("UNKNOWN_SYMBOL", "PROVIDER_NOT_ENTITLED") else "FAIL",
                    "bars": 0,
                    "latency_ms": ms_lat,
                    "note": f"{exc.code}",
                }
            )

    # FRED matrix
    for sid in ["GDP", "CPIAUCSL", "DGS10", "UNRATE", "FEDFUNDS", "M2SL"]:
        t0 = time.monotonic()
        try:
            out = fr.fetch_macro_observations(sid, start="2024-01-01", limit=20)
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "fred",
                    "test": sid,
                    "symbol": sid,
                    "interval": out.get("frequencyShort") or "macro",
                    "status": "PASS",
                    "bars": out["validCount"],
                    "first": out["firstDate"],
                    "last": out["lastDate"],
                    "units": out["unitsShort"],
                    "latency_ms": ms_lat,
                    "note": "",
                }
            )
        except ProviderError as exc:
            ms_lat = int((time.monotonic() - t0) * 1000)
            results.append(
                {
                    "provider": "fred",
                    "test": sid,
                    "symbol": sid,
                    "interval": "macro",
                    "status": "FAIL",
                    "bars": 0,
                    "latency_ms": ms_lat,
                    "note": f"{exc.code}",
                }
            )

    return results


async def _probe_twelvedata_ws() -> dict[str, Any]:
    import websockets

    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    url = os.environ.get("TWELVEDATA_WS_URL", "wss://ws.twelvedata.com/v1/quotes/price")
    t0 = time.monotonic()
    try:
        async with websockets.connect(
            url,
            additional_headers={"X-TD-APIKEY": key},
            open_timeout=10,
            ping_interval=10,
            ping_timeout=20,
        ) as ws:
            await ws.send(json.dumps({"action": "subscribe", "params": {"symbols": "BTC/USD"}}))
            sub_status = None
            tick = None
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("event") == "subscribe-status":
                    sub_status = msg.get("status")
                elif msg.get("event") == "price":
                    tick = {
                        "symbol": msg.get("symbol"),
                        "price": msg.get("price"),
                        "timestamp": msg.get("timestamp"),
                    }
                    break
            return {
                "status": "PASS" if tick else ("SUBSCRIBED_NO_TICK" if sub_status == "ok" else "FAIL"),
                "sub_status": sub_status,
                "tick": tick,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "error": type(exc).__name__, "latency_ms": int((time.monotonic() - t0) * 1000)}


def _probe_app_e2e() -> dict[str, Any]:
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_live_probe.db")
    os.environ["DATA_PROVIDERS_ENABLED"] = "twelvedata,polygon,fred,yfinance,local,synthetic"
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "LiveQA", "email": "live_qa@t.com", "password": "password123"},
    )
    if r.status_code == 201:
        tok = r.json()["token"]
    else:
        tok = c.post(
            "/api/v1/auth/login",
            json={"email": "live_qa@t.com", "password": "password123"},
        ).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}

    cat = c.get("/api/v1/data-providers").json()
    by_id = {x["id"]: x for x in cat["items"]}

    end_d = dt.date.today()
    start_d = end_d - dt.timedelta(days=180)
    bt_td = c.post(
        "/api/v1/backtests",
        headers=hdr,
        json={
            "name": "Live TD AAPL",
            "asset": "AAPL",
            "template": "sma_crossover",
            "params": {"fastPeriod": 10, "slowPeriod": 30},
            "startDate": str(start_d),
            "endDate": str(end_d),
            "initialCapital": 10000,
            "feeBps": 5,
            "slippageBps": 2,
            "dataProvider": "twelvedata",
        },
    )
    bt_ms = c.post(
        "/api/v1/backtests",
        headers=hdr,
        json={
            "name": "Live Massive BTC",
            "asset": "BTC-USD",
            "template": "sma_crossover",
            "params": {"fastPeriod": 10, "slowPeriod": 30},
            "startDate": str(start_d),
            "endDate": str(end_d),
            "initialCapital": 10000,
            "feeBps": 5,
            "slippageBps": 2,
            "dataProvider": "polygon",
        },
    )
    macro_gdp = c.get("/api/v1/macro/series?series_id=GDP&limit=5", headers=hdr)
    ws_tkt = c.post("/api/v1/auth/ws-ticket", headers=hdr)

    return {
        "catalog_polygon_name": by_id["polygon"]["nameEn"],
        "catalog_twelvedata_available": by_id["twelvedata"]["available"],
        "catalog_polygon_available": by_id["polygon"]["available"],
        "catalog_fred_available": by_id["fred"]["available"],
        "bt_twelvedata_status": bt_td.status_code,
        "bt_twelvedata_provider": bt_td.json().get("provenance", {}).get("provider") if bt_td.status_code in (200, 201) else bt_td.text[:120],
        "bt_massive_status": bt_ms.status_code,
        "bt_massive_provider": bt_ms.json().get("provenance", {}).get("provider") if bt_ms.status_code in (200, 201) else bt_ms.text[:120],
        "macro_gdp_status": macro_gdp.status_code,
        "macro_gdp_count": macro_gdp.json().get("validCount") if macro_gdp.status_code == 200 else 0,
        "ws_ticket_status": ws_tkt.status_code,
    }


def main() -> None:
    _load_env_privately()
    matrix = _probe_provider_matrix()
    ws_res = asyncio.run(_probe_twelvedata_ws())
    e2e_res = _probe_app_e2e()
    print(json.dumps({"matrix": matrix, "twelvedata_ws": ws_res, "app_e2e": e2e_res}, indent=2))


if __name__ == "__main__":
    main()
