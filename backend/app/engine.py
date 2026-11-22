"""Backtest engine facade: strict ENGINE_MODE, no silent fallback.

ENGINE_MODE=vendor -> VibeTradingEngine (real vendor in-process). This is the
                      ONLY mode allowed in production. If the vendor code is
                      unavailable or fails at runtime, the request fails with a
                      clear error (HTTP 503 ENGINE_UNAVAILABLE) — the local
                      imitation is NEVER used as a fallback.
ENGINE_MODE=local   -> local synthetic GBM engine (dev/demo only). Explicit
                      opt-in; refused when ENV=production.
Any other value     -> RuntimeError at import (refuse boot).
"""

from __future__ import annotations

import os
from typing import Any

ENGINE_MODE = os.environ.get("ENGINE_MODE", "vendor")
ENV = os.environ.get("ENV", "dev")
VALID_MODES = ("vendor", "local")

if ENGINE_MODE not in VALID_MODES:
    raise RuntimeError(
        f"REFUSE_BOOT: unknown ENGINE_MODE={ENGINE_MODE!r} (valid: {', '.join(VALID_MODES)})"
    )
if ENV == "production" and ENGINE_MODE != "vendor":
    raise RuntimeError(
        f"REFUSE_BOOT: ENGINE_MODE must be 'vendor' in production (got {ENGINE_MODE!r})"
    )

VENDOR_COMMIT = "c546e877274e7d36056c042808e1a875d9081eb9"

# Catalog + disclaimers stay data-only (importable in every mode).
from .synthetic_engine import ASSETS, DISCLAIMER, TEMPLATES  # noqa: E402,F401


def engine_block() -> dict[str, Any]:
    """The `engine` block attached to every backtest result / API response."""
    if ENGINE_MODE == "vendor":
        return {
            "mode": "vendor",
            "engineName": "vibe-trading:GlobalEquityEngine",
            "vendorCommit": VENDOR_COMMIT,
            "vendorVersionOrRef": VENDOR_COMMIT,
        }
    return {
        "mode": "local",
        "engineName": "synthetic-gbm(local)",
        "vendorCommit": None,
        "vendorVersionOrRef": None,
    }
