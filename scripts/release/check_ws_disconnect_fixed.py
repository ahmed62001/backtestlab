"""Same disconnect scenario as ``repro_ws_disconnect.py``, after the fix.

Wraps the aborted downstream with the production ``RequestContextMiddleware``.
Expected: no HTTP response is emitted (the client is gone) and no 500 is
fabricated.
"""

from __future__ import annotations

import asyncio
import json
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.middleware import RequestContextMiddleware  # noqa: E402


async def aborted_downstream(scope, receive, send):
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return  # no response is sent


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
    status = await drive(RequestContextMiddleware(aborted_downstream))
    print("FIXED_RESULT " + json.dumps({"status": status}))
    return 0 if status is None else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
