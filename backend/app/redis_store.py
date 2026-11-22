"""Shared Redis state for multi-worker API deployments.

Provides atomic, cross-worker primitives for:
- Single-use WebSocket ticket storage & consumption (GETDEL)
- Distributed sliding/fixed-window rate limiting (Lua INCR+EXPIRE)
- Health / readiness checks

When ``REDIS_URL`` is unset (dev / SQLite test runs), helpers return ``None``
so callers can use their bounded in-process fallback. When ``REDIS_URL`` IS
configured (or in production where Redis is required), errors fail closed
rather than silently degrading to a weaker per-process state.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger("backtestlab.redis")

_lock = threading.Lock()
_client: Any = None
_client_url: str | None = None

_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return current
"""


class RedisUnavailableError(RuntimeError):
    """Raised when Redis is configured/required but unreachable."""


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "").strip()


def is_redis_configured() -> bool:
    return bool(redis_url())


def get_redis():
    """Return a cached ``redis.Redis`` client, or ``None`` if ``REDIS_URL`` is unset."""
    global _client, _client_url
    url = redis_url()
    if not url:
        return None
    with _lock:
        if _client is not None and _client_url == url:
            return _client
        import redis  # type: ignore[import-not-found]

        _client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            retry_on_timeout=True,
        )
        _client_url = url
        return _client


def reset_redis_client() -> None:
    """Clear cached client (for tests)."""
    global _client, _client_url
    with _lock:
        _client = None
        _client_url = None


def store_ws_ticket(digest: str, user_id: str, ttl_s: int) -> bool:
    """Store a hashed WS ticket in Redis. Returns False if Redis is not configured."""
    client = get_redis()
    if client is None:
        return False
    try:
        client.set(f"btlab:ws_ticket:{digest}", user_id, ex=max(1, int(ttl_s)))
        return True
    except Exception as exc:
        log.error("redis store_ws_ticket failed: %s", exc)
        raise RedisUnavailableError("Redis unavailable for WS ticket issuance") from exc


def consume_ws_ticket_redis(digest: str) -> tuple[bool, str | None]:
    """Atomically consume a WS ticket from Redis.

    Returns ``(handled_by_redis, user_id_or_None)``.
    """
    client = get_redis()
    if client is None:
        return False, None
    try:
        uid = client.getdel(f"btlab:ws_ticket:{digest}")
        return True, (str(uid) if uid else None)
    except Exception as exc:
        log.error("redis consume_ws_ticket failed: %s", exc)
        # Fail closed: never accept a ticket when Redis is down
        return True, None


def redis_rate_limit(key: str, limit: int, window_s: int = 60) -> bool | None:
    """Atomic distributed rate limit check.

    Returns ``True`` if allowed, ``False`` if exceeded, or ``None`` when
    ``REDIS_URL`` is not configured (caller uses local fallback).
    In production, Redis errors fail closed (returns ``False``).
    """
    client = get_redis()
    if client is None:
        return None
    try:
        count = int(client.eval(_RATE_LIMIT_LUA, 1, f"btlab:rl:{key}", int(window_s)))
        return count <= limit
    except Exception as exc:
        log.error("redis rate_limit failed: %s", exc)
        if os.environ.get("ENV", "dev") == "production":
            return False
        return None


def redis_health() -> dict[str, Any]:
    """Return Redis health status for /ready."""
    if not is_redis_configured():
        return {"configured": False, "status": "not_configured"}
    try:
        client = get_redis()
        if client is not None and client.ping():
            return {"configured": True, "status": "ok"}
        return {"configured": True, "status": "error", "detail": "ping returned false"}
    except Exception as exc:
        return {"configured": True, "status": "error", "detail": type(exc).__name__}
