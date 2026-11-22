"""Phase 3 — independent provider comparison.

Calls Yahoo Finance directly (without importing the application's provider
code), saves a sanitized summary of the raw response, then diffs it against the
application's `/api/v1/market/series` output for the same window.

Usage: python phase3_provider_diff.py <token> [asset ...]
Output: JSON on stdout (also written by the caller to evidence).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import urllib.parse
import urllib.request

ASSETS = {"AAPL": "AAPL", "BTC-USD": "BTC-USD", "GC=F": "GC=F"}
INTERVALS = {"1D": ("1d", 365), "1H": ("1h", 60)}
API = "http://localhost:8000"


def fetch_api(token: str, symbol: str, interval: str, days: int) -> dict:
    url = (
        f"{API}/api/v1/market/series?symbol={urllib.parse.quote(symbol)}"
        f"&interval={interval}&days={days}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=90) as res:
        return json.load(res)


def fetch_provider(symbol: str, yf_interval: str, days: int) -> list[dict]:
    import yfinance as yf

    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=days)
    df = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=(end + dt.timedelta(days=1)).strftime("%Y-%m-%d"),
        interval=yf_interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or len(df) == 0:
        return []
    if getattr(df.columns, "nlevels", 1) > 1:
        df.columns = [c[0] for c in df.columns]
    out = []
    for ts, row in df.iterrows():
        try:
            out.append(
                {
                    "t": ts.tz_convert("UTC").isoformat()
                    if getattr(ts, "tzinfo", None)
                    else ts.tz_localize("UTC").isoformat(),
                    "o": float(row["Open"]),
                    "h": float(row["High"]),
                    "l": float(row["Low"]),
                    "c": float(row["Close"]),
                    "v": float(row["Volume"] or 0),
                }
            )
        except Exception:
            continue
    return out


def norm_ts(value: str) -> str:
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.UTC)
        return d.astimezone(dt.UTC).isoformat()
    except ValueError:
        return str(value)


def main() -> int:
    token = sys.argv[1]
    assets = sys.argv[2:] or list(ASSETS)
    out = {"generated_at": dt.datetime.now(dt.UTC).isoformat(), "assets": {}}
    for symbol in assets:
        out["assets"][symbol] = {}
        for interval, (yf_interval, days) in INTERVALS.items():
            entry: dict = {"interval": interval, "days": days}
            try:
                api = fetch_api(token, symbol, interval, days)
                api_bars = api.get("bars") or []
                entry["api"] = {
                    "provider": api.get("provider"),
                    "count": len(api_bars),
                    "first": api_bars[0]["t"] if api_bars else None,
                    "last": api_bars[-1]["t"] if api_bars else None,
                    "freshness": api.get("freshness"),
                }
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"api: {e}"
                out["assets"][symbol][interval] = entry
                continue
            try:
                prov = fetch_provider(ASSETS[symbol], yf_interval, days)
                entry["provider"] = {
                    "count": len(prov),
                    "first": prov[0]["t"] if prov else None,
                    "last": prov[-1]["t"] if prov else None,
                    "sample": prov[:2] + prov[-2:],
                }
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"provider: {e}"
                out["assets"][symbol][interval] = entry
                continue

            # Diff over the overlapping timestamps.
            api_map = {norm_ts(b["t"]): b for b in api_bars}
            mismatches = []
            compared = 0
            for p in prov:
                key = norm_ts(p["t"])
                a = api_map.get(key)
                if a is None:
                    continue
                compared += 1
                for field in ("o", "h", "l", "c"):
                    if not math.isclose(float(a[field]), float(p[field]), rel_tol=1e-6, abs_tol=1e-6):
                        mismatches.append(
                            {"t": key, "field": field, "api": a[field], "provider": p[field]}
                        )
                        break
                if len(mismatches) > 20:
                    break
            entry["comparison"] = {
                "overlapping_timestamps": compared,
                "mismatch_count": len(mismatches),
                "mismatches": mismatches[:20],
                "api_only": len(set(api_map) - {norm_ts(p["t"]) for p in prov}),
                "provider_only": len({norm_ts(p["t"]) for p in prov} - set(api_map)),
                "api_only_sample": sorted(set(api_map) - {norm_ts(p["t"]) for p in prov})[:3],
                "provider_only_sample": sorted(
                    {norm_ts(p["t"]) for p in prov} - set(api_map)
                )[:3],
                "api_sorted": [norm_ts(b["t"]) for b in api_bars]
                == sorted(norm_ts(b["t"]) for b in api_bars),
                "api_duplicates": len(api_bars) - len({norm_ts(b["t"]) for b in api_bars}),
                "future_timestamps": sum(
                    1
                    for b in api_bars
                    if dt.datetime.fromisoformat(norm_ts(b["t"]))
                    > dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)
                ),
            }
            out["assets"][symbol][interval] = entry
    print("PHASE3_JSON " + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
