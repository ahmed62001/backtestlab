#!/usr/bin/env python3
"""Repeatable local load test for BacktestLab API (never hits external market-data APIs).

Starts or targets an isolated local FastAPI server with DATA_PROVIDER_DEFAULT=local,
runs concurrent health/catalog/backtest requests, and reports actual measured
p50/p95/p99 latency and throughput.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Any

import httpx


async def _worker(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    iterations: int,
    latencies: list[float],
    errors: list[str],
) -> None:
    for i in range(iterations):
        t0 = time.perf_counter()
        try:
            if i % 3 == 0:
                r = await client.get("/health")
            elif i % 3 == 1:
                r = await client.get("/api/v1/assets", headers=headers)
            else:
                r = await client.post(
                    "/api/v1/backtests?async=false",
                    json={
                        "templateId": "ma-crossover",
                        "asset": "AAPL",
                        "from": "2022-01-01",
                        "to": "2022-12-31",
                        "initialCapital": 10000,
                        "feePct": 0.1,
                        "params": {"fastPeriod": 10, "slowPeriod": 30},
                        "dataProvider": "local",
                    },
                    headers=headers,
                )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)
            if r.status_code >= 500:
                errors.append(f"HTTP {r.status_code}")
        except Exception as exc:
            errors.append(type(exc).__name__)


async def run_load(base_url: str, concurrency: int, iterations: int) -> dict[str, Any]:
    latencies: list[float] = []
    errors: list[str] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        email = f"load-{int(time.time())}@t.com"
        r = await client.post(
            "/api/v1/auth/register",
            json={"name": "Load Tester", "email": email, "password": "password123"},
        )
        if r.status_code == 409:
            r = await client.post(
                "/api/v1/auth/login", json={"email": email, "password": "password123"}
            )
        tok = r.json()["token"]
        headers = {"Authorization": f"Bearer {tok}"}

        t_start = time.perf_counter()
        await asyncio.gather(
            *[_worker(client, headers, iterations, latencies, errors) for _ in range(concurrency)]
        )
        total_s = time.perf_counter() - t_start

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)] if n else 0.0
    p95 = latencies[min(n - 1, int(n * 0.95))] if n else 0.0
    p99 = latencies[min(n - 1, int(n * 0.99))] if n else 0.0
    return {
        "concurrency": concurrency,
        "totalRequests": n,
        "errors": len(errors),
        "totalSeconds": round(total_s, 3),
        "rps": round(n / total_s, 2) if total_s > 0 else 0.0,
        "p50Ms": round(p50, 2),
        "p95Ms": round(p95, 2),
        "p99Ms": round(p99, 2),
        "meanMs": round(statistics.mean(latencies), 2) if latencies else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8011")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--iterations", type=int, default=5)
    args = ap.parse_args()
    import json

    res = asyncio.run(run_load(args.url, args.concurrency, args.iterations))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
