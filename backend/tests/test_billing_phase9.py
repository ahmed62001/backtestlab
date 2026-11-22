"""Tests for Phase 9 billing abstraction (disabled by default + Stripe test mode)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from app import billing
from app.main import create_app
from fastapi.testclient import TestClient


def _client():
    return TestClient(create_app(), raise_server_exceptions=False)


def _auth(c: TestClient, email: str = "billing-test@t.com") -> dict[str, str]:
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Bill User", "email": email, "password": "password123"},
    )
    if r.status_code == 409:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    tok = r.json()["token"]
    c.cookies.clear()
    return {"Authorization": f"Bearer {tok}"}


def test_billing_disabled_by_default():
    c = _client()
    h = _auth(c, "bill-disabled@t.com")
    plans = c.get("/api/v1/billing/plans")
    assert plans.status_code == 200
    assert plans.json()["enabled"] is False
    assert c.post("/api/v1/billing/checkout", headers=h).status_code == 501
    assert c.post("/api/v1/billing/portal", headers=h).status_code == 501
    assert c.post("/api/v1/billing/webhook", json={}).status_code == 503


def test_stripe_webhook_signature_idempotency_and_lifecycle(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_pro_test")

    c = _client()
    h = _auth(c, "bill-pro@t.com")
    me = c.get("/api/v1/auth/me", headers=h).json()
    uid = me["id"]
    assert me["plan"] == "free"

    # Mock Stripe Checkout API
    class FakeResp:
        status_code = 200

        def json(self):
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/pay/cs_test_123"}

    monkeypatch.setattr(billing.httpx, "post", lambda *a, **k: FakeResp())
    chk = c.post("/api/v1/billing/checkout", headers=h)
    assert chk.status_code == 200
    assert chk.json()["sessionId"] == "cs_test_123"

    # Invalid signature rejected
    bad_wh = c.post(
        "/api/v1/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "t=123,v1=bad"},
    )
    assert bad_wh.status_code == 400

    # Valid checkout.session.completed upgrades user to pro
    payload = json.dumps(
        {
            "id": "evt_test_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": uid,
                    "customer": "cus_test_1",
                    "subscription": "sub_test_1",
                }
            },
        }
    ).encode("utf-8")
    ts = int(time.time())
    sig = hmac.new(b"whsec_test_secret", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    sig_hdr = f"t={ts},v1={sig}"

    wh1 = c.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": sig_hdr})
    assert wh1.status_code == 200
    assert wh1.json()["deduped"] is False
    assert c.get("/api/v1/auth/me", headers=h).json()["plan"] == "pro"

    # Replay same event is idempotent
    wh2 = c.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": sig_hdr})
    assert wh2.status_code == 200
    assert wh2.json()["deduped"] is True

    # Subscription deleted downgrades back to free
    del_payload = json.dumps(
        {
            "id": "evt_test_2",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test_1", "customer": "cus_test_1", "status": "canceled"}},
        }
    ).encode("utf-8")
    del_sig = hmac.new(
        b"whsec_test_secret", f"{ts}.".encode() + del_payload, hashlib.sha256
    ).hexdigest()
    wh3 = c.post(
        "/api/v1/billing/webhook",
        content=del_payload,
        headers={"Stripe-Signature": f"t={ts},v1={del_sig}"},
    )
    assert wh3.status_code == 200
    assert c.get("/api/v1/auth/me", headers=h).json()["plan"] == "free"
