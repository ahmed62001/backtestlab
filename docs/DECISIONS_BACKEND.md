# Backend decisions (append-only; newest first)

8. 2026-10-18 REAL vendor engine: in-process GlobalEquityEngine chosen over
   subprocess/HTTP (evidence: vendor_smoke.json + golden match <1e-9).
   Old claim "deterministic engine mirrors vendor semantics" retired; GBM code
   demoted to synthetic_engine.py, ENGINE_MODE=test only.
9. 2026-10-18 CryptoEngine (perpetuals) rejected at adapter boundary; spot
   equity allowlist AAPL/MSFT/NVDA/TSLA/AMD/SPY/2222.SR/1120.SR.
10. 2026-10-18 LocalCsvProvider license_class=dev_only; commercial provider
    choice left OWNER-ONLY behind DataProvider interface + BILLING license gate.
11. 2026-10-18 Templates are data (catalog in synthetic_engine.py TEMPLATES) +
    pure signal functions (signals.py); no exec/eval (grep test).
12. Frontend still hardcodes 5 templates — new 6 ids exposed via /templates;
    frontend addition deferred to Phase 8 (minimal change, recorded here).

---
Prior (demo track):
1. SQLite via SQLAlchemy 2.x (Postgres-portable models) — free-tier, zero-ops; DATABASE_URL switch ready.
2. Local JWT auth (SHA-256 + PyJWT) as default; Supabase provider interface reserved (AUTH_PROVIDER) — offline-first, no external dep.
3. In-process deterministic engine instead of live vendor import — vendor tree is agent/LLM-centric; importing it would add heavy deps + LLM quota risk. Adapter preserves interface; vendor LICENSE kept + version pinned.
4. Synchronous job completion (status done) — matches mock observable behavior; queue/progress extension point reserved.
5. Daily limits free=3/pro=100 enforced atomically per request (SQLite write in same txn as job insert).
6. Billing stub 501 NOT_AVAILABLE; webhook scaffold idempotent stub.
7. No PDF dep (license/weight); printable HTML report suffices v1.
