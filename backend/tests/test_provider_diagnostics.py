"""Tests for Provider Diagnostics and Coverage Matrix endpoint (Section 8)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.data_providers.diagnostics import generate_diagnostics_report


def test_diagnostics_report_generation():
    report = generate_diagnostics_report()
    assert "generatedAt" in report
    assert "providers" in report
    assert "assetCoverageMatrix" in report
    assert report["totalProviders"] >= 12
    assert report["healthyProvidersCount"] > 0

    # Verify provider entry details
    twelvedata = next((p for p in report["providers"] if p["providerId"] == "twelvedata"), None)
    assert twelvedata is not None
    assert "crypto" in twelvedata["supportedAssetClasses"]
    assert "commodity" in twelvedata["supportedAssetClasses"]
    assert "configuredFallbackProvider" in twelvedata
    assert "rateLimitAndRestrictions" in twelvedata

    # Verify coverage matrix entries
    matrix = report["assetCoverageMatrix"]
    assert len(matrix) >= 10
    
    classes = [entry["assetClass"] for entry in matrix]
    assert any("crypto" in c.lower() for c in classes)
    assert any("precious metals" in c.lower() for c in classes)
    assert any("forex" in c.lower() for c in classes)
    assert any("stocks" in c.lower() or "equities" in c.lower() for c in classes)
    assert any("indices" in c.lower() for c in classes)
    assert any("energy" in c.lower() for c in classes)
    assert any("agricultural" in c.lower() for c in classes)

    for entry in matrix:
        assert "primaryProvider" in entry
        assert "fallbackProvider" in entry
        assert "verificationStatus" in entry
        assert "verifiedSymbols" in entry
        assert len(entry["verifiedSymbols"]) > 0


def test_diagnostics_api_endpoint_contract():
    client = TestClient(create_app(), raise_server_exceptions=False)
    resp = client.get("/api/v1/data-providers/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "assetCoverageMatrix" in data
    assert "providers" in data
    
    crypto_entry = next((e for e in data["assetCoverageMatrix"] if "crypto" in e["assetClass"].lower()), None)
    assert crypto_entry is not None
    assert crypto_entry["primaryProvider"] == "twelvedata"
    assert "binance_public" in crypto_entry["fallbackProvider"]

    energy_entry = next((e for e in data["assetCoverageMatrix"] if "energy" in e["assetClass"].lower()), None)
    assert energy_entry is not None
    assert energy_entry["primaryProvider"] == "yfinance"
