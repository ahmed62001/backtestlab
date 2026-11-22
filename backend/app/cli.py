"""CLI commands for BacktestLab (Phase 4).

Provides: ingest, ingest-file, backfill, list, stats, verify, purge, export.
Universe YAMLs for symbol management.
Deterministic synthetic seed control.

Run as ``python -m app.cli <command>`` or ``python -m app.data_store.cli``.
"""

from __future__ import annotations

import argparse
import csv
import sys

import pandas as pd

from app.data_providers.base import ProviderError
from app.data_providers.registry import (
    _ALL,
    default_provider_id,
    enabled_ids,
    provider_infos,
)
from app.data_store.normalize import normalize_bars
from app.data_store.repository import (
    ensure_instrument,
    purge_all,
    purge_bars,
    purge_coverage,
    read_bars_for_symbol,
    store_stats,
    upsert_bars,
    upsert_coverage,
    verify_coverage_hashes,
)
from app.data_store.service import (
    MarketDataService,
    _canonical_hash,
    _store_timeframe,
    coverage_end_after_last_bar,
    is_enabled,
)
from app.data_store.symbols import load_universe
from app.data_store.ttl import expires_at_for
from app.db import init_db


def _frame_to_list(df: pd.DataFrame) -> list[dict]:
    rows = []
    for ts, row in df.iterrows():
        rows.append(
            {
                "ts": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if row["volume"] is not None else None,
            }
        )
    return rows


def cmd_ingest(args):
    """Ingest data from a provider for a symbol and date range."""
    init_db()
    provider_id = args.provider
    if provider_id not in _ALL:
        print(f"Unknown provider: {provider_id}")
        print(f"Available: {list(_ALL.keys())}")
        sys.exit(1)

    try:
        df, prov = MarketDataService().get_bars(
            provider_id,
            args.symbol,
            args.interval,
            args.start,
            args.end,
            adjusted=bool(getattr(args, "adjusted", False)),
            refresh=bool(getattr(args, "refresh", False)),
        )
        print(
            f"Fetched {len(df)} bars for {args.symbol} from {provider_id} "
            f"(retrieval={prov['retrieval']})"
        )
        print(f"Date range: {df.index[0].date()} to {df.index[-1].date()}")
        print(f"dataHash: {prov['data_hash']}")
    except ProviderError as e:
        print(f"Provider error: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}")
        sys.exit(1)


def cmd_ingest_file(args):
    """Ingest data from a CSV file into the market data store.

    Uses the same normalization/validation pipeline as every other ingestion
    path. Invalid rows reject the file; exact duplicate timestamps are collapsed
    before hashing/coverage so ``verify`` matches what was stored (D-PH3-17).
    """
    init_db()
    csv_path = getattr(args, "file", None) or args.csv_path
    provider_id = args.provider or "csv_upload"
    symbol = args.symbol
    interval = _store_timeframe(args.interval or "1D")
    asset_class = getattr(args, "asset_class", None) or "equity"

    try:
        raw = pd.read_csv(csv_path)
        norm = normalize_bars(raw, symbol, provider_id, interval)
        if norm.frame.empty or norm.rows_invalid:
            reasons = [
                w["message"]
                for w in norm.warnings
                if w["code"].startswith(("DROPPED_", "BAD_INPUT")) or w["code"] == "EMPTY_DATA"
            ]
            detail = "; ".join(reasons) or "no valid data found in CSV"
            raise ValueError(f"invalid CSV data: {detail}")

        bars_list = _frame_to_list(norm.frame)
        start = bars_list[0]["ts"]
        end_exclusive = coverage_end_after_last_bar(interval, bars_list[-1]["ts"])
        inst_id = ensure_instrument(symbol, asset_class)
        upsert_bars(inst_id, provider_id, interval, bars_list, adjusted=False)
        upsert_coverage(
            inst_id,
            provider_id,
            interval,
            start,
            end_exclusive,
            len(bars_list),
            _canonical_hash(bars_list),
            adjusted=False,
            status="complete",
            expires_at=expires_at_for(interval, end_exclusive),
        )
        print(f"Stored {len(bars_list)} bars for {symbol} from {csv_path}.")
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}")
        sys.exit(1)


def cmd_list(args):
    """List all enabled providers with their capabilities."""
    enabled = enabled_ids()
    catalog = provider_infos()
    by_id = {it["id"]: it for it in catalog["items"]}

    print(f"Enabled Data Providers (default: {default_provider_id()})")
    print("=" * 60)
    for pid in enabled:
        if pid in by_id:
            item = by_id[pid]
            print(f"  {pid}:")
            print(f"    Category: {item.get('category', 'N/A')}")
            print(f"    Markets: {item.get('markets', [])}")
            print(f"    Intervals: {item.get('intervals', [])}")
            print(f"    Key required: {item.get('requiresKey', False)}")
            print(f"    Key env: {item.get('requiresKeyEnv', 'N/A')}")
            print(f"    Rate limit: {item.get('rateLimitPerMinute', 0)}/min")
            print(f"    Adjusted: {item.get('supportsAdjusted', False)}")
            print(f"    Enabled: {item.get('enabled', False)}")
            if item.get("storeSummary"):
                print(
                    f"    Store: {item['storeSummary'].get('instrumentCount', 0)} "
                    f"instruments, {item['storeSummary'].get('timeframes', [])}"
                )
            print()


def cmd_stats(args):
    """Show statistics about stored data."""
    init_db()
    stats = store_stats()
    print("Data Store Statistics")
    print("=" * 40)
    print(f"Store enabled: {is_enabled()}")
    print(f"Enabled providers: {len(enabled_ids())}")
    print(f"Instruments: {stats['instruments']}")
    print(f"Bars: {stats['bars']}")
    print(f"Coverage rows: {stats['coverageRows']}")
    print(f"Oldest bar: {stats['oldest']}")
    print(f"Newest bar: {stats['newest']}")
    print(f"Last ingested: {stats['lastIngestedAt']}")


def cmd_verify(args):
    """Verify coverage data hashes and report corrupted rows."""
    init_db()
    print("Data Integrity Verification")
    print("=" * 40)

    results = verify_coverage_hashes()
    bad = [r for r in results if not r["ok"]]
    for r in results[:20]:
        mark = "✓" if r["ok"] else "✗"
        print(
            f"  {mark} {r['provider']} {r['timeframe']} {r['instrumentId']} "
            f"{r['rangeStart']}..{r['rangeEnd']} ({r['rows']} bars)"
        )
        if not r["ok"]:
            print(f"      expected {r['expected']}")
            print(f"      actual   {r['actual']}")
    print(f"\nChecked {len(results)} coverage rows; {len(bad)} corrupted.")
    if bad:
        sys.exit(1)


def cmd_purge(args):
    """Purge stored data (optionally filtered by provider/symbol/date)."""
    init_db()
    provider = getattr(args, "provider", None)
    symbol = getattr(args, "symbol", None)
    older_than = getattr(args, "older_than", None)
    try:
        if provider or symbol or older_than:
            deleted = purge_bars(provider=provider, symbol=symbol, older_than=older_than)
            print(f"Purged {deleted} bars matching filters.")
        else:
            bars = purge_all()
            coverage = purge_coverage()
            print(f"Purged {bars} bars and {coverage} coverage rows.")
    except Exception as e:  # noqa: BLE001
        print(f"Purge error: {e}")
        sys.exit(1)


def cmd_export(args):
    """Export stored data to CSV."""
    init_db()
    symbol = args.symbol or "AAPL"
    start = args.start or "2022-01-01"
    end = args.end or "2022-12-31"
    interval = _store_timeframe(args.interval or "1D")

    try:
        bars = read_bars_for_symbol(symbol, interval, start, end)
        if not bars:
            print(f"No data found for {symbol} in {start}..{end}")
            sys.exit(1)

        output = args.output or f"{symbol}_{interval}.csv"
        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "open", "high", "low", "close", "volume"])
            for row in bars:
                writer.writerow(
                    [
                        row["ts"].split("T")[0],
                        f"{row['open']:.6f}",
                        f"{row['high']:.6f}",
                        f"{row['low']:.6f}",
                        f"{row['close']:.6f}",
                        f"{float(row['volume'] or 0):.6f}",
                    ]
                )
        print(f"Exported {len(bars)} bars to {output}")
    except Exception as e:  # noqa: BLE001
        print(f"Export error: {e}")
        sys.exit(1)


def cmd_seed(args):
    """Deterministic synthetic seed: populate the market data store with
    GBM bars for every symbol in a universe YAML. No network, no keys."""
    init_db()
    from app.data_providers.synthetic import SyntheticProvider

    universe = load_universe(getattr(args, "universe", None))
    provider = SyntheticProvider()
    symbols = [s["canonical"] for s in universe.get("symbols", [])]
    if not symbols:
        symbols = ["AAPL", "BTC-USD", "ETH-USD", "EURUSD"]

    start = args.start or "2022-01-01"
    end = args.end or "2023-12-31"
    interval = _store_timeframe(args.interval or "1D")
    total = 0

    for sym in symbols:
        try:
            df = provider.fetch_ohlcv(sym, start, end, "1D")
            inst_id = ensure_instrument(sym, "equity")
            bars_list = _frame_to_list(df)
            upsert_bars(
                inst_id,
                provider.id,
                interval,
                bars_list,
                adjusted=getattr(provider, "adjusted", False),
            )
            upsert_coverage(
                inst_id,
                provider.id,
                interval,
                start,
                coverage_end_after_last_bar(interval, bars_list[-1]["ts"]),
                len(bars_list),
                _canonical_hash(bars_list),
                adjusted=getattr(provider, "adjusted", False),
                status="complete",
                expires_at=expires_at_for(interval, end),
            )
            total += len(bars_list)
            print(f"  {sym}: {len(bars_list)} bars (synthetic)")
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: error: {e}")

    print(f"Seed complete: {total} bars stored for {len(symbols)} symbols.")


def cmd_reset_token(args):
    """Issue a single-use password-reset token for an operator to deliver."""
    init_db()
    from sqlalchemy import select

    from app.auth import issue_password_reset
    from app.db import SessionLocal, User

    email = str(getattr(args, "email", "") or "").strip().lower()
    if not email:
        print("Error: --email is required")
        sys.exit(1)
    s = SessionLocal()
    try:
        u = s.scalar(select(User).where(User.email == email))
        if u is None:
            print(f"No account for {email}")
            sys.exit(1)
        token = issue_password_reset(u.id)
    finally:
        s.close()
    print(token)


def cmd_backfill(args):
    """Fill missing data ranges for a universe, provider by provider."""
    init_db()
    universe = load_universe(getattr(args, "universe", None))
    symbols = [s["canonical"] for s in universe.get("symbols", [])]
    if not symbols:
        print("No symbols found in universe.")
        sys.exit(1)

    providers = [args.provider] if getattr(args, "provider", None) else [default_provider_id()]
    start = args.start or "2022-01-01"
    end = args.end or "2023-12-31"
    interval = args.interval or "1D"
    failures = 0
    print(f"Backfilling {len(symbols)} symbols via {providers}")

    for pid in providers:
        service = MarketDataService()
        for sym in symbols:
            try:
                _df, prov = service.get_bars(pid, sym, interval, start, end)
                print(f"  {pid}/{sym}: {prov['rows']} bars ({prov['retrieval']})")
            except ProviderError as e:
                failures += 1
                print(f"  {pid}/{sym}: {e.code}: {e}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  {pid}/{sym}: error: {e}")

    print(f"Backfill complete: {failures} failure(s).")
    if failures:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(prog="backtestlab", description="BacktestLab CLI (Phase 4)")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_ingest = subparsers.add_parser("ingest", help="Ingest data from a provider")
    p_ingest.add_argument("provider", help="Provider ID")
    p_ingest.add_argument("symbol", help="Symbol")
    p_ingest.add_argument("--start", default="2022-01-01")
    p_ingest.add_argument("--end", default="2022-12-31")
    p_ingest.add_argument("--interval", "--timeframe", default="1D")
    p_ingest.add_argument("--adjusted", action="store_true")
    p_ingest.add_argument("--refresh", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_ingest_file = subparsers.add_parser("ingest-file", help="Ingest from CSV file")
    p_ingest_file.add_argument("csv_path", nargs="?", help="Path to CSV file")
    p_ingest_file.add_argument(
        "--file", dest="file", default=None, help="Path to CSV file (alternative to positional)"
    )
    p_ingest_file.add_argument("--symbol", default="APISYM")
    p_ingest_file.add_argument("--provider", default="csv_upload")
    p_ingest_file.add_argument("--interval", "--timeframe", default="1D")
    p_ingest_file.add_argument("--asset-class", default="equity")
    p_ingest_file.set_defaults(func=cmd_ingest_file)

    p_list = subparsers.add_parser("list", help="List enabled providers")
    p_list.set_defaults(func=cmd_list)

    p_stats = subparsers.add_parser("stats", help="Show data store stats")
    p_stats.set_defaults(func=cmd_stats)

    p_verify = subparsers.add_parser("verify", help="Verify data integrity")
    p_verify.set_defaults(func=cmd_verify)

    p_purge = subparsers.add_parser("purge", help="Purge stored data")
    p_purge.add_argument("--provider", default=None)
    p_purge.add_argument("--symbol", default=None)
    p_purge.add_argument("--older-than", default=None)
    p_purge.set_defaults(func=cmd_purge)

    p_export = subparsers.add_parser("export", help="Export data to CSV")
    p_export.add_argument("symbol", nargs="?", default="AAPL")
    p_export.add_argument("--start", default="2022-01-01")
    p_export.add_argument("--end", default="2022-12-31")
    p_export.add_argument("--interval", "--timeframe", default="1D")
    p_export.add_argument("--output", default=None)
    p_export.set_defaults(func=cmd_export)

    p_backfill = subparsers.add_parser("backfill", help="Fill missing data ranges")
    p_backfill.add_argument(
        "--universe", default=None, help="Universe name/path (default: universe.yaml)"
    )
    p_backfill.add_argument(
        "--provider", default=None, help="Provider id (default: configured default)"
    )
    p_backfill.add_argument("--start", default="2022-01-01")
    p_backfill.add_argument("--end", default="2023-12-31")
    p_backfill.add_argument("--interval", "--timeframe", default="1D")
    p_backfill.set_defaults(func=cmd_backfill)

    p_seed = subparsers.add_parser("seed", help="Deterministic synthetic seed of the data store")
    p_seed.add_argument("--universe", default=None)
    p_seed.add_argument("--start", default=None)
    p_seed.add_argument("--end", default=None)
    p_seed.add_argument("--interval", "--timeframe", default="1D")
    p_seed.set_defaults(func=cmd_seed)

    p_reset = subparsers.add_parser(
        "reset-token", help="Issue a single-use password-reset token for an account"
    )
    p_reset.add_argument("--email", required=True)
    p_reset.set_defaults(func=cmd_reset_token)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
