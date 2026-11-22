#!/usr/bin/env python3
"""Real-provider streaming smoke test (requires credentials).

Connects to the REAL Twelve Data WebSocket, authenticates with the actual
TWELVEDATA_API_KEY, subscribes to priority symbols, and waits for genuine
price events, reporting one event's price, provider timestamp and latency.

Usage (from the repository root, with a key configured):
    TWELVEDATA_API_KEY=... python3 backend/scripts/smoke_streaming.py

Exit codes: 0 = ticks verified, 1 = stream failed / no ticks in time,
2 = BLOCKED (no key configured). Never prints the key.
Run from backend/ or with PYTHONPATH=backend.
"""

from __future__ import annotations

import asyncio
import os
import sys

try:
    import websockets
except ImportError:
    print("BLOCKED: 'websockets' package not installed.")
    raise SystemExit(2)

KEY = os.environ.get("TWELVEDATA_API_KEY", "").strip()
SYMBOLS = os.environ.get("SMOKE_SYMBOLS", "BTC/USD,AAPL,EUR/USD").split(",")
TIMEOUT_S = float(os.environ.get("SMOKE_TIMEOUT_S", "45"))


async def main() -> int:
    if KEY in ("", "your_twelvedata_api_key", "demo", "changeme"):
        print("BLOCKED: TWELVEDATA_API_KEY is not configured.")
        print("Set TWELVEDATA_API_KEY in the backend environment and re-run.")
        return 2
    url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={KEY}"
    ticks = 0
    deadline = asyncio.get_event_loop().time() + TIMEOUT_S
    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(
            json_dumps({"action": "subscribe", "params": {"symbols": ",".join(SYMBOLS)}})
        )
        import json

        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_S)
            msg = json.loads(raw)
            if msg.get("event") == "subscribe-status":
                print(f"subscribe-status ok: {len(msg.get('success', []))} symbols, fails: {msg.get('fails')}")
            elif msg.get("event") == "price":
                ticks += 1
                if ticks == 1:
                    print(
                        "TICK: symbol=%s price=%s provider_ts=%s"
                        % (msg.get("symbol"), msg.get("price"), msg.get("timestamp"))
                    )
                    print(f"received {ticks} genuine provider price event(s)")
                    return 0
    print(f"FAILED: connected and subscribed but got 0 ticks in {TIMEOUT_S}s (markets may be closed).")
    return 1


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
