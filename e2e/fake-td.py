#!/usr/bin/env python3
"""Fake Twelve Data WS server for the mocked streaming E2E (no real provider).

Sends subscribe-status plus periodic price events whose price increases by a
fixed delta each tick so browser assertions can observe *visible* updates.
This proves the app's forwarding path only — never real-provider data.
"""

import asyncio
import json
import time

import websockets

PORT = 9451
STEP = 0.01


async def handler(ws):
    subscribed: list[str] = []
    counter = {"n": 0}

    async def emitter():
        while True:
            await asyncio.sleep(1.0)
            counter["n"] += 1
            ts = int(time.time())
            for sym in list(subscribed):
                await ws.send(
                    json.dumps(
                        {
                            "event": "price",
                            "symbol": sym,
                            "currency": "USD",
                            "exchange": "X",
                            "type": "Common Stock",
                            "timestamp": ts,
                            "price": 100 + counter["n"] * STEP,
                            "day_volume": 1000 + counter["n"],
                        }
                    )
                )

    task = asyncio.create_task(emitter())
    try:
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("action") == "subscribe":
                syms = msg["params"]["symbols"].split(",")
                subscribed.extend(s for s in syms if s not in subscribed)
                await ws.send(
                    json.dumps(
                        {
                            "event": "subscribe-status",
                            "status": "ok",
                            "success": [{"symbol": s, "exchange": "X", "type": "Common Stock"} for s in syms],
                            "fails": [],
                        }
                    )
                )
            elif msg.get("action") == "heartbeat":
                await ws.send(json.dumps({"event": "heartbeat", "status": "ok"}))
    finally:
        task.cancel()


def process_request(path, request=None):
    # websockets versions differ: legacy passes (request,), asyncio passes
    # (path, connection). Normalize both.
    req = request if request is not None else path
    req_path = getattr(req, "path", None) or (path if isinstance(path, str) else None)
    if req_path == "/health":
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        return Response(200, "OK", Headers([("Content-Type", "text/plain")]), b"ok")
    return None


async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT, process_request=process_request):
        print(f"fake-td listening on 127.0.0.1:{PORT}", flush=True)
        await asyncio.Future()


asyncio.run(main())
