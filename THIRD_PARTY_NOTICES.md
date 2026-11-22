# Third-party notices

## Vibe-Trading (MIT)
- Source: https://github.com/HKUDS/Vibe-Trading @ c546e877274e7d36056c042808e1a875d9081eb9 (main, 2026-10-18)
- Copyright (c) 2026 Vibe-Trading Contributors; LICENSE: backend/vendor/Vibe-Trading/LICENSE (MIT, intact).
- Used for: RUNTIME backtest engine (in-process GlobalEquityEngine via
  backend/app/adapter.py::VibeTradingEngine) + signal/data reference.
  No LLM in run path. Commit pinned: c546e87 (grafted HEAD, main).

## Backend deps (all permissive)
- fastapi, uvicorn, SQLAlchemy, pydantic(+settings), PyJWT, httpx, pytest — MIT/Apache/BSD family. No AGPL/GPL-network-copyleft. No Fincept Terminal anywhere.
