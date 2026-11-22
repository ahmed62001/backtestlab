#!/usr/bin/env python3
"""Bounded real-provider capability probes (dev use only).

Reads backend/.env for keys; never prints them. Prints only masked
diagnostics: status codes, response key names, timestamps, counts.
Phase A runs by default (REST). Phase B (Twelve Data WS) with --ws.
"""
import asyncio
import json
import os
import pathlib
import sys
import urllib.request
import urllib.error

ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def load_env() -> dict:
    out = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def get(name: str, env: dict) -> str | None:
    v = os.environ.get(name) or env.get(name)
    return v if v and len(v) >= 20 else None


def rest_json(url: str, label: str):
    print(f"\n[{label}] GET ...")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = r.read().decode()
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def masked(obj):
    if isinstance(obj, dict):
        return {k: ("<value>" if k in ("key", "api_key", "apikey") else masked(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [masked(x) for x in obj[:5]]
    return obj


def rest_phase(env):
    print("=== REST probes (bounded, one request each) ===")
    td = get("TWELVEDATA_API_KEY", env)
    if td:
        status, body = rest_json(
            f"https://api.twelvedata.com/price?symbol=AAPL&apikey={td}", "twelvedata price AAPL"
        )
        if isinstance(body, dict):
            print(f"status={status} keys={sorted(body.keys())} price_present={'price' in body} datetime_field={'datetime' in body} delay_field={'delay' in body}")
        else:
            print(f"status={status} body={str(body)[:120]}")
    else:
        print("twelvedata: MISSING key")
    pg = get("POLYGON_API_KEY", env)
    if pg:
        # Massive/Polygon shares the Polygon REST API shape.
        status, body = rest_json(
            f"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-05?adjusted=true&apiKey={pg}",
            "massive/polygon aggs AAPL",
        )
        if isinstance(body, dict):
            results = body.get("results")
            print(f"status={status} ticker={body.get('ticker')} result_count={body.get('result_count')} results_len={len(results) if isinstance(results, list) else 'n/a'}")
        else:
            print(f"status={status} body={str(body)[:160]}")
        status2, body2 = rest_json(
            f"https://api.polygon.io/v2/last/nbbo/AAPL?apiKey={pg}", "massive/polygon last AAPL"
        )
        if isinstance(body2, dict):
            print(f"status={status2} keys={sorted(body2.keys())} results_keys={sorted(body2.get('results', {}).keys()) if isinstance(body2.get('results'), dict) else 'n/a'}")
        else:
            print(f"status={status2} body={str(body2)[:160]}")
    else:
        print("massive/polygon: MISSING key")
    fred = get("FRED_API_KEY", env)
    if fred:
        status, body = rest_json(
            f"https://api.stlouisfed.org/fred/series/observations?series_id=GDP&api_key={fred}&file_type=json&limit=2&sort_order=desc",
            "fred observations GDP",
        )
        if isinstance(body, dict):
            obs = body.get("observations") or []
            print(f"status={status} observations={len(obs)} keys={sorted(obs[0].keys()) if obs else []} date={obs[0].get('date') if obs else 'n/a'}")
        else:
            print(f"status={status} body={str(body)[:160]}")
    else:
        print("fred: MISSING key")


async def ws_phase(env):
    print("\n=== Twelve Data WS probe (2 symbols, bounded) ===")
    import websockets

    td = get("TWELVEDATA_API_KEY", env)
    if not td:
        print("twelvedata WS: MISSING key")
        return
    url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={td}"
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            # BTC/USD trades 24/7; AAPL may be closed (no tick expected outside session).
            await ws.send(json.dumps({"action": "subscribe", "params": {"symbols": "BTC/USD,AAPL"}}))
            import time

            ticks: list[dict] = []
            deadline = time.time() + 60
            while time.time() < deadline and len(ticks) < 3:
                raw = await asyncio.wait_for(ws.recv(), timeout=65)
                msg = json.loads(raw)
                if msg.get("event") == "subscribe-status":
                    succ = msg.get("success") or []
                    fails = msg.get("fails") or []
                    print(f"subscribe-status: success={len(succ)} {[s.get('symbol') for s in succ]} fails={len(fails)}")
                    for f in fails:
                        print(f"  fail: {f}")
                elif msg.get("event") == "price":
                    ticks.append(msg)
                    print(f"TICK {msg.get('symbol')} ts={msg.get('timestamp')} type={msg.get('type')}")
            if ticks:
                import datetime as dt

                now = int(time.time())
                latest = max(t["timestamp"] for t in ticks)
                print(f"received {len(ticks)} genuine tick(s); latest provider ts age={now-latest}s")
            else:
                print("received 0 ticks in 60s (a closed equity market produces no tick; crypto should)")
    except Exception as e:  # noqa: BLE001
        print(f"WS probe failed: {type(e).__name__}: {str(e)[:200]}")


def main():
    env = load_env()
    rest_phase(env)
    if "--ws" in sys.argv:
        asyncio.run(ws_phase(env))


if __name__ == "__main__":
    main()
