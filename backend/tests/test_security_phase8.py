
import pytest
from fastapi.testclient import TestClient


def test_security_redaction_and_headers():
    from app.main import create_app, redact_url_keys

    app = create_app()
    c = TestClient(app, raise_server_exceptions=False)

    # 1. URL key redaction
    raw_url = "https://api.example.com/v1/data?symbol=AAPL&apikey=secret12345&foo=bar"
    redacted = redact_url_keys(raw_url)
    assert "secret12345" not in redacted
    assert "apikey=***REDACTED***" in redacted

    raw_bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
    redacted_bearer = redact_url_keys(raw_bearer)
    assert "eyJhbG" not in redacted_bearer
    assert "Bearer ***REDACTED***" in redacted_bearer

    # 2. Cache-Control: no-store header on protected endpoints
    r = c.get("/health")
    assert r.status_code == 200
    assert "cache-control" not in r.headers

    # Register to get token
    rr = c.post(
        "/api/v1/auth/register",
        json={"name": "SecTest", "email": "sec@test.com", "password": "password123"},
    )
    assert rr.status_code == 201
    tok = rr.json()["token"]
    assert rr.headers.get("cache-control") == "no-store"
    assert rr.headers.get("x-content-type-options") == "nosniff"

    # Protected endpoints have no-store
    h = {"Authorization": f"Bearer {tok}"}
    me_resp = c.get("/api/v1/auth/me", headers=h)
    assert me_resp.headers.get("cache-control") == "no-store"

    usage_resp = c.get("/api/v1/usage", headers=h)
    assert usage_resp.headers.get("cache-control") == "no-store"


def test_csv_upload_security_guards():
    from app.data_providers.csv_upload import ProviderError, validate_upload_csv

    # 1. Formula injection rejection
    formula_csv = b"date,open,high,low,close,volume\n2024-01-01,=SUM(A1:A10),105,95,100,1000\n"
    with pytest.raises(ProviderError) as ei:
        validate_upload_csv(formula_csv, "AAPL")
    assert ei.value.code == "BAD_INPUT"
    assert "formula-injection" in str(ei.value)

    # 2. Max rows limit
    # Generate CSV with 5001 rows
    lines = ["date,open,high,low,close,volume"]
    for i in range(5001):
        lines.append(f"2024-01-01,{i},{i + 1},{i - 1},{i},100")
    huge_csv = "\n".join(lines).encode()

    with pytest.raises(ProviderError) as ei2:
        validate_upload_csv(huge_csv, "AAPL")
    assert ei2.value.code == "BAD_INPUT"
    assert "rows limit" in str(ei2.value)


def test_prod_boot_validation(monkeypatch):
    import app.auth as auth
    from app.auth import validate_prod_boot

    # Dev mode passes
    monkeypatch.setenv("ENV", "dev")
    validate_prod_boot()

    # Production mode fails fast with weak secret. `SECRET` is read at import
    # time, so patch the module value as well as the environment.
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LOCAL_JWT_SECRET", "dev-secret-change-me")
    monkeypatch.setattr(auth, "SECRET", "dev-secret-change-me")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://btlab:not-a-real-password@localhost:5432/btlab"
    )
    monkeypatch.setenv("ENGINE_MODE", "vendor")

    with pytest.raises(RuntimeError) as ei:
        validate_prod_boot()
    assert "REFUSE_BOOT" in str(ei.value)
    assert "LOCAL_JWT_SECRET" in str(ei.value)

    # The shipped .env.example placeholder is long enough but must still be
    # refused: a known example value is not a secret.
    monkeypatch.setattr(auth, "SECRET", "change-me-to-a-random-32-plus-char-secret")
    with pytest.raises(RuntimeError) as ei2:
        validate_prod_boot()
    assert "LOCAL_JWT_SECRET" in str(ei2.value)

