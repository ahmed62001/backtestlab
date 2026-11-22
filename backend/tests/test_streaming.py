"""Live streaming: adapter parsing, manager policy, WS endpoint (no real network).

The fake upstream is a local ``websockets.serve`` instance standing in for
ws.twelvedata.com; the socket guard allows loopback only for these tests.
No real provider is contacted.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib
import socket
import sys
import threading
import time

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_test.db")

import app.streaming as streaming  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "StreamQA", "email": "stream_qa@t.com", "password": "password123"},
    )
    if r.status_code == 201:
        tok = r.json()["token"]
    else:
        r2 = c.post(
            "/api/v1/auth/login",
            json={"email": "stream_qa@t.com", "password": "password123"},
        )
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    adapter = streaming.get_manager()  # touch singleton early
    assert adapter is not None
    return c, tok


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def _price_msg(**over):
    ts = int(dt.datetime.now(dt.UTC).timestamp())
    msg = {
        "event": "price",
        "symbol": "AAPL",
        "currency": "USD",
        "exchange": "NASDAQ",
        "type": "Common Stock",
        "timestamp": ts,
        "price": 342.0157,
        "day_volume": 27631112,
    }
    msg.update(over)
    return msg


def test_parse_price_event_valid():
    tick = streaming._parse_price_event(_price_msg())
    assert tick is not None
    assert tick.symbol == "AAPL"
    assert tick.price == pytest.approx(342.0157)
    assert tick.currency == "USD"
    assert tick.day_volume == 27631112
    ev = tick.to_event()
    assert ev["source"] == "twelvedata"
    assert ev["transport"] == "websocket"
    assert ev["quality"] == "live"
    assert ev["latencyMs"] >= 0
    assert "price" not in ev or ev["price"] == tick.price


def test_parse_price_event_crypto_symbol_mapping():
    tick = streaming._parse_price_event(_price_msg(symbol="BTC/USD", price=65000))
    assert tick is not None
    assert tick.symbol == "BTC-USD"


def test_parse_price_event_rejects_malformed():
    assert streaming._parse_price_event(_price_msg(price="abc")) is None
    assert streaming._parse_price_event(_price_msg(price=-1)) is None
    assert streaming._parse_price_event(_price_msg(price=0)) is None
    assert streaming._parse_price_event(_price_msg(price=float("nan"))) is None
    assert streaming._parse_price_event(_price_msg(timestamp="not-a-number")) is None
    m = _price_msg()
    del m["timestamp"]
    assert streaming._parse_price_event(m) is None
    m = _price_msg()
    del m["symbol"]
    assert streaming._parse_price_event(m) is None
    assert streaming._parse_price_event(_price_msg(symbol="NOPE/ZZZ")) is None


def test_parse_price_event_optional_fields_absent():
    m = _price_msg()
    for k in ("day_volume", "bid", "ask"):
        m.pop(k, None)
    tick = streaming._parse_price_event(m)
    assert tick is not None
    assert tick.day_volume is None and tick.bid is None and tick.ask is None


# ---------------------------------------------------------------------------
# Manager policy (no upstream connection: no key configured)
# ---------------------------------------------------------------------------


def test_manager_unknown_symbols_and_cap(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_STREAM_MAX_SUBSCRIPTIONS", "2")
    mgr = streaming.StreamManager()
    mgr.register_client("c1")
    mgr.register_client("c2")
    granted, errors = mgr.acquire("c1", ["AAPL", "NVDA", "MSFT", "FAKE-SYM"])
    assert granted == ["AAPL", "NVDA"]  # priority order: AAPL before NVDA before MSFT
    assert errors["MSFT"] == "subscription_limit"
    assert errors["FAKE-SYM"] == "unknown_symbol"
    # Second client shares the budget; existing symbols are free.
    granted2, errors2 = mgr.acquire("c2", ["AAPL", "TSLA"])
    assert granted2 == ["AAPL"]
    assert errors2["TSLA"] == "subscription_limit"


def test_manager_refcount_release(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_STREAM_MAX_SUBSCRIPTIONS", "8")
    mgr = streaming.StreamManager()
    mgr.register_client("c1")
    mgr.register_client("c2")
    g1, _ = mgr.acquire("c1", ["AAPL"])
    g2, _ = mgr.acquire("c2", ["AAPL"])
    assert g1 == g2 == ["AAPL"]
    mgr.release("c1", ["AAPL"])
    assert mgr.current_symbols == ["AAPL"]  # c2 still holds it
    mgr.unregister_client("c2")
    assert mgr.current_symbols == []


def test_manager_frees_slots_after_release_and_supports_high_priority_eviction(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_STREAM_MAX_SUBSCRIPTIONS", "2")
    mgr = streaming.StreamManager()
    mgr.register_client("c1")
    mgr.register_client("c2")

    # Fill cap with 2 background symbols
    g1, _ = mgr.acquire("c1", ["AAPL", "NVDA"])
    assert set(g1) == {"AAPL", "NVDA"}

    # Releasing AAPL must actually free a slot (regression for refcount leak)
    mgr.release("c1", ["AAPL"])
    g2, err2 = mgr.acquire("c1", ["EURUSD"])
    assert g2 == ["EURUSD"]
    assert not err2

    # High-priority focus (e.g. viewing XAU/USD Asset page) evicts lowest-priority background symbol
    g3, err3 = mgr.acquire("c2", ["XAU/USD"], high_priority=True)
    assert g3 == ["XAU/USD"]
    assert not err3
    assert "XAU/USD" in mgr.current_symbols
    assert "NVDA" not in mgr.current_symbols  # evicted (lowest priority)


def test_manager_frees_slot_on_upstream_provider_rejected(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_STREAM_MAX_SUBSCRIPTIONS", "2")
    mgr = streaming.StreamManager()
    mgr.register_client("c1")
    g1, _ = mgr.acquire("c1", ["EURUSD", "GBPUSD"])
    assert set(g1) == {"EURUSD", "GBPUSD"}

    # Upstream rejects GBP/USD -> slot must be freed so another symbol can take it
    mgr._on_upstream_status("subscribe_status", {"raw": {"fails": [{"symbol": "GBP/USD"}]}})
    assert "GBPUSD" not in mgr.current_symbols
    g2, err2 = mgr.acquire("c1", ["XAU/USD"])
    assert g2 == ["XAU/USD"]
    assert not err2


# ---------------------------------------------------------------------------
# WS endpoint: auth + not-configured behaviour
# ---------------------------------------------------------------------------


def _get_ws_ticket(c, tok: str) -> str:
    r = c.post("/api/v1/auth/ws-ticket", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert "no-store" in r.headers.get("cache-control", "")
    ticket = r.json()["ticket"]
    assert isinstance(ticket, str) and len(ticket) >= 20
    return ticket


def test_ws_ticket_requires_auth(client):
    c, _ = client
    c.cookies.clear()
    r = c.post("/api/v1/auth/ws-ticket")
    assert r.status_code == 401


def test_ws_rejects_missing_token(client):
    c, _ = client
    with pytest.raises(Exception) as exc_info:
        with c.websocket_connect("/api/v1/market/stream") as ws:
            ws.receive_json()
    assert getattr(exc_info.value, "code", None) == 4401 or "4401" in str(exc_info.value)


def test_ws_rejects_legacy_jwt_query_param(client):
    """Long-lived access JWT in ?token= must never be accepted."""
    c, tok = client
    with pytest.raises(Exception):
        with c.websocket_connect(f"/api/v1/market/stream?token={tok}") as ws:
            ws.receive_json()


def test_ws_rejects_bad_ticket(client):
    c, _ = client
    with pytest.raises(Exception), c.websocket_connect(
        "/api/v1/market/stream",
        subprotocols=["btlab.v1", "ticket.not-a-valid-ticket"],
    ) as ws:
        ws.receive_json()


def test_ws_rejects_reused_ticket(client, monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    c, tok = client
    ticket = _get_ws_ticket(c, tok)
    with c.websocket_connect(
        "/api/v1/market/stream",
        subprotocols=["btlab.v1", f"ticket.{ticket}"],
    ) as ws:
        hello = ws.receive_json()
        assert hello["event"] == "connected"
    # Second use of the same ticket must fail.
    with pytest.raises(Exception), c.websocket_connect(
        "/api/v1/market/stream",
        subprotocols=["btlab.v1", f"ticket.{ticket}"],
    ) as ws:
        ws.receive_json()


def test_ws_rejects_expired_ticket(client, monkeypatch):
    c, tok = client
    monkeypatch.setattr(streaming, "WS_TICKET_TTL_S", 1)
    ticket = _get_ws_ticket(c, tok)
    # Advance monotonic clock past TTL.
    real_mono = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_mono() + 10.0)
    with pytest.raises(Exception), c.websocket_connect(
        "/api/v1/market/stream",
        subprotocols=["btlab.v1", f"ticket.{ticket}"],
    ) as ws:
        ws.receive_json()


def test_ws_concurrent_ticket_reuse():
    """Only one thread may consume a given ticket."""
    from concurrent.futures import ThreadPoolExecutor

    ticket, _ = streaming.issue_ws_ticket("user-concurrent")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: streaming.consume_ws_ticket(ticket), range(8)))
    assert results.count("user-concurrent") == 1
    assert results.count(None) == 7


def test_ws_accepts_query_ticket_fallback(client, monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    c, tok = client
    ticket = _get_ws_ticket(c, tok)
    with c.websocket_connect(f"/api/v1/market/stream?ticket={ticket}") as ws:
        hello = ws.receive_json()
        assert hello["event"] == "connected"


def test_ws_ticket_not_logged(client, monkeypatch, caplog):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    c, tok = client
    with caplog.at_level("DEBUG"):
        ticket = _get_ws_ticket(c, tok)
        with c.websocket_connect(
            "/api/v1/market/stream",
            subprotocols=["btlab.v1", f"ticket.{ticket}"],
        ) as ws:
            ws.receive_json()
    joined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert ticket not in joined
    assert tok not in joined


def test_ws_not_configured_reports_honestly(client, monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    c, tok = client
    ticket = _get_ws_ticket(c, tok)
    with c.websocket_connect(
        "/api/v1/market/stream",
        subprotocols=["btlab.v1", f"ticket.{ticket}"],
    ) as ws:
        hello = ws.receive_json()
        assert hello["event"] == "connected"
        assert hello["config"] == "not_configured"
        assert "apikey" not in json.dumps(hello)  # secret never leaks
        ws.send_json({"action": "subscribe", "symbols": ["AAPL"]})
        err = ws.receive_json()
        assert err["event"] == "subscription_error"
        assert err["errors"][0]["reason"] == "not_configured"
        ws.send_json({"action": "unsubscribe", "symbols": ["AAPL"]})
        resp = ws.receive_json()
        assert resp["event"] == "unsubscribed"
        ws.send_json({"action": "bogus"})
        resp = ws.receive_json()
        assert resp["event"] == "error"


# ---------------------------------------------------------------------------
# End-to-end through the app WS endpoint with a fake provider upstream
# ---------------------------------------------------------------------------


@pytest.fixture()
def loopback(monkeypatch):
    from conftest import _real_socket_connect as real_connect

    def allow_loopback(self, address, *args, **kwargs):
        if isinstance(address, tuple) and str(address[0]) in ("127.0.0.1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        if isinstance(address, str) and "127.0.0.1" in address:
            return real_connect(self, address, *args, **kwargs)
        raise OSError("blocked non-loopback")

    monkeypatch.setattr(socket.socket, "connect", allow_loopback)
    yield


def test_full_stream_pipeline_with_fake_provider(client, loopback, monkeypatch):
    """Fake Twelve Data WS server -> backend manager -> frontend WS client.

    Proves the forwarding path; this is NOT real-provider verification.
    """
    import websockets

    async def fake_provider(ws):
        subscribed: list[str] = []
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("action") == "subscribe":
                syms = msg["params"]["symbols"].split(",")
                subscribed.extend(syms)
                await ws.send(
                    json.dumps(
                        {
                            "event": "subscribe-status",
                            "status": "ok",
                            "success": [{"symbol": s, "exchange": "X", "type": "Common Stock"} for s in syms],
                            "fails": [],
                        }
                    )
                )
                for s in syms:
                    await ws.send(
                        json.dumps(
                            {
                                "event": "price",
                                "symbol": s,
                                "currency": "USD",
                                "exchange": "X",
                                "type": "Common Stock",
                                "timestamp": int(dt.datetime.now(dt.UTC).timestamp()),
                                "price": 123.45,
                                "day_volume": 1000,
                            }
                        )
                    )
            elif msg.get("action") == "unsubscribe":
                pass

    ready = threading.Event()
    port_holder: dict = {}

    def serve():
        async def main():
            server = await websockets.serve(fake_provider, "127.0.0.1", 0)
            port_holder["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            await server.wait_closed()

        asyncio.run(main())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(5), "fake provider did not start"

    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake-test-key-0000")
    monkeypatch.setenv("TWELVEDATA_WS_URL", f"ws://127.0.0.1:{port_holder['port']}/v1/quotes/price")
    monkeypatch.setenv("MARKET_STREAMING_ENABLED", "true")
    monkeypatch.setenv("MARKET_STREAM_MAX_SUBSCRIPTIONS", "2")

    # Fresh manager so env-driven config is picked up cleanly.
    streaming._manager = streaming.StreamManager()
    c, tok = client
    ticket = _get_ws_ticket(c, tok)
    try:
        with c.websocket_connect(
            "/api/v1/market/stream",
            subprotocols=["btlab.v1", f"ticket.{ticket}"],
        ) as ws:
            hello = ws.receive_json()
            assert hello["config"] == "configured"
            ws.send_json({"action": "subscribe", "symbols": ["AAPL", "NVDA", "MSFT"]})
            sub = None
            err = None
            deadline = time.time() + 8
            while time.time() < deadline and (sub is None or err is None):
                msg = ws.receive_json()
                if msg.get("event") == "subscribed":
                    sub = msg
                elif msg.get("event") == "subscription_error":
                    err = msg
            assert sub is not None, f"expected subscribed event, got {sub!r}/{err!r}"
            assert set(sub["symbols"]) == {"AAPL", "NVDA"}
            assert err is not None and err["errors"][0] == {"symbol": "MSFT", "reason": "subscription_limit"}
            # Upstream price events forwarded to the frontend socket.
            seen = set()
            deadline = time.time() + 8
            while time.time() < deadline and len(seen) < 2:
                msg = ws.receive_json()
                if msg.get("event") == "price":
                    seen.add(msg["symbol"])
                    assert msg["price"] == 123.45
                    assert msg["source"] == "twelvedata"
                    assert msg["quality"] == "live"
                    assert "apikey" not in json.dumps(msg)
            assert seen == {"AAPL", "NVDA"}, f"expected ticks for AAPL+NVDA, got {seen!r}"
    finally:
        streaming._manager = streaming.StreamManager()
