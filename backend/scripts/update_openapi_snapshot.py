"""Generate (or check) docs/openapi.snapshot.json from the FastAPI app.

Usage:
    python scripts/update_openapi_snapshot.py          # rewrite snapshot
    python scripts/update_openapi_snapshot.py --check  # fail on drift
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT.parent / "docs" / "openapi.snapshot.json"

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bt_openapi_snapshot.db")
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("ENGINE_MODE", "local")
sys.path.insert(0, str(ROOT))


def build_snapshot() -> dict:
    from app.main import app

    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when the committed snapshot is stale"
    )
    args = parser.parse_args()

    snapshot = build_snapshot()
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if args.check:
        existing = SNAPSHOT.read_text() if SNAPSHOT.exists() else ""
        if existing != rendered:
            print(f"OpenAPI snapshot is stale: {SNAPSHOT}", file=sys.stderr)
            print("Run: python scripts/update_openapi_snapshot.py", file=sys.stderr)
            return 1
        print("OpenAPI snapshot is current.")
        return 0

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered)
    print(f"Wrote {SNAPSHOT} ({len(snapshot.get('paths', {}))} paths).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
