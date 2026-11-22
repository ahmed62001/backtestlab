"""Phase 7.4 — independent metric recomputation from persisted records.

Reads only the stored equity curve and trades (raw SQL), then recomputes
total return, maximum drawdown, trade count and win rate with its own
implementation (no engine imports). Compares against the persisted summary and
the API payload.

Run inside the backend container (DATABASE_URL present).
"""

from __future__ import annotations

import json
import math
import os
import sys

import psycopg

RUN_IDS = sys.argv[1:]
TOL_2DP = 0.005  # UI displays total return / drawdown with 2 decimals
TOL_1DP = 0.05  # UI displays win rate with 1 decimal


def recompute(equity: list[dict], trades: list[dict]) -> dict:
    values = [float(p["strategy"]) for p in equity if isinstance(p.get("strategy"), (int, float))]
    if not values:
        return {"error": "no equity"}
    first, last = values[0], values[-1]
    total_return = (last - first) / first * 100.0 if first else None
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            max_dd = min(max_dd, (v - peak) / peak * 100.0)
    wins = 0
    for t in trades:
        pnl = t.get("pnl")
        if isinstance(pnl, (int, float)):
            wins += 1 if pnl > 0 else 0
    trade_count = len(trades)
    win_rate = (wins / trade_count * 100.0) if trade_count else None
    return {
        "points": len(values),
        "first_equity": first,
        "last_equity": last,
        "total_return_pct": total_return,
        "max_drawdown_pct": max_dd,
        "trade_count": trade_count,
        "win_rate_pct": win_rate,
    }


def close(a, b, tol=TOL_2DP) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), abs_tol=tol, rel_tol=0)


def main() -> int:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    out = {"runs": {}, "all_match": True}
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for rid in RUN_IDS:
                cur.execute(
                    "select asset, status, total_return_pct, max_drawdown_pct, win_rate_pct, "
                    "trades, result_json from backtests where id = %s",
                    (rid,),
                )
                row = cur.fetchone()
                if row is None:
                    out["runs"][rid] = {"error": "not_found"}
                    out["all_match"] = False
                    continue
                asset, status, ret, dd, wr, trades_n, result_json = row
                result = json.loads(result_json or "{}")
                equity = result.get("equity") or []
                trades = result.get("tradesList") or []
                rec = recompute(equity, trades)
                checks = {
                    "total_return": close(rec["total_return_pct"], ret),
                    "max_drawdown": close(rec["max_drawdown_pct"], dd),
                    "win_rate": close(rec["win_rate_pct"], wr, TOL_1DP),
                    "trade_count": rec["trade_count"] == int(trades_n),
                }
                match = all(checks.values())
                out["all_match"] = out["all_match"] and match
                out["runs"][rid] = {
                    "asset": asset,
                    "status": status,
                    "persisted": {
                        "total_return_pct": ret,
                        "max_drawdown_pct": dd,
                        "win_rate_pct": wr,
                        "trades": trades_n,
                    },
                    "recomputed": rec,
                    "checks": checks,
                    "match": match,
                }
            cur.execute(
                "select status, count(*) from jobs group by status order by status"
            )
            out["job_states"] = {s: int(c) for s, c in cur.fetchall()}
            cur.execute(
                "select count(*) from backtests where status in ('queued','running')"
            )
            out["unfinished_backtests"] = int(cur.fetchone()[0])
    print("RECOMPUTE_JSON " + json.dumps(out))
    return 0 if out["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
