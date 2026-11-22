"""Shared provider cooldown state (anti-bot / rate-limit parking).

The state lives in the database so the API and worker processes agree. All
helpers are best-effort: a storage failure must never prevent a data fetch or
turn into a 500 — worse to lose a cooldown than to lose the request.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from sqlalchemy import delete

log = logging.getLogger("backtestlab.data_providers.cooldown")

DEFAULT_PROVIDER_COOLDOWN_S = float(os.environ.get("PROVIDER_COOLDOWN_S", "300"))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed


def cooldown_status(provider_id: str) -> dict[str, Any]:
    """Return ``{"active": bool, "retryAfter": int, "reason": str}``."""
    from ..db import ProviderState, SessionLocal, init_db

    try:
        init_db()
        s = SessionLocal()
        try:
            row = s.get(ProviderState, provider_id)
            until = _parse(row.cooldown_until) if row is not None else None
            if row is None or until is None or until <= _now():
                return {"active": False, "retryAfter": 0, "reason": ""}
            remaining = max(1, int((until - _now()).total_seconds()))
            return {
                "active": True,
                "retryAfter": remaining,
                "reason": str(row.reason or ""),
            }
        finally:
            s.close()
    except Exception as e:  # noqa: BLE001 - cooldown is advisory
        log.warning("could not read provider cooldown for %s: %s", provider_id, e)
        return {"active": False, "retryAfter": 0, "reason": ""}


def set_cooldown(provider_id: str, seconds: float, reason: str = "") -> int:
    """Park a provider for ``seconds``; returns the effective remaining time."""
    from ..db import ProviderState, SessionLocal, init_db

    seconds = max(0.0, float(seconds))
    if seconds <= 0:
        return 0
    until = _now() + dt.timedelta(seconds=seconds)
    try:
        init_db()
        s = SessionLocal()
        try:
            row = s.get(ProviderState, provider_id)
            if row is None:
                row = ProviderState(provider_id=provider_id)
                s.add(row)
            row.cooldown_until = until.isoformat()
            row.reason = str(reason)[:200]
            row.updated_at = _now().isoformat()
            s.commit()
        finally:
            s.close()
        return int(seconds)
    except Exception as e:  # noqa: BLE001 - cooldown is advisory
        log.warning("could not persist provider cooldown for %s: %s", provider_id, e)
        return 0


def clear_cooldown(provider_id: str) -> None:
    from ..db import ProviderState, SessionLocal, init_db

    try:
        init_db()
        s = SessionLocal()
        try:
            s.execute(delete(ProviderState).where(ProviderState.provider_id == provider_id))
            s.commit()
        finally:
            s.close()
    except Exception as e:  # noqa: BLE001
        log.warning("could not clear provider cooldown for %s: %s", provider_id, e)


def record_failure(provider_id: str, code: str, cooldown_s: float) -> int:
    """Apply the provider's cooldown when a failure signals abuse/shielding."""
    if code not in ("UPSTREAM_BLOCKED", "RATE_LIMITED"):
        return 0
    if cooldown_s <= 0:
        return 0
    return set_cooldown(provider_id, cooldown_s, reason=code)


def clear_provider_state() -> None:
    """Test/operator helper: drop all cooldown rows."""
    from ..db import ProviderState, SessionLocal, init_db

    try:
        init_db()
        s = SessionLocal()
        try:
            s.execute(delete(ProviderState))
            s.commit()
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "DEFAULT_PROVIDER_COOLDOWN_S",
    "clear_cooldown",
    "clear_provider_state",
    "cooldown_status",
    "record_failure",
    "set_cooldown",
]
