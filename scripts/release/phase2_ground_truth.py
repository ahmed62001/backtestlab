"""Phase 2 ground truth: read persisted equity curves with raw SQL.

Runs inside the backend container (DATABASE_URL is provided there). Uses only
psycopg + json — it does not import the application's engine or matcher, so it
is an independent oracle.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg

RUN_IDS = sys.argv[1:] or ["bt-b3889491", "bt-7477a5a2", "bt-566e6959"]


def main() -> int:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    out = {}
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for rid in RUN_IDS:
                cur.execute(
                    "select id, user_id, asset, status, data_provider, data_interval, "
                    "data_start, data_end, config_json, result_json from backtests where id = %s",
                    (rid,),
                )
                row = cur.fetchone()
                if row is None:
                    out[rid] = {"error": "not_found"}
                    continue
                (
                    bid,
                    user_id,
                    asset,
                    status,
                    provider,
                    interval,
                    dstart,
                    dend,
                    config_json,
                    result_json,
                ) = row
                result = json.loads(result_json or "{}")
                equity = result.get("equity") or []
                values = [p.get("strategy") for p in equity if isinstance(p, dict)]
                values = [float(v) for v in values if isinstance(v, (int, float))]
                dates = [p.get("date") for p in equity if isinstance(p, dict)]
                expected = [p for p in equity if isinstance(p, dict)]
                out[rid] = {
                    "run_id": bid,
                    "user_id": user_id,
                    "asset": asset,
                    "status": status,
                    "provider": provider,
                    "interval": interval,
                    "data_start": dstart,
                    "data_end": dend,
                    "config": json.loads(config_json or "{}"),
                    "point_count": len(equity),
                    "timestamps_returned": len(dates),
                    "first_timestamp": dates[0] if dates else None,
                    "last_timestamp": dates[-1] if dates else None,
                    "first_equity": values[0] if values else None,
                    "last_equity": values[-1] if values else None,
                    "min_equity": min(values) if values else None,
                    "max_equity": max(values) if values else None,
                    "duplicate_timestamp_count": len(dates) - len(set(dates)),
                    "null_equity_count": sum(1 for v in values if v is None),
                    "invalid_point_count": len(expected) - len(values),
                }
    print("GROUND_TRUTH_JSON " + json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
