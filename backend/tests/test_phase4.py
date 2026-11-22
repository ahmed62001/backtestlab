"""Phase 4 gates: argon2id, migration, rate limit, prod boot, supabase JWKS."""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def test_argon2_new_hash_and_verify():
    from app.auth import hash_pw, verify_pw

    h = hash_pw("a@t.com", "password123")
    assert h.startswith("argon2:")
    ok, _up = verify_pw("a@t.com", "password123", h)
    assert ok
    bad, _ = verify_pw("a@t.com", "wrongpass1", h)
    assert not bad


def test_legacy_sha256_migrates_on_login():
    import hashlib

    from app.auth import verify_pw

    legacy = hashlib.sha256(b"mig@t.com::oldpass99").hexdigest()
    ok, upgraded = verify_pw("mig@t.com", "oldpass99", legacy)
    assert ok and upgraded and upgraded.startswith("argon2:")
    ok2, _ = verify_pw("mig@t.com", "oldpass99", upgraded)
    assert ok2


def test_rate_limit_blocks_after_burst():
    from app import auth

    auth._attempts.clear()
    auth.LOGIN_MAX_PER_MIN = 3
    try:
        assert auth.rate_limit("k")
        assert auth.rate_limit("k")
        assert auth.rate_limit("k")
        assert not auth.rate_limit("k")
    finally:
        auth.LOGIN_MAX_PER_MIN = int(os.environ.get("LOGIN_MAX_PER_MIN", "20"))
        auth._attempts.clear()


def test_prod_boot_validation_refuses_weak():
    import subprocess

    env = {
        **os.environ,
        "ENV": "production",
        "LOCAL_JWT_SECRET": "short",
        "CORS_ORIGINS": "*",
        "DATABASE_URL": "sqlite:///./x.db",
        "DEBUG": "true",
        "ENGINE_MODE": "local",
    }
    r = subprocess.run(
        [
            "python3",
            "-c",
            "import sys; sys.path.insert(0,'.'); from app.main import create_app; create_app()",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=".",
        env=env,
    )
    assert r.returncode != 0 and "REFUSE_BOOT" in (r.stdout + r.stderr)


def test_no_billing_startup_refusal():
    """License/billing startup gate removed by product decision (2026-10-19):
    BILLING_ENABLED=true alone must NOT block boot."""
    import subprocess

    env_ok = {
        **os.environ,
        "ENV": "production",
        "LOCAL_JWT_SECRET": "x" * 40,
        "CORS_ORIGINS": "https://a.example",
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/x",
        "DEBUG": "false",
        "ENGINE_MODE": "vendor",
        "BILLING_ENABLED": "true",
    }
    r2 = subprocess.run(
        [
            "python3",
            "-c",
            "import sys; sys.path.insert(0,'.'); from app.auth import validate_prod_boot; validate_prod_boot(); print('BOOT_OK')",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=".",
        env=env_ok,
    )
    assert "BOOT_OK" in (r2.stdout + r2.stderr), (r2.stdout, r2.stderr)


def test_non_local_auth_provider_refused_in_production(monkeypatch):
    import pytest
    from app.auth import validate_prod_boot

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("LOCAL_JWT_SECRET", "a-very-strong-production-secret-32chars!")
    monkeypatch.setenv("CORS_ORIGINS", "https://backtestlab.example.com")
    monkeypatch.setenv("ENGINE_MODE", "vendor")
    with pytest.raises(RuntimeError, match="AUTH_PROVIDER"):
        validate_prod_boot()
