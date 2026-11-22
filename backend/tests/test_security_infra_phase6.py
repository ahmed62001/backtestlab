"""Tests for HttpOnly cookies, CSRF protection, Redis shared state, email reset, and async default."""

from __future__ import annotations

from unittest.mock import MagicMock

from app import email_service, redis_store
from app.main import create_app
from fastapi.testclient import TestClient


def _client():
    return TestClient(create_app(), raise_server_exceptions=False)


def test_httponly_cookies_and_csrf_protection():
    c = _client()
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Cookie User", "email": "cookie-sec@t.com", "password": "password123"},
    )
    if r.status_code == 409:
        r = c.post(
            "/api/v1/auth/login",
            json={"email": "cookie-sec@t.com", "password": "password123"},
        )
    assert r.status_code in (200, 201), r.text
    assert "btlab_access" in c.cookies
    assert "btlab_csrf" in c.cookies
    csrf = c.cookies.get("btlab_csrf")

    # Cookie-authenticated GET works without CSRF header
    me = c.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "cookie-sec@t.com"

    # Cookie-authenticated POST without X-CSRF-Token is rejected with 403 CSRF_FAILED
    bad_post = c.post(
        "/api/v1/backtests",
        json={"templateId": "buy-hold", "asset": "AAPL", "initialCapital": 10000},
    )
    assert bad_post.status_code == 403
    assert bad_post.json()["code"] == "CSRF_FAILED"

    # Cookie-authenticated POST WITH X-CSRF-Token succeeds
    good_post = c.post(
        "/api/v1/backtests",
        json={"templateId": "buy-hold", "asset": "AAPL", "initialCapital": 10000},
        headers={"X-CSRF-Token": csrf},
    )
    assert good_post.status_code == 201, good_post.text

    # Logout clears cookies (with CSRF header)
    out = c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401


def test_email_password_reset_flow(monkeypatch):
    sent: list[dict] = []

    def fake_send(*, to_email: str, subject: str, text_body: str, html_body: str | None = None):
        sent.append({"to": to_email, "subject": subject, "text": text_body})
        return True

    monkeypatch.setattr(email_service, "send_email", fake_send)

    c = _client()
    c.post(
        "/api/v1/auth/register",
        json={"name": "Reset User", "email": "reset-mail@t.com", "password": "password123"},
    )
    # Unknown email returns generic 200 and sends nothing
    r_unk = c.post("/api/v1/auth/forgot", json={"email": "nobody-exists@t.com"})
    assert r_unk.status_code == 200
    assert r_unk.json() == {"ok": True}
    assert len(sent) == 0

    # Known email returns generic 200 and dispatches reset link with token
    r_ok = c.post("/api/v1/auth/forgot", json={"email": "reset-mail@t.com"})
    assert r_ok.status_code == 200
    assert r_ok.json() == {"ok": True}
    assert len(sent) == 1
    assert "token=" in sent[0]["text"]
    token = sent[0]["text"].split("token=")[1].splitlines()[0].strip()

    # Reset password with token
    r_reset = c.post(
        "/api/v1/auth/reset",
        json={"token": token, "password": "newpassword456"},
    )
    assert r_reset.status_code == 200

    # Token is single-use
    r_replay = c.post(
        "/api/v1/auth/reset",
        json={"token": token, "password": "anotherpassword"},
    )
    assert r_replay.status_code == 422

    # Login works with new password
    r_login = c.post(
        "/api/v1/auth/login",
        json={"email": "reset-mail@t.com", "password": "newpassword456"},
    )
    assert r_login.status_code == 200


def test_redis_shared_ws_ticket_and_rate_limit(monkeypatch):
    store: dict[str, str] = {}
    counters: dict[str, int] = {}

    fake = MagicMock()
    fake.ping.return_value = True

    def fake_set(k, v, ex=None):
        store[k] = v
        return True

    def fake_getdel(k):
        return store.pop(k, None)

    def fake_eval(script, numkeys, key, window):
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    fake.set.side_effect = fake_set
    fake.getdel.side_effect = fake_getdel
    fake.eval.side_effect = fake_eval

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis_store, "get_redis", lambda: fake)

    from app.streaming import consume_ws_ticket, issue_ws_ticket

    ticket, ttl = issue_ws_ticket("u-123")
    assert ttl > 0
    assert consume_ws_ticket(ticket) == "u-123"
    # Replay rejected
    assert consume_ws_ticket(ticket) is None

    # Rate limit via Redis
    assert redis_store.redis_rate_limit("k1", 2, 60) is True
    assert redis_store.redis_rate_limit("k1", 2, 60) is True
    assert redis_store.redis_rate_limit("k1", 2, 60) is False

    h = redis_store.redis_health()
    assert h["configured"] is True
    assert h["status"] == "ok"


def test_async_default_env_and_external_worker_mode(monkeypatch):
    monkeypatch.setenv("ASYNC_BACKTESTS_DEFAULT", "1")
    monkeypatch.setenv("QUEUE_INPROCESS_WORKER", "0")

    c = _client()
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Async User", "email": "async-def@t.com", "password": "password123"},
    )
    if r.status_code == 409:
        r = c.post(
            "/api/v1/auth/login",
            json={"email": "async-def@t.com", "password": "password123"},
        )
    tok = r.json()["token"]
    # Clear cookies so we test Bearer cleanly
    c.cookies.clear()

    # Default POST creates a queued job without spawning in-process thread
    rb = c.post(
        "/api/v1/backtests",
        json={"templateId": "buy-hold", "asset": "AAPL", "initialCapital": 10000},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert rb.status_code == 201, rb.text
    body = rb.json()
    assert "jobId" in body
    assert body["status"] == "queued"

    # Explicit ?async=false runs synchronously
    rb_sync = c.post(
        "/api/v1/backtests?async=false",
        json={"templateId": "buy-hold", "asset": "AAPL", "initialCapital": 10000},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert rb_sync.status_code == 201, rb_sync.text
    assert "totalReturnPct" in rb_sync.json()
