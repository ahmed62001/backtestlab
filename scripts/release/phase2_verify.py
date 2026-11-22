"""Phase 2 verification: persisted equity curves vs the API payload.

Runs inside the backend container. The oracle is raw SQL over ``result_json``;
the payload is produced by the application's own ``full()`` serializer (the same
function behind ``GET /api/v1/backtests/{id}``). It performs a point-by-point
comparison of timestamps and equity values.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import psycopg

RUN_IDS = sys.argv[1:] or ["bt-b3889491", "bt-7477a5a2", "bt-566e6959"]


def oracle(conn, rid):
    with conn.cursor() as cur:
        cur.execute(
            "select id, user_id, asset, result_json, config_json, data_start, data_end, "
            "data_interval, data_provider from backtests where id = %s",
            (rid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    bid, user_id, asset, result_json, config_json, dstart, dend, interval, provider = row
    result = json.loads(result_json or "{}")
    equity = result.get("equity") or []
    values = [float(p["strategy"]) for p in equity if isinstance(p.get("strategy"), (int, float))]
    dates = [str(p.get("date")) for p in equity if p.get("date") is not None]
    return {
        "run_id": bid,
        "user_id": user_id,
        "asset": asset,
        "provider": provider,
        "interval": interval,
        "data_start": dstart,
        "data_end": dend,
        "config": json.loads(config_json or "{}"),
        "point_count": len(equity),
        "first_timestamp": dates[0] if dates else None,
        "last_timestamp": dates[-1] if dates else None,
        "first_equity": values[0] if values else None,
        "last_equity": values[-1] if values else None,
        "min_equity": min(values) if values else None,
        "max_equity": max(values) if values else None,
        "duplicate_timestamp_count": len(dates) - len(set(dates)),
        "null_equity_count": sum(1 for p in equity if p.get("strategy") is None),
        "raw_equity": equity,
    }


def main() -> int:
    sys.path.insert(0, "/app")
    os.environ.setdefault("ENV", "dev")
    from app.db import Backtest, SessionLocal
    from app.main import full

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    out = {"runs": {}, "comparisons": {}, "generated_at": dt.datetime.now(dt.UTC).isoformat()}
    with psycopg.connect(url) as conn:
        for rid in RUN_IDS:
            o = oracle(conn, rid)
            if o is None:
                out["runs"][rid] = {"error": "not_found"}
                continue
            raw = o.pop("raw_equity")
            s = SessionLocal()
            try:
                b = s.get(Backtest, rid)
                payload = full(b) if b is not None else None
            finally:
                s.close()
            served = payload.get("equity", []) if payload else []
            mismatches = []
            if len(served) != len(raw):
                mismatches.append(
                    {"kind": "count", "expected": len(raw), "actual": len(served)}
                )
            for i, (exp, act) in enumerate(zip(raw, served)):
                if str(exp.get("date")) != str(act.get("date")) or float(
                    exp.get("strategy")
                ) != float(act.get("strategy")):
                    mismatches.append(
                        {
                            "kind": "point",
                            "index": i,
                            "expected": [exp.get("date"), exp.get("strategy")],
                            "actual": [act.get("date"), act.get("strategy")],
                        }
                    )
                    if len(mismatches) > 10:
                        break
            o["api"] = {
                "point_count": len(served),
                "first_timestamp": served[0]["date"] if served else None,
                "last_timestamp": served[-1]["date"] if served else None,
                "first_equity": served[0]["strategy"] if served else None,
                "last_equity": served[-1]["strategy"] if served else None,
                "result_meta": (payload or {}).get("resultMeta"),
            }
            o["mismatch_count"] = len(mismatches)
            o["mismatches"] = mismatches[:10]
            out["runs"][rid] = o

    # Pairwise alignment check for the AAPL comparison pair.
    ids = [r for r in RUN_IDS if r in out["runs"] and "point_count" in out["runs"][r]]
    if len(ids) >= 2:
        a, b = ids[0], ids[1]
        out["comparisons"]["pair"] = {
            "a": a,
            "b": b,
            "a_points": out["runs"][a]["point_count"],
            "b_points": out["runs"][b]["point_count"],
            "a_first": out["runs"][a]["first_timestamp"],
            "a_last": out["runs"][a]["last_timestamp"],
            "b_first": out["runs"][b]["first_timestamp"],
            "b_last": out["runs"][b]["last_timestamp"],
        }
    print("PHASE2_JSON " + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
