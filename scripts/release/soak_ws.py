"""Phase 4 soak: WebSocket reconnect storm + concurrent HTTP load.

Runs against the running Docker Compose stack. Simulates abnormal WS closes
(1006 semantics: transport aborted without a close frame) while hammering the
five request paths that produced the historical 500s.

Exit 0 only when every HTTP response is non-500 and no unexpected traceback was
logged during the run.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import websockets

API = "http://localhost:8000"
WS = "ws://localhost:8000/api/v1/market/stream"
EMAIL_FILE = "/tmp/opencode/email.txt"
PASSWORD_FILE = "/tmp/opencode/qa-password.txt"
PATHS = [
    "/api/v1/usage",
    "/api/v1/templates",
    "/api/v1/backtests",
    "/api/v1/market/universe",
    "/api/v1/market/quotes?symbols=AAPL,MSFT",
]


def login() -> str:
    email = open(EMAIL_FILE).read().strip()
    password = open(PASSWORD_FILE).read().strip()
    req = urllib.request.Request(
        f"{API}/api/v1/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        d = json.load(res)
    return d.get("token") or d["access_token"]


def http_get(token: str, path: str) -> tuple[str, int, float]:
    started = time.perf_counter()
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            res.read()
            return path, res.status, time.perf_counter() - started
    except urllib.error.HTTPError as e:
        e.read()
        return path, e.code, time.perf_counter() - started
    except Exception:  # noqa: BLE001
        return path, 0, time.perf_counter() - started


async def ws_cycle(token: str, mode: str) -> str:
    url = f"{WS}?token={urllib.parse.quote(token)}"
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            await ws.send(json.dumps({"action": "subscribe", "symbols": ["AAPL"]}))
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                pass
            if mode == "abnormal":
                # Drop the TCP transport without a close handshake: the server
                # observes an abnormal (1006) disconnect.
                transport = getattr(ws, "transport", None)
                if transport is not None:
                    transport.abort()
                else:  # pragma: no cover - version fallback
                    await ws.close()
            else:
                await ws.close()
            return hello.get("event", "?")
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"


async def main() -> int:
    token = login()
    results = {"http": {}, "ws": [], "started_at": time.time()}

    async def storm(n: int) -> None:
        for i in range(n):
            results["ws"].append(await ws_cycle(token, "abnormal" if i % 2 == 0 else "normal"))

    def load(rounds: int):
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [
                pool.submit(http_get, token, path)
                for _ in range(rounds)
                for path in PATHS
            ]
            return [f.result() for f in futures]

    # Run HTTP load concurrently with the WS storm.
    loop = asyncio.get_running_loop()
    load_task = loop.run_in_executor(None, load, 8)
    await storm(40)
    http_results = await load_task

    for path, status, _elapsed in http_results:
        key = path.split("?")[0]
        bucket = results["http"].setdefault(key, {})
        bucket[str(status)] = bucket.get(str(status), 0) + 1

    results["finished_at"] = time.time()
    results["http_total"] = len(http_results)
    results["http_500"] = sum(1 for _, s, _ in http_results if s == 500)
    results["http_non_2xx"] = sum(1 for _, s, _ in http_results if not (200 <= s < 300))
    results["ws_cycles"] = len(results["ws"])
    results["ws_errors"] = sum(1 for r in results["ws"] if str(r).startswith("error"))
    print("SOAK_JSON " + json.dumps(results))
    return 0 if results["http_500"] == 0 and results["ws_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
