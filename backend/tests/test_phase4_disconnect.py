"""Phase 4 — HTTP client disconnect must not create artificial HTTP 500s.

These tests drive the real application at the ASGI level with hand-written
``receive``/``send`` callables. ``TestClient`` cannot reproduce a disconnect:
it always delivers a complete request and collects a complete response.

Ordering is event-driven (no sleeps used for synchronisation beyond the
test-only slow endpoint that gives the disconnect a window to arrive).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402


class _Recorder:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, message) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return int(m["status"])
        return None

    @property
    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body")

    def headers(self) -> dict[str, str]:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return {
                    k.decode().lower(): v.decode() for k, v in m.get("headers", [])
                }
        return {}


def _scope(path: str, method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 55555),
        "server": ("testserver", 80),
    }


def _submit(app, scope, *, disconnect: bool, delay: float = 0.0):
    """Drive one request; optionally emit ``http.disconnect`` after the body."""
    recorder = _Recorder()
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        if disconnect:
            if delay:
                await asyncio.sleep(delay)
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()  # pragma: no cover - never expected
        raise AssertionError("unreachable")

    async def run():
        await app(scope, receive, recorder.send)

    return run, recorder


def _make_app():
    app = create_app()

    async def slow():
        # Gives the disconnect a deterministic window to be observed.
        await asyncio.sleep(0.05)
        return {"ok": True}

    async def boom():
        raise RuntimeError("genuine application failure")

    app.add_api_route("/_test/phase4/slow", slow, methods=["GET"])
    app.add_api_route("/_test/phase4/boom", boom, methods=["GET"])
    return app


def test_normal_request_succeeds_with_headers():
    app = _make_app()
    run, rec = _submit(app, _scope("/health"), disconnect=False)
    asyncio.run(run())
    assert rec.status == 200
    headers = rec.headers()
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"
    assert headers.get("x-request-id")


def test_client_disconnect_without_response_is_not_converted_to_500(caplog):
    """The exact baseline failure mode, at the middleware layer.

    A handler that observes ``http.disconnect`` and aborts without sending a
    response used to make ``BaseHTTPMiddleware.call_next`` raise
    ``RuntimeError: No response returned.`` and the wrapper answered 500.
    """
    from app.middleware import RequestContextMiddleware

    async def aborted(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return

    run, rec = _submit(RequestContextMiddleware(aborted), _scope("/_test/abort"), disconnect=True)
    asyncio.run(run())
    assert rec.status is None  # nothing can be delivered to a gone client
    assert "unhandled request error" not in caplog.text


def test_no_basehttp_middleware_decorators_remain():
    """Structural guard: the unsafe ``@app.middleware("http")`` wrappers are gone."""
    source = (BACKEND_ROOT / "app" / "main.py").read_text()
    assert '@app.middleware("http")' not in source
    assert "BaseHTTPMiddleware" not in source


def test_real_app_slow_endpoint_survives_disconnect():
    app = _make_app()
    run, rec = _submit(app, _scope("/_test/phase4/slow"), disconnect=True)
    asyncio.run(run())
    assert rec.status != 500


def test_request_id_header_is_echoed_when_valid():
    app = _make_app()
    run, rec = _submit(
        app,
        _scope("/health", headers=[(b"x-request-id", b"abc-123")]),
        disconnect=False,
    )
    asyncio.run(run())
    assert rec.headers().get("x-request-id") == "abc-123"


def test_sensitive_paths_are_not_cacheable():
    app = _make_app()
    run, rec = _submit(app, _scope("/api/v1/usage"), disconnect=False)
    asyncio.run(run())
    # Unauthenticated, but the no-store header must still be present.
    assert rec.status in (401, 403)
    assert rec.headers().get("cache-control") == "no-store"


def test_genuine_internal_exception_still_returns_500_and_is_logged(caplog):
    import logging

    caplog.set_level(logging.ERROR, logger="backtestlab")
    app = _make_app()
    run, rec = _submit(app, _scope("/_test/phase4/boom"), disconnect=False)
    asyncio.run(run())
    assert rec.status == 500
    assert b"Internal error" in rec.body
    assert "unhandled request error" in caplog.text


def test_cancellation_is_propagated_not_converted_to_500():
    app = create_app()

    async def cancelled():
        raise asyncio.CancelledError()

    app.add_api_route("/_test/phase4/cancel", cancelled, methods=["GET"])
    run, rec = _submit(app, _scope("/_test/phase4/cancel"), disconnect=False)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert rec.status != 500


def test_websocket_scope_passes_through_unmodified():
    app = create_app()
    seen: list[dict] = []
    sent: list[dict] = []

    async def fake_downstream(scope, receive, send):
        seen.append(scope)
        await send({"type": "websocket.accept"})

    async def receive():
        return {"type": "websocket.receive", "text": "hello"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "path": "/api/v1/ws",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    # Exercise the middleware in isolation so pass-through is unambiguous.
    from app.middleware import RequestContextMiddleware

    asyncio.run(RequestContextMiddleware(fake_downstream)(scope, receive, send))
    assert seen and seen[0]["type"] == "websocket"
    assert sent == [{"type": "websocket.accept"}]


def test_abnormal_websocket_disconnect_code_1006_is_handled():
    """The ASGI server delivers code 1006 after an abnormal close."""
    app = create_app()

    async def ws_downstream(scope, receive, send):
        await send({"type": "websocket.accept"})
        message = await receive()
        assert message["type"] == "websocket.disconnect"
        assert message["code"] == 1006
        await send({"type": "websocket.close", "code": 1006})

    from app.middleware import RequestContextMiddleware

    messages = [{"type": "websocket.disconnect", "code": 1006}]
    sent: list[dict] = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "path": "/api/v1/ws",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    asyncio.run(RequestContextMiddleware(ws_downstream)(scope, receive, send))
    assert sent[0]["type"] == "websocket.accept"
    assert sent[-1]["type"] == "websocket.close"
