"""Baseline reproduction of the Phase 4 failure mode.

Rebuilds the *pre-fix* pattern — two ``BaseHTTPMiddleware`` wrappers (the two
``@app.middleware("http")`` functions) around a handler whose response path is
skipped after the client disconnects (it returns without sending anything).
Drives it with a real ASGI client that emits ``http.disconnect``.

Expected on baseline: ``RuntimeError: No response returned.`` is converted by
the wrapper into an HTTP 500. After the fix: no response and no 500.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("baseline")


async def aborted_downstream(scope, receive, send):
    """A handler that observes the disconnect and aborts its response."""
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return  # no response is sent


async def guard(request, call_next):
    resp = await call_next(request)
    resp.headers["x-content-type-options"] = "nosniff"
    return resp


async def rid(request, call_next):
    try:
        return await call_next(request)
    except Exception:
        log.exception("unhandled request error")
        return JSONResponse({"code": "INTERNAL", "message": "Internal error"}, status_code=500)


def build():
    # Equivalent to adding `guard` then `rid`: rid is outermost.
    app = BaseHTTPMiddleware(BaseHTTPMiddleware(aborted_downstream, dispatch=guard), dispatch=rid)
    return app


async def drive(app):
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/_test/phase4/abort",
        "raw_path": b"/_test/phase4/abort",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 55555),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return next((m["status"] for m in messages if m["type"] == "http.response.start"), None)


async def main() -> int:
    status = await drive(build())
    print("BASELINE_RESULT " + json.dumps({"status": status}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
