#!/usr/bin/env python3
"""MANUAL-ONLY smoke test against REAL data providers (needs network).

Never run in CI. Usage (from backend/):

    python3 scripts/smoke_providers.py                # free providers
    python3 scripts/smoke_providers.py --with-keys    # + keyed provider
    ALPHAVANTAGE_API_KEY=... python3 scripts/smoke_providers.py --with-keys

Each provider is exercised end-to-end: fetch -> normalize -> provenance.
Exit code 0 = all exercised providers healthy.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading" / "agent")
)

CASES = [
    # (provider_id, symbol, start, end)
    ("stooq", "AAPL", "2024-01-01", "2024-06-30"),
    ("yfinance", "AAPL", "2024-01-01", "2024-06-30"),
    ("ccxt", "BTC/USDT", "2024-01-01", "2024-06-30"),
]
KEYED_CASES = [
    ("alphavantage", "IBM", "2024-01-01", "2024-06-30"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--with-keys", action="store_true", help="also exercise keyed providers (needs env keys)"
    )
    args = ap.parse_args()
    os.environ.setdefault("DATA_CACHE_DIR", "/tmp/btlab_smoke_cache")
    from app.data_providers.base import ProviderError
    from app.data_providers.registry import get_provider

    cases = CASES + (KEYED_CASES if args.with_keys else [])
    failures = 0
    for pid, symbol, start, end in cases:
        try:
            p = get_provider(pid)
            health = p.health_check()
            if not health["available"]:
                print(f"[SKIP] {pid}: unavailable ({health['detail']})")
                continue
            res = p.fetch_ohlcv_cached(symbol, start, end)
            df = res.frame
            prov = res.provenance
            print(
                f"[ OK ] {pid} {symbol}: {len(df)} bars "
                f"{prov['start']}..{prov['end']} hash={prov['dataHash'][:12]} "
                f"cache={prov['cache']} adjusted={prov['adjusted']}"
            )
            print(df.tail(2).to_string())
        except ProviderError as e:
            print(f"[FAIL] {pid} {symbol}: {e}")
            failures += 1
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {pid} {symbol}: {type(e).__name__}: {e}")
            failures += 1
    print(f"\n{len(cases) - failures}/{len(cases)} exercised OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
