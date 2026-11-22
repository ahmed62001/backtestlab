"""Compatibility entry point: ``python -m app.data_store.cli``.

The implementation lives in :mod:`app.cli`; this shim keeps the documented
Phase 4 command path working.
"""

from __future__ import annotations

from app.cli import main

if __name__ == "__main__":
    main()
