"""Shared client-IP resolution for rate limiters.

Forwarded headers are trusted **only** when ``TRUST_PROXY_HEADERS=1`` is set by
the operator (the production compose file does this and keeps the API port off
the public interface). Nginx sets ``X-Real-IP`` to the direct peer address, which
a browser cannot spoof; ``X-Forwarded-For`` is only used as a fallback. With the
flag unset, a spoofed header can never influence a limiter key.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping


def valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except (TypeError, ValueError):
        return None


def client_ip_from(
    peer: str | None,
    headers: Mapping[str, str],
    trust_proxy: bool | None = None,
) -> str:
    """Resolve the limiter key from the peer address and (trusted) headers."""
    if trust_proxy is None:
        trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "0") == "1"
    fallback = peer or "?"
    if not trust_proxy:
        return fallback
    real = valid_ip(headers.get("x-real-ip", ""))
    if real:
        return real
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        first = valid_ip(forwarded.split(",")[0])
        if first:
            return first
    return fallback
