"""Stripe billing integration (disabled by default via BILLING_ENABLED=false).

Implements:
- Plan definitions (free, pro)
- Checkout Session & Customer Portal creation via Stripe REST API
- HMAC-SHA256 Stripe-Signature webhook verification with timestamp tolerance
- Idempotent webhook event processing (BillingEvent ledger)
- Subscription status synchronization (active/trialing -> pro; canceled -> free)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx
from sqlalchemy import select

from .db import BillingCustomer, BillingEvent, SessionLocal, User, init_db

log = logging.getLogger("backtestlab.billing")

PLANS: dict[str, dict[str, Any]] = {
    "free": {"id": "free", "name": "Free", "dailyLimit": 5, "priceMonthlyUsd": 0},
    "pro": {"id": "pro", "name": "Pro", "dailyLimit": 500, "priceMonthlyUsd": 29},
}


def billing_enabled() -> bool:
    return os.environ.get("BILLING_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _stripe_secret() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def _stripe_webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


def _pro_price_id() -> str:
    return os.environ.get("STRIPE_PRO_PRICE_ID", "").strip()


def is_stripe_configured() -> bool:
    return billing_enabled() and bool(_stripe_secret())


def verify_stripe_signature(payload: bytes, sig_header: str, secret: str, tolerance_s: int = 300) -> bool:
    """Verify Stripe-Signature header (t=<ts>,v1=<hmac_sha256>)."""
    if not sig_header or not secret:
        return False
    parts: dict[str, list[str]] = {}
    for item in sig_header.split(","):
        if "=" not in item:
            continue
        k, v = item.strip().split("=", 1)
        parts.setdefault(k, []).append(v)
    ts_list = parts.get("t") or []
    v1_list = parts.get("v1") or []
    if not ts_list or not v1_list:
        return False
    try:
        ts = int(ts_list[0])
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > tolerance_s:
        return False
    signed_payload = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in v1_list)


def create_checkout_session(user: User, success_url: str, cancel_url: str) -> dict[str, Any]:
    """Create a Stripe Checkout Session for the Pro plan."""
    secret = _stripe_secret()
    price_id = _pro_price_id()
    if not secret or not price_id:
        raise RuntimeError("BILLING_NOT_CONFIGURED")
    form = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": user.id,
        "customer_email": user.email,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "metadata[user_id]": user.id,
    }
    resp = httpx.post(
        "https://api.stripe.com/v1/checkout/sessions",
        headers={"Authorization": f"Bearer {secret}"},
        data=form,
        timeout=10.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"STRIPE_ERROR:{resp.status_code}")
    data = resp.json()
    return {"sessionId": data.get("id", ""), "url": data.get("url", "")}


def create_portal_session(user: User, return_url: str) -> dict[str, Any]:
    """Create a Stripe Billing Portal session for an existing customer."""
    secret = _stripe_secret()
    if not secret:
        raise RuntimeError("BILLING_NOT_CONFIGURED")
    init_db()
    s = SessionLocal()
    try:
        bc = s.get(BillingCustomer, user.id)
        if bc is None or not bc.customer_id:
            raise LookupError("NO_BILLING_CUSTOMER")
        cid = bc.customer_id
    finally:
        s.close()
    resp = httpx.post(
        "https://api.stripe.com/v1/billing_portal/sessions",
        headers={"Authorization": f"Bearer {secret}"},
        data={"customer": cid, "return_url": return_url},
        timeout=10.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"STRIPE_ERROR:{resp.status_code}")
    return {"url": resp.json().get("url", "")}


def process_stripe_webhook(raw_body: bytes, sig_header: str) -> dict[str, Any]:
    """Verify signature, deduplicate by event_id, and sync subscription status."""
    secret = _stripe_webhook_secret()
    if not secret:
        raise RuntimeError("BILLING_NOT_CONFIGURED")
    if not verify_stripe_signature(raw_body, sig_header, secret):
        raise PermissionError("INVALID_SIGNATURE")

    event = json.loads(raw_body.decode("utf-8"))
    event_id = str(event.get("id", "")).strip()
    event_type = str(event.get("type", "")).strip()
    if not event_id:
        raise ValueError("MISSING_EVENT_ID")

    init_db()
    s = SessionLocal()
    try:
        if s.get(BillingEvent, event_id) is not None:
            return {"received": True, "deduped": True, "eventId": event_id}

        obj = (event.get("data") or {}).get("object") or {}
        now_iso = dt.datetime.now(dt.UTC).isoformat()

        if event_type == "checkout.session.completed":
            uid = str(obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id") or "")
            cid = str(obj.get("customer") or "")
            sid = str(obj.get("subscription") or "")
            if uid:
                _upsert_subscription(s, uid, cid, sid, plan="pro", status="active", now_iso=now_iso)
        elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
            cid = str(obj.get("customer") or "")
            sid = str(obj.get("id") or "")
            status = str(obj.get("status") or ("canceled" if event_type.endswith("deleted") else "active"))
            cancel_end = bool(obj.get("cancel_at_period_end", False))
            period_end = str(obj.get("current_period_end") or "")
            plan = "pro" if status in ("active", "trialing", "past_due") else "free"
            bc = None
            if sid:
                bc = s.scalar(select(BillingCustomer).where(BillingCustomer.subscription_id == sid))
            if bc is None and cid:
                bc = s.scalar(select(BillingCustomer).where(BillingCustomer.customer_id == cid))
            if bc is not None:
                _upsert_subscription(
                    s,
                    bc.user_id,
                    cid or bc.customer_id,
                    sid or bc.subscription_id,
                    plan=plan,
                    status=status,
                    current_period_end=period_end,
                    cancel_at_period_end=cancel_end,
                    now_iso=now_iso,
                )

        s.add(BillingEvent(event_id=event_id, event_type=event_type, processed_at=now_iso))
        s.commit()
        return {"received": True, "deduped": False, "eventId": event_id, "type": event_type}
    finally:
        s.close()


def _upsert_subscription(
    s,
    user_id: str,
    customer_id: str,
    subscription_id: str,
    *,
    plan: str,
    status: str,
    current_period_end: str = "",
    cancel_at_period_end: bool = False,
    now_iso: str = "",
) -> None:
    bc = s.get(BillingCustomer, user_id)
    if bc is None:
        bc = BillingCustomer(user_id=user_id)
        s.add(bc)
    bc.customer_id = customer_id
    bc.subscription_id = subscription_id
    bc.plan = plan
    bc.status = status
    bc.current_period_end = current_period_end
    bc.cancel_at_period_end = cancel_at_period_end
    bc.updated_at = now_iso
    u = s.get(User, user_id)
    if u is not None:
        u.plan = plan
