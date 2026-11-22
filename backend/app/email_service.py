"""Configurable email delivery abstraction for password recovery and notifications.

Supports:
- ``none`` (default when unconfigured): no-op, logs non-sensitive delivery event
- ``smtp``: standard SMTP / STARTTLS using ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``, ``SMTP_FROM``
- ``resend``: Resend HTTP API using ``RESEND_API_KEY`` and ``EMAIL_FROM``

Never logs raw reset tokens or credentials.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

log = logging.getLogger("backtestlab.email")


def email_provider_name() -> str:
    return os.environ.get("EMAIL_PROVIDER", "none").strip().lower() or "none"


def app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:5173").rstrip("/")


def is_email_configured() -> bool:
    prov = email_provider_name()
    if prov == "smtp":
        return bool(os.environ.get("SMTP_HOST", "").strip())
    if prov == "resend":
        return bool(os.environ.get("RESEND_API_KEY", "").strip())
    return False


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    """Send an email via the configured provider. Returns True if sent, False if disabled/failed."""
    prov = email_provider_name()
    if prov == "none":
        log.info("email delivery skipped (EMAIL_PROVIDER=none)", extra={"to": to_email, "subject": subject})
        return False

    from_addr = os.environ.get("EMAIL_FROM", os.environ.get("SMTP_FROM", "noreply@backtestlab.local"))

    if prov == "smtp":
        host = os.environ.get("SMTP_HOST", "").strip()
        if not host:
            log.warning("SMTP_HOST not configured; skipping email")
            return False
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        use_tls = os.environ.get("SMTP_STARTTLS", "1") not in ("0", "false", "False")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_email
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        try:
            with smtplib.SMTP(host, port, timeout=10) as srv:
                if use_tls:
                    srv.starttls()
                if user:
                    srv.login(user, password)
                srv.send_message(msg)
            log.info("email sent via smtp", extra={"subject": subject})
            return True
        except Exception as exc:
            log.error("smtp send failed: %s", type(exc).__name__)
            return False

    if prov == "resend":
        api_key = os.environ.get("RESEND_API_KEY", "").strip()
        if not api_key:
            log.warning("RESEND_API_KEY not configured; skipping email")
            return False
        payload: dict[str, Any] = {
            "from": from_addr,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
        }
        if html_body:
            payload["html"] = html_body
        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=10.0,
            )
            if 200 <= resp.status_code < 300:
                log.info("email sent via resend", extra={"subject": subject})
                return True
            log.error("resend API returned %s", resp.status_code)
            return False
        except Exception as exc:
            log.error("resend send failed: %s", type(exc).__name__)
            return False

    log.warning("unknown EMAIL_PROVIDER=%r", prov)
    return False


def send_password_reset_email(*, to_email: str, token: str) -> bool:
    """Send password reset instructions without logging the raw token."""
    reset_url = f"{app_base_url()}/reset?token={token}"
    subject = "BacktestLab — Password Reset"
    text_body = (
        "You requested a password reset for your BacktestLab account.\n\n"
        f"Reset link (valid for 30 minutes, single use):\n{reset_url}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    html_body = (
        "<p>You requested a password reset for your BacktestLab account.</p>"
        f'<p><a href="{reset_url}">Reset your password</a> (valid for 30 minutes, single use).</p>'
        "<p>If you did not request this, you can safely ignore this email.</p>"
    )
    return send_email(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
