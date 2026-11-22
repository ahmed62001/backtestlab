"""Contract test: API responses match docs/API_CONTRACT.md schemas (subset)."""

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def test_contract_shapes():
    import os

    import uuid

    os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_contract.db"
    with contextlib.suppress(OSError):
        pathlib.Path("/tmp/bt_contract.db").unlink()
    from app.main import create_app
    from fastapi.testclient import TestClient

    test_email = f"ct_{uuid.uuid4().hex[:6]}@t.com"
    c = TestClient(create_app(), raise_server_exceptions=False)
    r = c.post(
        "/api/v1/auth/register", json={"name": "CT", "email": test_email, "password": "password123"}
    )
    assert r.status_code == 201
    tok, user = r.json()["token"], r.json()["user"]
    # Refresh support (D-PH1-05) means register/login also return an access and
    # a rotating refresh token alongside the legacy ``token`` field.
    assert {"token", "access_token", "refresh_token", "user"} == set(r.json())
    assert {"id", "name", "email", "plan", "language", "createdAt"} <= set(user)
    h = {"Authorization": "Bearer " + tok}
    t = c.get("/api/v1/templates").json()
    assert {"items", "total"} == set(t) and t["total"] >= 11
    # Phase 2 contract: provider catalog + optional dataProvider on backtests
    dp = c.get("/api/v1/data-providers").json()
    assert {"items", "default", "enabled"} == set(dp) or {"items", "default", "enabled"} <= set(dp)
    assert any(x["id"] == dp["default"] for x in dp["items"])
    for it in dp["items"]:
        assert {
            "id",
            "nameEn",
            "nameAr",
            "markets",
            "intervals",
            "requiresKey",
            "available",
            "licenseClass",
            "enabled",
            "isDefault",
        } <= set(it)
    rb = c.post(
        "/api/v1/backtests",
        json={
            "templateId": "ma-crossover",
            "asset": "AAPL",
            "initialCapital": 10000,
            "feePct": 0.1,
            "params": {},
            "dataProvider": "local",
        },
        headers=h,
    )
    assert rb.status_code == 201, rb.text
    d = rb.json()
    for k in (
        "id",
        "templateId",
        "asset",
        "status",
        "totalReturnPct",
        "maxDrawdownPct",
        "sharpe",
        "winRatePct",
        "trades",
        "vsBuyHoldPct",
        "equity",
        "warnings",
        "costs",
        "provenance",
        "engine",
        "disclaimer",
        "dataProvider",
    ):
        assert k in d, k
    assert isinstance(d["engine"], dict)
    assert {"mode", "engineName", "vendorCommit", "vendorVersionOrRef"} == set(d["engine"])
    assert d["provenance"]["provider"] == "local"
    assert {"provider", "symbol", "interval", "start", "end", "rows", "dataHash"} <= set(
        d["provenance"]
    )
    assert isinstance(d["equity"][0], dict) and {
        "date",
        "strategy",
        "benchmark",
        "drawdown",
    } <= set(d["equity"][0])
    u = c.get("/api/v1/usage", headers=h).json()
    assert {"usedToday", "dailyLimit", "plan", "periodStart"} <= set(u)
    e = c.get("/health").json()
    assert e["ok"] is True


def test_openapi_snapshot_no_drift():
    """Generated OpenAPI paths/status codes match docs/openapi.snapshot.json."""
    import json
    import pathlib

    from app.main import create_app
    from fastapi.testclient import TestClient

    c = TestClient(create_app(), raise_server_exceptions=False)
    snapshot_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "openapi.snapshot.json"
    )
    committed = json.loads(snapshot_path.read_text())
    committed_paths = {k: sorted(v.keys()) for k, v in committed.get("paths", {}).items()}

    live = c.get("/openapi.json").json()
    live_paths = {k: sorted(v.keys()) for k, v in live.get("paths", {}).items()}

    missing = [p for p in committed_paths if p not in live_paths]
    extra = [p for p in live_paths if p not in committed_paths]
    assert not missing, f"OpenAPI paths removed: {missing}"
    assert not extra, f"OpenAPI paths added: {extra}"
    assert committed_paths == live_paths, (
        "OpenAPI path/method drift - regenerate with: "
        "python backend/scripts/update_openapi_snapshot.py"
    )
