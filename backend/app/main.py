"""BacktestLab backend: FastAPI service + deterministic engine + SQLite store."""

from __future__ import annotations

import datetime as dt
import functools
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import market as market_router
from . import streaming as streaming_router
from .adapter import (
    EngineRejectedError,
    VendorUnavailableError,
    vendor_available,
)
from .auth import (
    SECRET,
    consume_password_reset,
    current_user,
    hash_pw,
    issue_password_reset,
    issue_refresh_token,
    make_token,
    revoke_refresh_tokens,
    rotate_refresh_token,
)
from .data import quality_guards
from .data_providers import ProviderError, fetch_bars, provider_infos
from .data_providers.base import (
    ERR_BAD_INPUT,
    ERR_DATA_NOT_IN_STORE,
    ERR_EMPTY_DATA,
    ERR_NO_DATA,
    ERR_RATE_LIMITED,
    ERR_UNKNOWN_SYMBOL,
    http_status_for_code,
)
from .data_providers.registry import all_provider_ids, enabled_ids
from .db import (
    Backtest,
    Job,
    MarketInstrument,
    PasswordReset,
    RefreshToken,
    SessionLocal,
    Usage,
    User,
    engine,
    init_db,
    today_key,
)
from .engine import DISCLAIMER, ENGINE_MODE, TEMPLATES, engine_block
from .instruments import asset_catalog, get_instrument, is_backtest_eligible
from .middleware import RequestContextMiddleware
from .netutil import client_ip_from, valid_ip
from .observability import (
    configure_logging,
    get_request_id,
    redact,
    render_metrics,
)
from .observability import (
    inc as metric_inc,
)
from .pipeline import run_and_normalize
from .spot_engine import INTRADAY_INTERVALS, SUPPORTED_BACKTEST_INTERVALS, normalize_interval
from .synthetic_engine import run_backtest as _synthetic_run

configure_logging()
log = logging.getLogger("backtestlab")

BANNED = [
    "buy now",
    "sell now",
    "guaranteed",
    "sure profit",
    "risk-free",
    "will earn",
    "\u0627\u0634\u062a\u0631 \u0627\u0644\u0622\u0646",
    "\u0631\u0628\u062d \u0645\u0636\u0645\u0648\u0646",
    "\u0628\u062f\u0648\u0646 \u0645\u062e\u0627\u0637\u0631",
]
FREE_LIMIT = int(os.environ.get("DAILY_RUN_LIMIT_FREE", "3"))
# No payment provider is wired. Keep the whole billing surface explicitly
# disabled (501 + stable code) instead of returning misleading success, and
# expose the capability so the UI can hide/disable checkout.
BILLING_ENABLED = os.environ.get("BILLING_ENABLED", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Phase 10: API pagination + bounded payloads.
DEFAULT_PAGE_SIZE = int(os.environ.get("API_DEFAULT_PAGE_SIZE", "50"))
MAX_PAGE_SIZE = int(os.environ.get("API_MAX_PAGE_SIZE", "200"))
API_MAX_EQUITY_POINTS = int(os.environ.get("API_MAX_EQUITY_POINTS", "1000"))
API_MAX_TRADE_ROWS = int(os.environ.get("API_MAX_TRADE_ROWS", "500"))
API_MAX_COMPARE_IDS = int(os.environ.get("API_MAX_COMPARE_IDS", "10"))

# Some clients poll an OpenAI-style /v1/models endpoint that this service does
# not expose (observed every 30s from a container bridge address). Logging each
# 404 at full rate floods the access log without identifying the caller, so an
# unmatched probe is logged at most once per interval with its client/User-Agent.
_UNMATCHED_PROBE_PATHS = frozenset({"/v1/models", "/models", "/api/v1/models"})
_PROBE_LOG_INTERVAL_S = float(os.environ.get("PROBE_LOG_INTERVAL_S", "300"))
_probe_log_lock = threading.Lock()
_probe_last_logged: dict[tuple[str, str], float] = {}


def _log_unmatched_probe(request: Request, request_id: str, path: str) -> None:
    client = request.client.host if request.client else "?"
    key = (client, path)
    now = time.monotonic()
    with _probe_log_lock:
        last = _probe_last_logged.get(key, 0.0)
        if now - last < _PROBE_LOG_INTERVAL_S:
            return
        _probe_last_logged[key] = now
    log.warning(
        "unmatched client probe",
        extra={
            "method": request.method,
            "path": path,
            "status": 404,
            "client": client,
            "user_agent": redact(request.headers.get("user-agent", ""))[:160],
            "query": redact(str(request.url.query))[:200],
            "request_id": request_id,
        },
    )
    metric_inc(
        "backtestlab_unmatched_probe_total",
        method=request.method,
        path=path,
    )


class Register(BaseModel):
    name: str
    email: str
    password: str


class Login(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


PRO_LIMIT = int(os.environ.get("DAILY_RUN_LIMIT_PRO", "100"))


def redact_url_keys(msg: str) -> str:
    """Strip API keys/tokens from URLs or raw error strings before returning to caller."""
    return redact(msg)


def _valid_ip(value: str) -> str | None:
    return valid_ip(value)


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting (shared resolver)."""
    return client_ip_from(
        request.client.host if request.client else "?",
        {k.lower(): v for k, v in request.headers.items()},
    )


# Provider outcomes that describe the *request* (bad symbol/range or a source
# with no bars for that window), not a missing resource. They must answer 422
# so clients never confuse them with a missing backtest/job (404) or a
# transient upstream outage (502/503).
_PROVIDER_VALIDATION_CODES = frozenset(
    {
        ERR_BAD_INPUT,
        ERR_UNKNOWN_SYMBOL,
        ERR_DATA_NOT_IN_STORE,
        ERR_EMPTY_DATA,
        ERR_NO_DATA,
    }
)

# Only these provider-supplied keys may leave the service in an error payload.
_SAFE_PROVIDER_DETAIL_KEYS = ("provider", "symbol", "start", "end", "retryAfter")


def _provider_http_exception(e: ProviderError) -> HTTPException:
    """Translate a ProviderError into a stable HTTP response.

    ``detail`` keeps the machine code and message (which always names the
    provider) plus a small, non-secret context block. Transient upstream
    failures keep their 502/503 mapping and a Retry-After hint when supplied.
    """
    status = http_status_for_code(e.code)
    if e.code in _PROVIDER_VALIDATION_CODES:
        status = 422
    detail: dict[str, Any] = {
        "code": e.code,
        "message": str(e),
        "provider": e.provider,
    }
    for key in ("symbol", "start", "end"):
        value = e.details.get(key)
        if value:
            detail[key] = value
    headers: dict[str, str] | None = None
    if e.retry_after is not None:
        retry = max(0, int(e.retry_after))
        detail["retryAfter"] = retry
        headers = {"Retry-After": str(retry)}
    return HTTPException(status, detail=detail, headers=headers)


def _bounded_backtest(fn):
    """Bound synchronous backtest runs to ``QUEUE_MAX_WORKERS`` slots.

    Async/idempotent submissions are bounded inside ``queue.submit_job``; this
    decorator covers the synchronous (default) path so a burst of CPU-heavy
    runs cannot create unbounded concurrent work.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if request is None:
            request = next((a for a in args if isinstance(a, Request)), None)
        async_mode = bool(
            request is not None
            and (
                request.query_params.get("async", "") == "true"
                or request.headers.get("idempotency-key", "")
            )
        )
        if async_mode:
            return fn(*args, **kwargs)
        from .queue import acquire_slot, release_slot

        try:
            acquire_slot()
        except RuntimeError as e:
            raise HTTPException(503, detail={"code": "SERVER_BUSY", "message": str(e)}) from e
        try:
            return fn(*args, **kwargs)
        finally:
            release_slot()

    return wrapper


MAX_REQUEST_BODY_BYTES = 1_000_000
# The documented CSV limit is 5 MiB; JSON string escaping (quotes/newlines)
# adds a small amount on the wire, so this path gets a bounded envelope.
MAX_CSV_REQUEST_BODY_BYTES = 6_000_000
CSV_UPLOAD_PATH = "/api/v1/data-providers/csv-upload"


class BodySizeLimitMiddleware:
    """ASGI body guard that counts the *actual* bytes, not Content-Length.

    This closes the chunked-transfer bypass and turns a non-numeric
    Content-Length into a 400 instead of a 500. The bounded body is replayed to
    the application exactly once.
    """

    def __init__(
        self,
        app,
        max_bytes: int = MAX_REQUEST_BODY_BYTES,
        upload_max_bytes: int = MAX_CSV_REQUEST_BODY_BYTES,
        upload_path: str = CSV_UPLOAD_PATH,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes
        self.upload_path = upload_path

    async def _reject(self, send, status: int, code: str, message: str, rid: str) -> None:
        body = json.dumps(
            {"code": code, "message": message, "details": [], "requestId": rid}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        rid_raw = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = rid_raw if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", rid_raw or "") else uuid.uuid4().hex
        limit = self.upload_max_bytes if scope.get("path") == self.upload_path else self.max_bytes

        raw_len = headers.get(b"content-length")
        if raw_len is not None:
            try:
                declared = int(raw_len)
            except (TypeError, ValueError):
                await self._reject(send, 400, "BAD_REQUEST", "Invalid Content-Length", rid)
                return
            if declared < 0:
                await self._reject(send, 400, "BAD_REQUEST", "Invalid Content-Length", rid)
                return
            if declared > limit:
                await self._reject(send, 413, "PAYLOAD_TOO_LARGE", "Body over limit", rid)
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                await self._reject(send, 400, "BAD_REQUEST", "Invalid request body", rid)
                return
            chunk = message.get("body", b"") or b""
            total += len(chunk)
            if total > limit:
                await self._reject(send, 413, "PAYLOAD_TOO_LARGE", "Body over limit", rid)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)


def err(code: str, message: str, status: int, request_id: str = "") -> JSONResponse:
    rid = request_id or get_request_id() or "-"
    return JSONResponse(
        {"code": code, "message": redact_url_keys(message), "details": [], "requestId": rid},
        status_code=status,
    )


def user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "plan": u.plan,
        "language": u.language,
        "createdAt": u.created_at,
    }


def summary(b: Backtest) -> dict:
    cfg = json.loads(b.config_json or "{}")
    return {
        "id": b.id,
        "name": b.name,
        "templateId": b.template_id,
        "asset": b.asset,
        "status": b.status,
        "createdAt": b.created_at,
        "totalReturnPct": b.total_return_pct,
        "maxDrawdownPct": b.max_drawdown_pct,
        "sharpe": b.sharpe,
        "winRatePct": b.win_rate_pct,
        "trades": b.trades,
        "vsBuyHoldPct": b.vs_buy_hold_pct,
        "dataProvider": getattr(b, "data_provider", "") or "",
        "config": cfg,
    }


def _page_args(
    limit: int, offset: int, default: int = DEFAULT_PAGE_SIZE, maximum: int = MAX_PAGE_SIZE
) -> tuple[int, int]:
    """Clamp client pagination input to a safe, bounded window."""
    try:
        limit_i = int(limit)
    except (TypeError, ValueError):
        limit_i = default
    try:
        offset_i = int(offset)
    except (TypeError, ValueError):
        offset_i = 0
    if limit_i <= 0:
        limit_i = default
    return max(1, min(limit_i, maximum)), max(0, offset_i)


def _downsample(items: list, maximum: int) -> tuple[list, bool]:
    """Evenly downsample a list to *maximum* points, keeping first and last."""
    n = len(items)
    if maximum <= 0 or n <= maximum:
        return items, False
    if maximum == 1:
        return [items[-1]], True
    step = (n - 1) / (maximum - 1)
    indexes = sorted({round(i * step) for i in range(maximum)})
    indexes[0], indexes[-1] = 0, n - 1
    return [items[i] for i in indexes], True


def full(b: Backtest) -> dict:
    d = summary(b)
    try:
        r = json.loads(b.result_json or "{}")
    except Exception:  # noqa: BLE001
        r = {}
    eng = r.get("engine", {})
    if not isinstance(eng, dict):
        # legacy stored string engine -> never mislabel; keep it visible
        eng = {
            "mode": "unknown",
            "engineName": str(eng) if eng else "-",
            "vendorCommit": None,
            "vendorVersionOrRef": None,
        }
    equity_all = r.get("equity", []) or []
    trades_all = r.get("tradesList", []) or []
    equity, eq_sampled = _downsample(list(equity_all), API_MAX_EQUITY_POINTS)
    trades_truncated = len(trades_all) > API_MAX_TRADE_ROWS
    trades = list(trades_all[-API_MAX_TRADE_ROWS:]) if trades_truncated else list(trades_all)
    d.update(
        {
            "equity": equity,
            "monthly": r.get("monthly", []),
            "tradesList": trades,
            "overfitting": r.get("overfitting", False),
            "disclaimer": r.get("disclaimer", DISCLAIMER),
            "warnings": r.get("warnings", []),
            "costs": r.get("costs", {}),
            "provenance": r.get("provenance", {}),
            "engine": eng,
            "resultMeta": {
                "equityTotalPoints": len(equity_all),
                "equityReturned": len(equity),
                "equityDownsampled": eq_sampled,
                "tradesTotal": len(trades_all),
                "tradesReturned": len(trades),
                "tradesTruncated": trades_truncated,
            },
        }
    )
    return d


_INTERVALS = SUPPORTED_BACKTEST_INTERVALS
_MIN_DATE = dt.date(2015, 1, 1)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _param_specs(template_id: str) -> dict[str, dict[str, Any]]:
    spec = next((t for t in TEMPLATES if t["id"] == template_id), None)
    if spec is None:
        return {}
    return {p["key"]: p for p in spec.get("paramSpecs", [])}


def _validate_params(template_id: str, params: dict[str, Any]) -> None:
    """Validate template params against the advertised paramSpecs.

    Rejects unknown keys, non-numeric/non-finite values, type mismatches and
    out-of-range values with 422 before any provider call or quota use.
    """
    specs = _param_specs(template_id)
    for key, value in params.items():
        spec = specs.get(key)
        if spec is None:
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": f"Unknown param {key!r}"},
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": f"Param {key!r} must be a number"},
            )
        if not math.isfinite(float(value)):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": f"Param {key!r} must be finite"},
            )
        if float(value) < float(spec["min"]) or float(value) > float(spec["max"]):
            raise HTTPException(
                422,
                detail={
                    "code": "BAD_INPUT",
                    "message": f"Param {key!r} must be between {spec['min']} and {spec['max']}",
                },
            )
        # Integer-stepped specs must not receive fractional values.
        if float(spec.get("step", 1)) == 1 and float(value) != int(float(value)):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": f"Param {key!r} must be an integer"},
            )


def _validate_backtest_input(body: dict[str, Any]) -> None:
    """Strict validation for backtest creation input. Raises HTTPException(422)."""
    # templateId
    tids = [t["id"] for t in TEMPLATES]
    template_id = body.get("templateId", "ma-crossover")
    if template_id not in tids:
        raise HTTPException(422, detail={"code": "UNKNOWN_TEMPLATE", "message": "Unknown template"})
    # leverage / short (spot only). Booleans are not valid numbers here: JSON
    # `true` compares equal to 1 in Python and must not pass as leverage.
    lev = body.get("leverage", 1)
    if isinstance(lev, bool) or not isinstance(lev, (int, float)) or lev != 1:
        raise HTTPException(
            422, detail={"code": "LEVERAGE_NOT_ALLOWED", "message": "Spot only, leverage 1"}
        )
    short = body.get("short", False)
    if not isinstance(short, bool) or short:
        raise HTTPException(
            422, detail={"code": "LEVERAGE_NOT_ALLOWED", "message": "Spot only, leverage 1"}
        )
    # asset (must be a registered, backtest-eligible instrument)
    requested_asset = str(body.get("asset", "")).strip().upper()
    asset = requested_asset
    if not asset:
        raise HTTPException(
            422, detail={"code": "UNKNOWN_ASSET", "message": "Unknown asset: (empty)"}
        )
    inst = get_instrument(asset)
    if inst is None:
        raise HTTPException(
            422,
            detail={"code": "UNKNOWN_ASSET", "message": f"Unknown asset: {asset}"},
        )
    # Persist and execute with the canonical symbol (BTC/USDT -> BTC-USDT) so
    # provider routing, provenance and stored results all identify one
    # instrument regardless of the alias the client used. Keep the client's
    # original spelling in the config for provenance.
    body["asset"] = inst.symbol
    asset = inst.symbol
    if requested_asset != inst.symbol:
        body["requestedSymbol"] = requested_asset
    else:
        body.pop("requestedSymbol", None)
    if not is_backtest_eligible(asset):
        raise HTTPException(
            422,
            detail={
                "code": "ASSET_NOT_BACKTESTABLE",
                "message": f"Asset {asset} ({inst.asset_class}) has no genuine OHLCV backtest source",
            },
        )
    # interval (validate & normalize before date-range check so intraday allows >= 1 day)
    raw_interval = str(body.get("interval", "1D")).strip()
    try:
        interval = normalize_interval(raw_interval)
    except EngineRejectedError:
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": f"interval must be one of {_INTERVALS}"}
        ) from None
    body["interval"] = interval
    # dates: from/to stay optional (the provider/engine applies its own default
    # window when both are omitted). Explicit values are validated strictly.
    from_str = str(body.get("from", "")).strip()
    to_str = str(body.get("to", "")).strip()
    if from_str or to_str:
        if not from_str or not to_str:
            raise HTTPException(
                422,
                detail={
                    "code": "BAD_INPUT",
                    "message": "Both from and to are required when either is set",
                },
            )
        try:
            if not _DATE_RE.match(from_str) or not _DATE_RE.match(to_str):
                raise ValueError("basic-format dates are not accepted")
            from_dt = dt.date.fromisoformat(from_str)
            to_dt = dt.date.fromisoformat(to_str)
        except Exception:  # noqa: BLE001
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "Invalid date format (use YYYY-MM-DD)"}
            ) from None
        today = dt.datetime.now(dt.UTC).date()
        if from_dt < _MIN_DATE:
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": f"Start date before {_MIN_DATE}"}
            )
        if to_dt >= today:
            raise HTTPException(
                422,
                detail={
                    "code": "BAD_INPUT",
                    "message": "End date cannot be today or in the future",
                },
            )
        if to_dt <= from_dt:
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "End date must be after start date"}
            )
        min_days = 1 if interval in INTRADAY_INTERVALS else 180
        if (to_dt - from_dt).days < min_days:
            msg = (
                "Date range must be at least 1 day for intraday intervals"
                if interval in INTRADAY_INTERVALS
                else "Date range must be at least 6 months"
            )
            raise HTTPException(422, detail={"code": "BAD_INPUT", "message": msg})
    # initialCapital
    try:
        raw_cap = body.get("initialCapital", 10000)
        if isinstance(raw_cap, bool):
            raise ValueError("boolean is not a number")
        cap = float(raw_cap)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": "initialCapital must be a number"}
        ) from None
    if not math.isfinite(cap) or cap < 100 or cap > 1_000_000:
        raise HTTPException(
            422,
            detail={
                "code": "BAD_INPUT",
                "message": "initialCapital must be between 100 and 1,000,000",
            },
        )
    # feePct
    try:
        raw_fee = body.get("feePct", 0.1)
        if isinstance(raw_fee, bool):
            raise ValueError("boolean is not a number")
        fee = float(raw_fee)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": "feePct must be a number"}
        ) from None
    if not math.isfinite(fee) or fee < 0 or fee > 5:
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": "feePct must be between 0 and 5"}
        )
    # cost fields (optional explicit overrides)
    for cost_key in ("commissionPct", "slippagePct", "spreadPct"):
        if cost_key in body and body[cost_key] is not None:
            raw_c = body[cost_key]
            if isinstance(raw_c, bool) or not isinstance(raw_c, (int, float)):
                raise HTTPException(
                    422, detail={"code": "BAD_INPUT", "message": f"{cost_key} must be a number"}
                )
            if not math.isfinite(float(raw_c)) or float(raw_c) < 0 or float(raw_c) > 5:
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": f"{cost_key} must be between 0 and 5"},
                )
    # stopLoss
    sl = body.get("stopLoss")
    if sl is not None:
        if not isinstance(sl, dict):
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "stopLoss must be an object"}
            )
        sl_mode = str(sl.get("mode", "none"))
        if sl_mode not in ("none", "fixed_pct", "risk_based"):
            raise HTTPException(
                422,
                detail={
                    "code": "BAD_INPUT",
                    "message": "stopLoss.mode must be none, fixed_pct, or risk_based",
                },
            )
        if sl_mode != "none":
            sl_pct = sl.get("pct")
            if isinstance(sl_pct, bool) or not isinstance(sl_pct, (int, float)) or not (0 < float(sl_pct) <= 95):
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "stopLoss.pct must be in (0, 95]"},
                )
    # takeProfit
    tp = body.get("takeProfit")
    if tp is not None:
        if not isinstance(tp, dict):
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "takeProfit must be an object"}
            )
        tp_mode = str(tp.get("mode", "none"))
        if tp_mode not in ("none", "fixed_pct"):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "takeProfit.mode must be none or fixed_pct"},
            )
        if tp_mode != "none":
            tp_pct = tp.get("pct")
            if isinstance(tp_pct, bool) or not isinstance(tp_pct, (int, float)) or not (0 < float(tp_pct) <= 1000):
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "takeProfit.pct must be in (0, 1000]"},
                )
    # positionSizing
    ps = body.get("positionSizing")
    if ps is not None:
        if not isinstance(ps, dict):
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "positionSizing must be an object"}
            )
        ps_mode = str(ps.get("mode", "pct_equity"))
        if ps_mode not in ("pct_equity", "fixed_amount", "risk_based"):
            raise HTTPException(
                422,
                detail={
                    "code": "BAD_INPUT",
                    "message": "positionSizing.mode must be pct_equity, fixed_amount, or risk_based",
                },
            )
        max_alloc = ps.get("maxAllocationPct", 100)
        if isinstance(max_alloc, bool) or not isinstance(max_alloc, (int, float)) or not (1 <= float(max_alloc) <= 100):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "maxAllocationPct must be in [1, 100]"},
            )
        val = ps.get("value")
        if ps_mode == "pct_equity" and val is not None:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not (1 <= float(val) <= 100):
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "positionSizing.value (%) must be in [1, 100]"},
                )
        elif ps_mode == "fixed_amount":
            if isinstance(val, bool) or not isinstance(val, (int, float)) or float(val) <= 0:
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "fixed_amount value must be > 0"},
                )
        elif ps_mode == "risk_based":
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not (0.1 <= float(val) <= 25):
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "risk_based value (%) must be in [0.1, 25]"},
                )
            if not isinstance(sl, dict) or sl.get("mode") == "none" or float(sl.get("pct", 0) or 0) <= 0:
                raise HTTPException(
                    422,
                    detail={
                        "code": "BAD_INPUT",
                        "message": "risk_based position sizing requires an active stopLoss.pct",
                    },
                )
    # validation (OOS split)
    val_cfg = body.get("validation")
    if val_cfg is not None:
        if not isinstance(val_cfg, dict):
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "validation must be an object"}
            )
        v_mode = str(val_cfg.get("mode", "none"))
        if v_mode not in ("none", "split"):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "validation.mode must be none or split"},
            )
        if v_mode == "split" and val_cfg.get("inSamplePct") is not None:
            is_pct = val_cfg.get("inSamplePct")
            if isinstance(is_pct, bool) or not isinstance(is_pct, (int, float)) or not (50 <= float(is_pct) <= 85):
                raise HTTPException(
                    422,
                    detail={"code": "BAD_INPUT", "message": "validation.inSamplePct must be in [50, 85]"},
                )
    # dataProvider
    provider_id = str(body.get("dataProvider", "")).strip()
    if provider_id:
        enabled = enabled_ids()
        if provider_id not in enabled:
            raise HTTPException(
                422,
                detail={
                    "code": "UNKNOWN_DATA_PROVIDER",
                    "message": f"Unknown or disabled provider: {provider_id}",
                },
            )
    # params must be an object when the key is present (JSON null is invalid)
    if "params" in body and not isinstance(body["params"], dict):
        raise HTTPException(
            422, detail={"code": "BAD_INPUT", "message": "params must be an object"}
        )
    _validate_params(str(template_id), body.get("params") or {})


def _migration_status() -> tuple[str | None, str | None]:
    """Return (current_revision, head_revision) from Alembic metadata."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, head


def _readiness_checks() -> tuple[bool, dict[str, Any]]:
    """Readiness = DB reachable + schema at migration head + market store readable."""
    ok = True
    checks: dict[str, Any] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["db"] = {"status": "error", "detail": redact(e)}
        ok = False

    try:
        current, head = _migration_status()
        if current is None and os.environ.get("ENV", "dev") != "production":
            # Dev databases created with init_db()/create_all have no
            # alembic_version row; report it without failing local readiness.
            checks["migrations"] = {"status": "unmanaged-dev", "head": head}
        elif current and head and current == head:
            checks["migrations"] = {"status": "head", "current": current, "head": head}
        else:
            checks["migrations"] = {"status": "behind", "current": current, "head": head}
            ok = False
    except Exception as e:  # noqa: BLE001
        checks["migrations"] = {"status": "error", "detail": redact(e)}
        if os.environ.get("ENV", "dev") == "production":
            ok = False

    try:
        s = SessionLocal()
        try:
            s.execute(select(MarketInstrument.id).limit(1)).all()
        finally:
            s.close()
        checks["store"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["store"] = {"status": "error", "detail": redact(e)}
        ok = False

    vok, vdetail = vendor_available()
    checks["vendor"] = {"available": bool(vok), "detail": vdetail}

    from .redis_store import redis_health

    rhealth = redis_health()
    checks["redis"] = rhealth
    if rhealth.get("configured") and rhealth.get("status") != "ok":
        ok = False
    return ok, checks


def create_app() -> FastAPI:
    from .auth import validate_prod_boot
    from .data_providers.csv_upload import retry_pending_upload_deletions

    validate_prod_boot()
    # Retry upload tombstones left by a crash/failed filesystem cleanup. This
    # only touches app-generated per-user quarantine names (never the upload
    # root or another tenant's directory).
    retry_pending_upload_deletions()
    app = FastAPI(title="BacktestLab API", version="1.0.0")
    origins = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware, probe_paths=_UNMATCHED_PROBE_PATHS)

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        d = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "ERROR", "message": str(exc.detail)}
        )
        ridv = get_request_id() or "-"
        msg = redact_url_keys(str(d.get("message", "Error")))
        payload: dict[str, Any] = {
            "code": d.get("code", "ERROR"),
            "message": msg,
            "details": [],
            "requestId": ridv,
        }
        # Preserve a small, explicit allow-list of provider context fields so
        # clients can render a precise message without echoing upstream bodies.
        for key in _SAFE_PROVIDER_DETAIL_KEYS:
            if key in d and d[key] not in (None, ""):
                payload[key] = d[key]
        return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exc(request: Request, exc: StarletteHTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {}
        code = d.get("code") or ("NOT_FOUND" if exc.status_code == 404 else "ERROR")
        message = d.get("message") or (str(exc.detail) if exc.detail else "Request failed")
        ridv = get_request_id() or "-"
        return JSONResponse(
            {
                "code": code,
                "message": redact_url_keys(str(message)),
                "details": [],
                "requestId": ridv,
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        ridv = get_request_id() or "-"
        details = [
            {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {
                "code": "BAD_INPUT",
                "message": "Request validation failed",
                "details": details,
                "requestId": ridv,
            },
            status_code=422,
        )

    @app.get("/health")
    def health():
        # Liveness: no DB, store or vendor dependency.
        return {"ok": True, "service": "backtestlab", "time": dt.datetime.now(dt.UTC).isoformat()}

    @app.get("/ready")
    def ready(response: Response):
        ok, checks = _readiness_checks()
        if not ok:
            response.status_code = 503
        return {"ok": ok, **checks}

    @app.get("/metrics")
    def metrics():
        return Response(render_metrics(), media_type="text/plain; version=0.0.4")

    @app.get("/api/v1/health")
    def health_v1():
        return {"ok": True}

    @app.post("/api/v1/auth/register", status_code=201)
    def register(body: Register, request: Request, response: Response):
        init_db()
        from .auth import rate_limit, set_auth_cookies

        if not rate_limit("reg:" + client_ip(request)):
            raise HTTPException(
                429, detail={"code": "RATE_LIMITED", "message": "Too many attempts"}
            )
        email_raw = body.email.strip()
        if not _EMAIL_RE.match(email_raw) or len(email_raw) > 320:
            raise HTTPException(422, detail={"code": "INVALID_EMAIL", "message": "Invalid email"})
        if len(body.password) < 8 or len(body.password) > 200:
            raise HTTPException(
                422, detail={"code": "WEAK_PASSWORD", "message": "Password too short"}
            )
        if len(body.name.strip()) < 2:
            raise HTTPException(422, detail={"code": "INVALID_NAME", "message": "Invalid name"})
        s = SessionLocal()
        try:
            if s.scalar(select(User).where(User.email == email_raw.lower())):
                raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "Email taken"})
            u = User(
                id="u-" + uuid.uuid4().hex[:8],
                email=email_raw.lower(),
                name=body.name.strip()[:200],
                password_hash=hash_pw(email_raw, body.password),
                plan="free",
            )
            s.add(u)
            s.commit()
            s.refresh(u)
            tok = make_token(u.id)
            refresh, _jti, _exp = issue_refresh_token(u.id)
            set_auth_cookies(response, tok, refresh)
            return {
                "token": tok,
                "access_token": tok,
                "refresh_token": refresh,
                "user": user_dict(u),
            }
        finally:
            s.close()

    @app.post("/api/v1/auth/login")
    def login(body: Login, request: Request, response: Response):
        init_db()
        from .auth import (
            clear_login_failures,
            dummy_verify,
            login_lockout_remaining,
            record_login_failure,
            set_auth_cookies,
            verify_pw,
        )

        ip = client_ip(request)
        email = body.email.strip().lower()
        # DB-backed, cross-process lockout (5 account failures / window;
        # IP threshold is higher to avoid collateral lockout behind a NAT).
        retry_after = login_lockout_remaining(ip, email)
        if retry_after:
            raise HTTPException(
                429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Too many failed sign-in attempts",
                    "retryAfter": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        s = SessionLocal()
        try:
            u = s.scalar(select(User).where(User.email == email))
            if u is None:
                # Equalize timing with a real verification and count the
                # failure exactly like a wrong password: the response never
                # reveals whether the account exists.
                dummy_verify(body.password)
                record_login_failure(ip, email)
                raise HTTPException(
                    401, detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"}
                )
            ok, upgraded = verify_pw(body.email, body.password, u.password_hash)
            if not ok:
                record_login_failure(ip, email)
                raise HTTPException(
                    401, detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"}
                )
            clear_login_failures(email)
            if upgraded:
                u.password_hash = upgraded
                s.commit()
            access = make_token(u.id)
            refresh, _jti, _exp = issue_refresh_token(u.id)
            set_auth_cookies(response, access, refresh)
            return {
                "token": access,
                "access_token": access,
                "refresh_token": refresh,
                "user": user_dict(u),
            }
        finally:
            s.close()

    @app.post("/api/v1/auth/forgot")
    def forgot(body: dict[str, Any] | None = None, request: Request = None):  # type: ignore
        """Always generic (no account enumeration).

        When the account exists a single-use reset token is created and
        dispatched via the configured email provider (if any). The endpoint
        never returns the token, and it is rate-limited to prevent flooding.
        """
        from .auth import rate_limit
        from .email_service import send_password_reset_email

        email = str((body or {}).get("email", "")).strip().lower()
        if not email or len(email) > 320:
            return {"ok": True}
        ip = client_ip(request) if request is not None else "?"
        if not rate_limit("forgot-ip:" + ip) or not rate_limit("forgot-em:" + email):
            raise HTTPException(
                429, detail={"code": "RATE_LIMITED", "message": "Too many attempts"}
            )
        init_db()
        s = SessionLocal()
        try:
            u = s.scalar(select(User).where(User.email == email))
            if u is not None:
                token = issue_password_reset(u.id)
                send_password_reset_email(to_email=u.email, token=token)
                if os.environ.get("AUTH_RESET_TOKEN_LOG", "0") == "1":
                    log.info("password reset token issued for %s: %s", u.id, token)
        finally:
            s.close()
        return {"ok": True}

    @app.post("/api/v1/auth/reset")
    def reset(body: dict[str, Any] | None = None):
        payload = body or {}
        token = str(payload.get("token") or "").strip()
        password = str(payload.get("password") or "")
        if not token or len(password) < 8 or len(password) > 200:
            raise HTTPException(422, detail={"code": "INVALID_TOKEN", "message": "Invalid token"})
        uid = consume_password_reset(token)
        if uid is None:
            raise HTTPException(
                422, detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token"}
            )
        init_db()
        s = SessionLocal()
        try:
            u = s.get(User, uid)
            if u is None:
                raise HTTPException(
                    422, detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token"}
                )
            u.password_hash = hash_pw(u.email, password)
            s.commit()
        finally:
            s.close()
        # A password reset invalidates every existing refresh token.
        revoke_refresh_tokens(uid)
        return {"ok": True}

    @app.post("/api/v1/auth/refresh")
    def refresh(request: Request, response: Response, body: RefreshRequest | None = None):
        from .auth import REFRESH_COOKIE, set_auth_cookies, verify_csrf

        init_db()
        if body is not None:
            raw_refresh = body.refresh_token or None
        else:
            raw_refresh = request.cookies.get(REFRESH_COOKIE)
            if raw_refresh:
                verify_csrf(request)
        if not raw_refresh:
            raise HTTPException(
                401, detail={"code": "INVALID_TOKEN", "message": "Missing refresh token"}
            )
        out = rotate_refresh_token(raw_refresh)
        if out is None:
            raise HTTPException(
                401, detail={"code": "INVALID_TOKEN", "message": "Invalid or reused refresh token"}
            )
        access, new_refresh = out
        set_auth_cookies(response, access, new_refresh)
        return {
            "token": access,
            "access_token": access,
            "refresh_token": new_refresh,
        }

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, body: RefreshRequest | None = None):
        from .auth import ACCESS_COOKIE, REFRESH_COOKIE, clear_auth_cookies, verify_csrf

        init_db()
        raw_refresh = body.refresh_token if (body and body.refresh_token) else None
        if not raw_refresh:
            raw_refresh = request.cookies.get(REFRESH_COOKIE)
            if raw_refresh or request.cookies.get(ACCESS_COOKIE):
                verify_csrf(request)
        if raw_refresh:
            try:
                payload = jwt.decode(
                    raw_refresh,
                    SECRET,
                    algorithms=["HS256"],
                    options={"verify_exp": False, "require": ["sub", "kind"]},
                )
                if payload.get("kind") == "refresh" and payload.get("sub"):
                    revoke_refresh_tokens(str(payload["sub"]), payload.get("jti"))
            except Exception:  # noqa: BLE001
                pass
        clear_auth_cookies(response)
        return {"ok": True}

    @app.post("/api/v1/auth/revoke")
    def revoke(body: RefreshRequest, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        try:
            payload = jwt.decode(
                body.refresh_token,
                SECRET,
                algorithms=["HS256"],
                options={"verify_exp": False, "require": ["sub", "kind"]},
            )
        except Exception:  # noqa: BLE001
            payload = {}
        # Only a refresh token belonging to the authenticated caller can be
        # revoked through this endpoint.
        if payload.get("kind") == "refresh" and payload.get("sub") == u.id:
            revoke_refresh_tokens(u.id, payload.get("jti"))
        return {"ok": True}

    @app.get("/api/v1/auth/me")
    def me(u: User = Depends(current_user)):  # noqa: B008
        return user_dict(u)

    @app.get("/api/v1/templates")
    def templates():
        return {"items": TEMPLATES, "total": len(TEMPLATES)}

    @app.get("/api/v1/assets")
    def assets():
        """Authoritative instrument catalog.

        Derived from the instrument registry (not a hand-maintained UI list) so
        the UI can only select instruments the backend can genuinely backtest
        with an enabled, configured provider.
        """
        items = asset_catalog()
        return {"items": items, "total": len(items)}

    @app.get("/api/v1/data-providers")
    def data_providers():
        """Provider catalog: id, AR/EN names, markets/intervals, requires_key,
        availability (health), enabled + license_class as PLAIN INFORMATION
        only (no gating is derived from it)."""
        return provider_infos()

    @app.get("/api/v1/data-providers/diagnostics")
    def data_providers_diagnostics(probes: bool = False):
        """Comprehensive market data provider audit, health & asset coverage report."""
        from .data_providers.diagnostics import generate_diagnostics_report

        return generate_diagnostics_report(run_probes=probes)

    @app.get("/api/v1/macro/series")
    def macro_series(
        series_id: str,
        start: str = "",
        end: str = "",
        limit: int = 200,
        response: Response = None,  # type: ignore[assignment]
        _u: User = Depends(current_user),  # noqa: B008
    ):
        """Fetch macroeconomic observations from FRED (separate from OHLCV backtests)."""
        from .data_providers.base import ProviderError, http_status_for_code
        from .data_providers.fred import FredProvider

        if response is not None:
            response.headers["Cache-Control"] = "no-store"
        try:
            return FredProvider().fetch_macro_observations(
                series_id, start=start, end=end, limit=limit
            )
        except ProviderError as e:
            raise HTTPException(
                http_status_for_code(e.code),
                detail={"code": e.code, "message": str(e), "provider": e.provider},
            ) from e

    @app.post("/api/v1/data-providers/csv-upload")
    def csv_upload(body: dict[str, Any], u: User = Depends(current_user)):  # noqa: B008
        """Upload a user-supplied OHLCV CSV for the csv_upload provider."""
        from .data_providers.csv_upload import upload_symbol_csv

        symbol = str(body.get("symbol", "")).strip().upper()
        content = body.get("csv")
        if not symbol or not isinstance(content, str) or not content.strip():
            raise HTTPException(
                422, detail={"code": "BAD_INPUT", "message": "symbol + csv (string) required"}
            )
        try:
            out = upload_symbol_csv(symbol, content.encode(), u.id)
        except ProviderError as e:
            raise HTTPException(422, detail={"code": e.code, "message": str(e)}) from e
        return {"ok": True, **out}

    @app.get("/api/v1/data-store/availability")
    def data_store_availability(u: User = Depends(current_user)):  # noqa: B008
        """Provider availability status for the data store catalog."""
        from .data_providers.registry import provider_infos

        catalog = provider_infos()
        return {
            "enabled": catalog["enabled"],
            "default": catalog["default"],
            "providers": [
                {
                    "id": it["id"],
                    "nameEn": it["nameEn"],
                    "nameAr": it["nameAr"],
                    "category": it.get("category"),
                    "available": it["available"],
                    "availableDetail": it["availableDetail"],
                    "retryAfter": it.get("retryAfter", 0),
                    "requiresKey": it["requiresKey"],
                    "requiresKeyEnv": it.get("requiresKeyEnv"),
                    "licenseClass": it["licenseClass"],
                }
                for it in catalog["items"]
            ],
        }

    @app.get("/api/v1/data-store/coverage")
    def data_store_coverage(limit: int = 100, offset: int = 0, u: User = Depends(current_user)):  # noqa: B008
        """Coverage info for data stored in the market data store (paginated)."""
        from app.data_providers.registry import provider_infos
        from app.data_store.repository import read_coverage_all
        from app.data_store.service import is_enabled

        try:
            limit, offset = _page_args(limit, offset, default=100, maximum=500)
            coverage = read_coverage_all(limit=limit, offset=offset)
        except Exception:  # noqa: BLE001
            coverage = {"instruments": [], "providers": {}, "total": 0}

        by_id = {it["id"]: it for it in provider_infos()["items"]}
        provider_list = []
        for pid in all_provider_ids():
            item = by_id.get(pid, {})
            provider_list.append(
                {
                    "id": pid,
                    "name": item.get("nameEn", pid),
                    "category": item.get("category", "unknown"),
                    "enabled": pid in enabled_ids(),
                }
            )

        instruments = coverage.get("instruments", [])
        total = int(coverage.get("total", len(instruments)))
        return {
            "items": instruments,
            "instruments": instruments,
            "total": total,
            "limit": limit,
            "offset": offset,
            "providers": provider_list,
            "providerCounts": coverage.get("providers", {}),
            "storeEnabled": is_enabled(),
        }

    @app.get("/api/v1/data-store/instruments")
    def data_store_instruments(limit: int = 100, offset: int = 0, u: User = Depends(current_user)):  # noqa: B008
        """Stored instruments plus the timeframes/ranges available for each."""
        from app.data_store.repository import coverage_summary

        try:
            limit, offset = _page_args(limit, offset, default=100, maximum=500)
            summary = coverage_summary(limit=limit, offset=offset)
        except Exception:  # noqa: BLE001
            summary = {
                "instruments": [],
                "timeframes": [],
                "providers": {},
                "instrumentCount": 0,
                "completeCoverageRows": 0,
            }
        instruments = summary.get("instruments", [])
        return {
            "items": instruments,
            "total": int(summary.get("instrumentCount", len(instruments))),
            "limit": limit,
            "offset": offset,
            "timeframes": summary.get("timeframes", []),
            "providers": summary.get("providers", []),
            "completeCoverageRows": summary.get("completeCoverageRows", 0),
        }

    @app.get("/api/v1/data-store/hash-stability")
    def data_store_hash_stability(
        limit: int = 100, offset: int = 0, u: User = Depends(current_user)
    ):  # noqa: B008
        """Verify stored coverage hashes still match the stored bars (paged)."""
        from app.data_store.repository import verify_coverage_hashes

        try:
            limit, offset = _page_args(limit, offset, default=100, maximum=500)
            checks = verify_coverage_hashes(limit=limit, offset=offset)
            return {
                "stable": all(c["ok"] for c in checks),
                "checks": checks,
                "partial": len(checks) >= limit,
                "limit": limit,
                "offset": offset,
            }
        except Exception as e:  # noqa: BLE001
            return {"stable": False, "checks": [], "error": redact_url_keys(str(e))}

    @app.get("/api/v1/usage")
    def usage(u: User = Depends(current_user)):  # noqa: B008
        init_db()
        s = SessionLocal()
        try:
            row = s.scalar(select(Usage).where(Usage.user_id == u.id, Usage.day == today_key()))
            limit = PRO_LIMIT if u.plan == "pro" else FREE_LIMIT
            return {
                "usedToday": row.used if row else 0,
                "dailyLimit": limit,
                "plan": u.plan,
                "periodStart": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT00:00:00Z"),
            }
        finally:
            s.close()

    @app.get("/api/v1/plans")
    def plans():
        return {
            "billingEnabled": BILLING_ENABLED,
            "items": [
                {
                    "id": "free",
                    "monthlyPrice": 0,
                    "yearlyPrice": 0,
                    "available": True,
                },
                {
                    "id": "pro",
                    "monthlyPrice": 19,
                    "yearlyPrice": 182,
                    "available": BILLING_ENABLED,
                },
            ],
        }

    @app.get("/api/v1/invoices")
    def invoices(u: User = Depends(current_user)):  # noqa: B008
        return {"items": []}

    @app.get("/api/v1/notifications")
    def notifs(u: User = Depends(current_user)):  # noqa: B008
        return {"items": []}

    def _limit_check(s, u: User):
        limit = PRO_LIMIT if u.plan == "pro" else FREE_LIMIT
        row = s.scalar(select(Usage).where(Usage.user_id == u.id, Usage.day == today_key()))
        used = row.used if row else 0
        if used >= limit:
            raise HTTPException(
                429, detail={"code": "DAILY_LIMIT_REACHED", "message": "Daily limit reached"}
            )
        return row, limit

    @app.get("/api/v1/backtests")
    def list_bt(limit: int = DEFAULT_PAGE_SIZE, offset: int = 0, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        limit, offset = _page_args(limit, offset)
        s = SessionLocal()
        try:
            where = Backtest.user_id == u.id
            total = s.scalar(select(func.count()).select_from(Backtest).where(where)) or 0
            rows = s.scalars(
                select(Backtest)
                .where(where)
                .order_by(Backtest.created_at.desc(), Backtest.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [summary(b) for b in rows],
                "total": int(total),
                "limit": limit,
                "offset": offset,
            }
        finally:
            s.close()

    @app.post("/api/v1/backtests", status_code=201)
    @_bounded_backtest
    def create_bt(
        body: dict[str, Any],
        u: User = Depends(current_user),  # noqa: B008
        request: Request = None,
    ):  # type: ignore
        init_db()
        t_start = time.perf_counter()
        _validate_backtest_input(body)
        timings: dict[str, float] = {
            "validate_ms": round((time.perf_counter() - t_start) * 1000, 2)
        }
        idem = ""
        try:
            idem = request.headers.get("idempotency-key", "") if request else ""
        except Exception:  # noqa: BLE001
            idem = ""
        if len(idem) > 128:
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "Idempotency-Key must be 1-128 chars"},
            )
        async_param = ""
        try:
            async_param = (request.query_params.get("async", "") if request else "").strip().lower()
        except Exception:  # noqa: BLE001
            async_param = ""
        default_async = os.environ.get(
            "ASYNC_BACKTESTS_DEFAULT",
            "1" if os.environ.get("ENV") == "production" else "0",
        ) in ("1", "true", "True", "yes")
        if async_param == "false":
            async_mode = False
        elif async_param == "true":
            async_mode = True
        else:
            async_mode = default_async or bool(idem)
        if async_mode:
            from .queue import submit_job

            try:
                out = submit_job(u.id, body, idem)
            except LookupError:
                raise HTTPException(
                    429,
                    detail={"code": "DAILY_LIMIT_REACHED", "message": "Daily limit reached"},
                ) from None
            except RuntimeError as e:
                raise HTTPException(503, detail={"code": "SERVER_BUSY", "message": str(e)}) from e
            return {
                "jobId": out["job_id"],
                "backtestId": out["backtest_id"],
                "status": out["status"],
                "deduped": out["deduped"],
            }
        s = SessionLocal()
        try:
            _row, limit = _limit_check(s, u)
            if ENGINE_MODE == "local":
                r = _synthetic_run(body)
                r.setdefault("warnings", []).append({"code": "SYNTHETIC_DATA"})
                r["engine"] = engine_block()
            else:
                t_data = time.perf_counter()
                try:
                    _dp, prov = fetch_bars(
                        body.get("dataProvider"),
                        str(body.get("asset", "AAPL")),
                        str(body.get("from", "") or ""),
                        str(body.get("to", "") or ""),
                        str(body.get("interval", "1D")),
                        user_id=u.id,
                    )
                except ProviderError as e:
                    timings["data_ms"] = round((time.perf_counter() - t_data) * 1000, 2)
                    timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
                    log.info(
                        "backtest timing",
                        extra={
                            "timings": timings,
                            "status": 422
                            if e.code in _PROVIDER_VALIDATION_CODES
                            else http_status_for_code(e.code),
                        },
                    )
                    if e.code not in _PROVIDER_VALIDATION_CODES and e.code != ERR_RATE_LIMITED:
                        # Only log genuine upstream/operational failures; a
                        # validated no-data outcome is a client-visible 422.
                        log.error("data provider failed: %s", e)
                    raise _provider_http_exception(e) from e
                timings["data_ms"] = round((time.perf_counter() - t_data) * 1000, 2)
                guards = quality_guards(prov.frame)
                if prov.provenance.get("license_class") != "commercial_ok":
                    guards = guards + [{"code": "DATA_DEV_SOURCE"}]
                try:
                    t_engine = time.perf_counter()
                    r = run_and_normalize(body, prov.frame, prov.provenance, guards)
                    timings["engine_ms"] = round((time.perf_counter() - t_engine) * 1000, 2)
                except EngineRejectedError as e:
                    raise HTTPException(
                        422, detail={"code": "ENGINE_NOT_ALLOWED", "message": str(e)}
                    ) from e
                except VendorUnavailableError as e:
                    # NO silent fallback to the local imitation: fail loudly.
                    log.error("vendor engine unavailable: %s", e)
                    raise HTTPException(
                        503, detail={"code": "ENGINE_UNAVAILABLE", "message": str(e)}
                    ) from e
            bid = "bt-" + uuid.uuid4().hex[:8]
            t_persist = time.perf_counter()
            pv = r.get("provenance", {}) if isinstance(r.get("provenance"), dict) else {}
            b = Backtest(
                id=bid,
                user_id=u.id,
                name=str(body.get("asset", "AAPL"))
                + " / "
                + str(body.get("templateId", "ma-crossover")),
                template_id=r["templateId"],
                asset=r["asset"],
                status="done",
                created_at=dt.datetime.now(dt.UTC).isoformat(),
                total_return_pct=r["totalReturnPct"],
                max_drawdown_pct=r["maxDrawdownPct"],
                sharpe=r["sharpe"],
                win_rate_pct=r["winRatePct"],
                trades=r["trades"],
                vs_buy_hold_pct=r["vsBuyHoldPct"],
                data_provider=str(pv.get("provider", "")),
                data_symbol=str(pv.get("symbol", "")),
                data_interval=str(pv.get("interval", "")),
                data_start=str(pv.get("start") or ""),
                data_end=str(pv.get("end") or ""),
                data_hash=str(pv.get("dataHash", "")),
                data_rows=int(pv.get("rows") or pv.get("bars") or 0),
                config_json=json.dumps(body, default=str),
                result_json=json.dumps(r, default=str),
            )
            s.add(b)
            from .queue import _reserve_quota

            try:
                _reserve_quota(s, u.id, today_key(), limit)
            except LookupError:
                s.rollback()
                raise HTTPException(
                    429,
                    detail={"code": "DAILY_LIMIT_REACHED", "message": "Daily limit reached"},
                ) from None
            s.commit()
            timings["persist_ms"] = round((time.perf_counter() - t_persist) * 1000, 2)
            timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
            log.info(
                "backtest timing",
                extra={
                    "timings": timings,
                    "status": 201,
                    "provider": str(pv.get("provider", "")),
                    "symbol": str(pv.get("symbol", "")),
                },
            )
            return full(b)
        finally:
            s.close()

    @app.get("/api/v1/backtests/{bid}")
    def get_bt(bid: str, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        s = SessionLocal()
        try:
            b = s.scalar(select(Backtest).where(Backtest.id == bid, Backtest.user_id == u.id))
            if b is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            return full(b)
        finally:
            s.close()

    @app.get("/api/v1/jobs/{jid}")
    def get_job(jid: str, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        from .db import Job

        s = SessionLocal()
        try:
            j = s.scalar(select(Job).where(Job.id == jid, Job.user_id == u.id))
            if j is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            return {
                "jobId": j.id,
                "backtestId": j.backtest_id,
                "status": j.status,
                "progress": j.progress,
                "error": redact_url_keys(str(j.error)) if j.error else None,
            }
        finally:
            s.close()

    @app.post("/api/v1/jobs/{jid}/cancel")
    def cancel_job(jid: str, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        from .db import Job

        s = SessionLocal()
        try:
            j = s.scalar(select(Job).where(Job.id == jid, Job.user_id == u.id))
            if j is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            if j.status in ("queued", "running"):
                j.status = "cancelled"
                s.commit()
            return {"jobId": j.id, "status": j.status}
        finally:
            s.close()

    @app.delete("/api/v1/backtests/{bid}")
    def del_bt(bid: str, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        s = SessionLocal()
        try:
            b = s.scalar(select(Backtest).where(Backtest.id == bid, Backtest.user_id == u.id))
            if b is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            s.delete(b)
            s.commit()
            return {"ok": True}
        finally:
            s.close()

    @app.get(
        "/api/v1/compare",
    )
    def compare(ids: str = "", u: User = Depends(current_user)):  # noqa: B008
        init_db()
        requested = [x for x in ids.split(",") if x]
        truncated = len(requested) > API_MAX_COMPARE_IDS
        requested = requested[:API_MAX_COMPARE_IDS]
        s = SessionLocal()
        try:
            out = []
            for bid in requested:
                b = s.scalar(select(Backtest).where(Backtest.id == bid, Backtest.user_id == u.id))
                if b is not None:
                    out.append(full(b))
            return {
                "items": out,
                "disclaimer": DISCLAIMER,
                "requested": len(requested),
                "returned": len(out),
                "truncated": truncated,
            }
        finally:
            s.close()

    @app.get("/api/v1/backtests/{bid}/export.csv")
    def export_csv(bid: str, u: User = Depends(current_user)):  # noqa: B008
        init_db()
        s = SessionLocal()
        try:
            b = s.scalar(select(Backtest).where(Backtest.id == bid, Backtest.user_id == u.id))
            if b is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            r = json.loads(b.result_json or "{}")
            lines = ["id,date,side,price,qty,pnl"] + [
                f"{t['id']},{t['date']},{t['side']},{t['price']},{t['qty']},{t['pnl']}"
                for t in r.get("tradesList", [])
            ]
            return Response(
                "\n".join(lines),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={bid}.csv"},
            )
        finally:
            s.close()

    @app.get("/api/v1/backtests/{bid}/report", response_class=HTMLResponse)
    def report(bid: str, u: User = Depends(current_user)):  # noqa: B008
        import html

        init_db()
        s = SessionLocal()
        try:
            b = s.scalar(select(Backtest).where(Backtest.id == bid, Backtest.user_id == u.id))
            if b is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            r = json.loads(b.result_json or "{}")
            eng = r.get("engine") if isinstance(r.get("engine"), dict) else {}
            prov = r.get("provenance") or {}
            eng_line = html.escape(
                f"Engine: {eng.get('mode', '-')}/{eng.get('engineName', '-')} "
                f"ref {str(eng.get('vendorVersionOrRef') or '-')[:12]}"
            )
            prov_line = html.escape(
                f"Data: provider={prov.get('provider', '-')} "
                f"symbol={prov.get('symbol', b.asset)} "
                f"interval={prov.get('interval', '1D')} "
                f"range={prov.get('start', '?')}..{prov.get('end', '?')} "
                f"rows={prov.get('bars', prov.get('rows', '-'))} "
                f"hash={str(prov.get('dataHash', '-'))[:12]}"
            )
            return (
                f"<!doctype html><html dir='ltr'><head><meta charset='utf-8'><title>{html.escape(b.name)}</title></head>"
                f"<body><h1>{html.escape(b.name)}</h1>"
                f"<p>Return: {b.total_return_pct}% | Sharpe: {b.sharpe} | Trades: {b.trades}</p>"
                f"<p><small>{eng_line}<br/>{prov_line}</small></p>"
                f"<p>{html.escape(DISCLAIMER['en'])}</p></body></html>"
            )
        finally:
            s.close()

    @app.patch("/api/v1/auth/me")
    def update_me(body: dict[str, Any], u: User = Depends(current_user)):  # noqa: B008
        init_db()
        unknown = sorted(set(body) - {"name", "language"})
        if unknown:
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": f"Unknown fields: {', '.join(unknown)}"},
            )
        if "name" in body and (
            not isinstance(body["name"], str) or not (2 <= len(body["name"].strip()) <= 200)
        ):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "name must be a 2-200 char string"},
            )
        if "language" in body and (
            not isinstance(body["language"], str) or body["language"] not in ("ar", "en")
        ):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "language must be 'ar' or 'en'"},
            )
        s = SessionLocal()
        try:
            db_u = s.get(User, u.id)
            if db_u is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            if "name" in body:
                db_u.name = body["name"].strip()
            if "language" in body:
                db_u.language = body["language"]
            s.commit()
            s.refresh(db_u)
            return user_dict(db_u)
        finally:
            s.close()

    @app.post("/api/v1/auth/password")
    def change_password(body: dict[str, Any], u: User = Depends(current_user)):  # noqa: B008
        """Change the caller's password after verifying the current one."""
        from .auth import verify_pw

        current = body.get("currentPassword")
        new = body.get("newPassword")
        if not isinstance(current, str) or not isinstance(new, str):
            raise HTTPException(
                422,
                detail={"code": "BAD_INPUT", "message": "currentPassword and newPassword required"},
            )
        if len(new) < 8 or len(new) > 200:
            raise HTTPException(
                422, detail={"code": "WEAK_PASSWORD", "message": "Password too short"}
            )
        init_db()
        s = SessionLocal()
        try:
            db_u = s.get(User, u.id)
            if db_u is None:
                raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Not found"})
            ok, _upgraded = verify_pw(db_u.email, current, db_u.password_hash)
            if not ok:
                raise HTTPException(
                    401,
                    detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"},
                )
            db_u.password_hash = hash_pw(db_u.email, new)
            s.commit()
        finally:
            s.close()
        # Existing refresh tokens can no longer mint sessions.
        revoke_refresh_tokens(u.id)
        return {"ok": True}

    @app.delete("/api/v1/auth/me")
    def delete_me(u: User = Depends(current_user)):  # noqa: B008
        from .data_providers.csv_upload import (
            finalize_user_upload_deletion,
            prepare_user_upload_deletion,
            restore_user_upload_deletion,
        )

        init_db()
        s = SessionLocal()
        pending_uploads = None
        try:
            # SQLite ignores FOR UPDATE, so acquire its write reservation before
            # checking ownership. PostgreSQL uses the row lock below.
            if s.bind is not None and s.bind.dialect.name == "sqlite":
                s.connection().exec_driver_sql("BEGIN IMMEDIATE")
            db_u = s.scalar(select(User).where(User.id == u.id).with_for_update())
            if db_u is None:
                return {"ok": True}

            # Hide only this user's server-derived upload directory before the
            # transaction. If SQL fails, the directory is restored below.
            pending_uploads = prepare_user_upload_deletion(u.id)

            # Delete dependants explicitly; PostgreSQL and SQLite both enforce
            # foreign keys. password_resets has a FK to users.id (D-PH15-01).
            from .db import BillingCustomer

            s.execute(delete(BillingCustomer).where(BillingCustomer.user_id == u.id))
            s.execute(delete(RefreshToken).where(RefreshToken.user_id == u.id))
            s.execute(delete(PasswordReset).where(PasswordReset.user_id == u.id))
            s.execute(delete(Job).where(Job.user_id == u.id))
            s.execute(delete(Backtest).where(Backtest.user_id == u.id))
            s.execute(delete(Usage).where(Usage.user_id == u.id))
            s.delete(db_u)
            s.commit()
        except Exception:
            s.rollback()
            try:
                restore_user_upload_deletion(u.id, pending_uploads)
            except OSError:
                log.exception("failed to restore account uploads after deletion rollback")
            raise
        finally:
            s.close()

        # SQL is committed now. A cleanup error is logged and its tombstone is
        # retried at the next app start; never turn a committed deletion into a
        # misleading API failure.
        finalize_user_upload_deletion(pending_uploads)
        return {"ok": True}

    def _billing_unavailable(message: str) -> JSONResponse:
        return JSONResponse(
            {
                "code": "BILLING_NOT_CONFIGURED",
                "message": message,
                "details": [],
                "requestId": get_request_id() or "-",
            },
            status_code=501,
        )

    @app.get("/api/v1/billing/plans")
    def billing_plans():
        from .billing import PLANS, billing_enabled

        return {"enabled": billing_enabled(), "plans": list(PLANS.values())}

    @app.get("/api/v1/billing/status")
    def billing_status(u: User = Depends(current_user)):  # noqa: B008
        from .billing import billing_enabled
        from .db import BillingCustomer

        init_db()
        s = SessionLocal()
        try:
            bc = s.get(BillingCustomer, u.id)
            return {
                "enabled": billing_enabled(),
                "plan": u.plan,
                "status": bc.status if bc else ("active" if u.plan == "free" else "inactive"),
                "cancelAtPeriodEnd": bool(bc.cancel_at_period_end) if bc else False,
                "currentPeriodEnd": bc.current_period_end if bc else "",
            }
        finally:
            s.close()

    @app.post("/api/v1/billing/checkout")
    def checkout(request: Request, u: User = Depends(current_user)):  # noqa: B008
        from .billing import billing_enabled, create_checkout_session, is_stripe_configured
        from .email_service import app_base_url

        if not billing_enabled() or not is_stripe_configured():
            return _billing_unavailable(
                "Payments are not configured. Billing is disabled on this deployment."
            )
        base = app_base_url()
        try:
            return create_checkout_session(u, f"{base}/billing?status=success", f"{base}/billing?status=cancel")
        except RuntimeError as e:
            raise HTTPException(502, detail={"code": "BILLING_PROVIDER_ERROR", "message": str(e)}) from e

    @app.post("/api/v1/billing/portal")
    def portal(request: Request, u: User = Depends(current_user)):  # noqa: B008
        from .billing import billing_enabled, create_portal_session, is_stripe_configured
        from .email_service import app_base_url

        if not billing_enabled() or not is_stripe_configured():
            return _billing_unavailable(
                "Payments are not configured. Billing is disabled on this deployment."
            )
        try:
            return create_portal_session(u, f"{app_base_url()}/billing")
        except LookupError:
            raise HTTPException(404, detail={"code": "NO_BILLING_CUSTOMER", "message": "No subscription found"}) from None
        except RuntimeError as e:
            raise HTTPException(502, detail={"code": "BILLING_PROVIDER_ERROR", "message": str(e)}) from e

    @app.post("/api/v1/billing/webhook")
    async def webhook(request: Request):
        from .billing import billing_enabled, process_stripe_webhook

        if not billing_enabled():
            return JSONResponse(
                {
                    "code": "BILLING_NOT_CONFIGURED",
                    "message": "Billing webhooks are disabled on this deployment.",
                    "stored": False,
                    "requestId": get_request_id() or "-",
                },
                status_code=503,
            )
        raw_body = await request.body()
        sig = request.headers.get("stripe-signature", "")
        try:
            return process_stripe_webhook(raw_body, sig)
        except RuntimeError:
            return JSONResponse(
                {
                    "code": "BILLING_NOT_CONFIGURED",
                    "message": "Webhook secret not configured.",
                    "stored": False,
                    "requestId": get_request_id() or "-",
                },
                status_code=501,
            )
        except PermissionError:
            raise HTTPException(400, detail={"code": "INVALID_SIGNATURE", "message": "Invalid signature"}) from None
        except ValueError as e:
            raise HTTPException(400, detail={"code": "BAD_INPUT", "message": str(e)}) from e

    @app.post("/api/v1/support/contact")
    def contact(body: dict[str, Any]):
        return {"ok": True}

    @app.get("/api/v1/help")
    def help_():
        return {"items": [{"q": "Is this investment advice?", "a": "No. Analysis tool only."}]}

    @app.get("/docs-contract")
    def contract():
        return {"version": "1.0.0"}

    app.include_router(market_router.router)
    app.include_router(streaming_router.router)
    return app


app = create_app()
