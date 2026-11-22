"""Pure-ASGI request middleware (Phase 4).

Replaces two ``@app.middleware("http")`` (``BaseHTTPMiddleware``) wrappers.

Why: ``BaseHTTPMiddleware`` runs the downstream app in a separate task and
buffers its messages. When an HTTP client disconnects mid-request, Starlette
cancels that task; ``call_next`` then raises ``RuntimeError: No response
returned.`` — an artificial error for a request the client already abandoned.
The old ``except Exception`` in the wrapper turned that into an HTTP 500 and an
``unhandled request error`` traceback. Because the error came from the
middleware's own task plumbing, it also appeared next to unrelated WebSocket
reconnect events.

This implementation talks ASGI directly:
* it never creates a second task, so disconnects cannot masquerade as errors;
* it distinguishes a real exception (still logged and returned as 500 when the
  client is connected) from a client disconnect (logged at INFO, no response);
* it propagates ``asyncio.CancelledError`` untouched.

All previous behaviour is preserved: request-id, security headers, no-store on
sensitive paths, access logging, and metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time

from starlette.datastructures import MutableHeaders

from .observability import (
    get_request_id,
    new_request_id,
    request_id_var,
)
from .observability import (
    inc as metric_inc,
)

log = logging.getLogger("backtestlab")

_NO_STORE_MARKERS = (
    "/auth/",
    "/backtests/",
    "/usage",
    "/jobs/",
    "/compare",
    "/data-store/",
    "/billing/",
)

_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)


class RequestContextMiddleware:
    """Security headers, request id, access log and disconnect-safe errors."""

    def __init__(
        self,
        app,
        probe_paths: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.probe_paths = frozenset(probe_paths)
        self._probe_lock = threading.Lock()
        self._probe_last: dict[tuple[str, str], float] = {}

    def _log_probe(self, scope, rid: str) -> None:
        path = (scope.get("path") or "/").rstrip("/") or "/"
        if path not in self.probe_paths:
            return
        client = scope.get("client")
        client_host = client[0] if client else "?"
        key = (client_host, path)
        now = time.monotonic()
        with self._probe_lock:
            last = self._probe_last.get(key, 0.0)
            if now - last < float(os.environ.get("PROBE_LOG_INTERVAL_S", "300")):
                return
            self._probe_last[key] = now
        log.warning(
            "unmatched client probe",
            extra={
                "method": scope.get("method"),
                "path": path,
                "status": 404,
                "client": client_host,
                "request_id": rid,
            },
        )
        with contextlib.suppress(Exception):
            metric_inc(
                "backtestlab_unmatched_probe_total",
                method=str(scope.get("method", "")),
                path=path,
            )

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            # WebSocket / lifespan traffic passes through untouched.
            await self.app(scope, receive, send)
            return

        incoming = ""
        for key, value in scope.get("headers", []):
            if key == b"x-request-id":
                incoming = value.decode("latin-1", "replace")
                break
        rid = (
            incoming
            if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", incoming or "")
            else new_request_id()
        )
        token = request_id_var.set(rid)
        started = time.perf_counter()
        self._log_probe(scope, rid)
        status = 500
        response_started = False
        disconnected = False

        async def receive_wrapper():
            nonlocal disconnected
            message = await receive()
            if message.get("type") == "http.disconnect":
                disconnected = True
            return message

        async def send_wrapper(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = int(message.get("status", 500))
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS:
                    headers.setdefault(name.decode(), value.decode())
                headers.setdefault("x-request-id", rid)
                path = scope.get("path", "")
                if any(marker in path for marker in _NO_STORE_MARKERS):
                    headers.setdefault("cache-control", "no-store")
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except asyncio.CancelledError:
            # The server cancelled the task (client gone). Re-raise: this is
            # not an application error and must not be converted into a 500.
            log.info(
                "request cancelled",
                extra={"method": scope.get("method"), "path": scope.get("path"), "request_id": rid},
            )
            raise
        except Exception:
            if disconnected:
                # Client went away; nothing can be delivered and nothing is
                # wrong with the application. Not an error.
                log.info(
                    "client disconnected before response",
                    extra={
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "request_id": rid,
                    },
                )
            elif response_started:
                # Headers already sent: cannot replace the response, but the
                # failure must still be visible to operators.
                log.exception(
                    "unhandled error after response started",
                    extra={"path": scope.get("path"), "request_id": rid},
                )
            else:
                log.exception(
                    "unhandled request error",
                    extra={"path": scope.get("path"), "request_id": rid},
                )
                body = json.dumps(
                    {
                        "code": "INTERNAL",
                        "message": "Internal error",
                        "details": [],
                        "requestId": rid,
                    }
                ).encode()
                try:
                    await send_wrapper(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send_wrapper({"type": "http.response.body", "body": body})
                except Exception:  # noqa: BLE001  # nosec B110 - transport is already gone
                    pass
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            route = scope.get("route")
            path = getattr(route, "path", None) or scope.get("path", "")
            method = scope.get("method", "")
            labels = {"method": method, "path": path}
            try:
                metric_inc("backtestlab_http_requests_total", status=str(status), **labels)
                metric_inc(
                    "backtestlab_http_request_duration_ms_sum", elapsed_ms, **labels
                )
                metric_inc("backtestlab_http_request_duration_ms_count", **labels)
            except Exception:  # noqa: BLE001  # nosec B110 - metrics must never break a request
                pass
            log.info(
                "request completed",
                extra={
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": elapsed_ms,
                    "request_id": rid,
                },
            )
            request_id_var.reset(token)


def is_client_disconnect_error(exc: BaseException) -> bool:
    """Recognise the historical ``RuntimeError: No response returned.`` signal.

    Kept for compatibility with call sites/tests that still classify the old
    BaseHTTPMiddleware failure. A bare RuntimeError with this message is only a
    disconnect symptom, never an application bug.
    """
    return isinstance(exc, RuntimeError) and "No response returned" in str(exc)


__all__ = ["RequestContextMiddleware", "is_client_disconnect_error", "get_request_id"]
