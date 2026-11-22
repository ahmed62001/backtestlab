"""Release-candidate security regressions (RC hardening).

Covers the release-blocking findings fixed ahead of the first production
deployment:

* insecure/placeholder JWT secret accepted in production
* spoofable proxy headers used for rate-limit keys
* unbounded in-process rate limiter + unthrottled /forgot
* non-atomic refresh-token rotation
* unauthenticated provider catalog doing live network work on every request
  and echoing unredacted upstream errors
* unenforced queue concurrency cap
* CSV upload symlink/atomicity issues
"""

from __future__ import annotations

import os
import stat
import threading
import uuid
from pathlib import Path

import pytest
from app.data_providers import csv_upload, registry
from app.main import create_app
from fastapi.testclient import TestClient
from starlette.requests import Request

CSV = "date,open,high,low,close,volume\n2024-01-02,10,11,9,10,100\n2024-01-03,10,11,9,10,100\n"


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _request(headers: dict[str, str], peer: str = "127.0.0.1") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 12345)})


# ---------------------------------------------------------------- JWT secrets
def test_production_refuses_shipped_placeholder_secret(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "SECRET", "change-me-32-chars-minimum-please")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bt")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENGINE_MODE", "vendor")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    monkeypatch.setenv("AUTH_RESET_TOKEN_LOG", "0")

    with pytest.raises(RuntimeError, match="REFUSE_BOOT"):
        auth.validate_prod_boot()


def test_production_accepts_strong_secret(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "SECRET", "x" * 48)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bt")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENGINE_MODE", "vendor")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    monkeypatch.setenv("AUTH_RESET_TOKEN_LOG", "0")
    auth.validate_prod_boot()


def test_production_refuses_token_logging_and_unimplemented_provider(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "SECRET", "x" * 48)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bt")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENGINE_MODE", "vendor")
    monkeypatch.setenv("AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("AUTH_RESET_TOKEN_LOG", "1")
    with pytest.raises(RuntimeError) as exc:
        auth.validate_prod_boot()
    text = str(exc.value)
    assert "AUTH_PROVIDER" in text
    assert "AUTH_RESET_TOKEN_LOG" in text


# ------------------------------------------------------------- proxy headers
def test_forwarded_headers_ignored_by_default(monkeypatch):
    from app import auth

    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    auth._attempts.clear()
    req = _request({"x-real-ip": "203.0.113.9", "x-forwarded-for": "198.51.100.7"})
    from app.main import client_ip

    assert client_ip(req) == "127.0.0.1"


def test_forwarded_headers_used_only_when_trusted(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    from app.main import client_ip

    assert client_ip(_request({"x-real-ip": "203.0.113.9"})) == "203.0.113.9"
    # Invalid values fall back to the direct peer.
    assert client_ip(_request({"x-real-ip": "not-an-ip"})) == "127.0.0.1"


# ---------------------------------------------------------- rate limiter cap
def test_rate_limiter_key_cap_bounds_memory(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "RATE_LIMIT_MAX_KEYS", 3)
    auth._attempts.clear()
    for i in range(50):
        auth.rate_limit(f"email:user{i}@example.test")
    assert len(auth._attempts) <= 3


def test_forgot_is_rate_limited(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "LOGIN_MAX_PER_MIN", 1)
    auth._attempts.clear()
    c = _client()
    first = c.post("/api/v1/auth/forgot", json={"email": "nobody@example.test"})
    assert first.status_code == 200, first.text
    second = c.post("/api/v1/auth/forgot", json={"email": "nobody@example.test"})
    assert second.status_code == 429, second.text


# --------------------------------------------------------- refresh rotation
def test_concurrent_refresh_rotation_issues_exactly_one_token():
    from app.auth import rotate_refresh_token

    c = _client()
    email = f"race-{uuid.uuid4().hex[:8]}@example.test"
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Race", "email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    refresh = r.json()["refresh_token"]

    barrier = threading.Barrier(2)
    results: list[tuple[str, str] | None] = []

    def run() -> None:
        barrier.wait()
        results.append(rotate_refresh_token(refresh))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for x in results if x is not None) == 1, results


# --------------------------------------------------------------- queue cap
def test_queue_concurrency_cap_is_enforced(monkeypatch):
    from app import queue

    monkeypatch.setattr(queue, "MAX_WORKERS", 1)
    with queue._lock:
        queue._running = 0
    queue.acquire_slot()
    try:
        with pytest.raises(RuntimeError, match="SERVER_BUSY"):
            queue.acquire_slot()
    finally:
        queue.release_slot()
    assert queue.running_jobs() == 0


# ------------------------------------------------- provider catalog + cache
class _FakeCaps:
    category = "equities"
    asset_classes = ("equity",)
    supports_adjusted = False
    requires_package = None
    requires_key_env = None
    rate_limit_per_minute = 0
    description_en = "fake"
    description_ar = "fake"


class _FakeProvider:
    id = "fake"
    name_en = "Fake"
    name_ar = "Fake"
    markets = ("equity",)
    intervals = ("1D",)
    requires_key = False
    license_class = "test"
    capabilities = _FakeCaps()

    def list_supported_markets(self) -> list[str]:
        return ["equity"]

    def health_check(self) -> dict:
        raise RuntimeError("upstream failed: https://api.example.test/x?api_key=SUPERSECRET")


def test_provider_catalog_redacts_upstream_secrets(monkeypatch):
    monkeypatch.setattr(registry, "_ALL", {"fake": _FakeProvider})
    monkeypatch.setenv("ENV", "dev")
    payload = registry.provider_infos()
    item = payload["items"][0]
    assert "SUPERSECRET" not in item["availableDetail"]
    assert "REDACTED" in item["availableDetail"]


def test_provider_catalog_is_cached_in_production(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(registry, "_ALL", {"fake": _FakeProvider})
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(registry, "_CATALOG_TTL_S", 300.0)
    registry.clear_provider_info_cache()

    real_build = registry._build_provider_infos

    def counting_build():
        calls.append(1)
        return real_build()

    monkeypatch.setattr(registry, "_build_provider_infos", counting_build)
    try:
        first = registry.provider_infos()
        second = registry.provider_infos()
        assert len(calls) == 1
        assert first == second
        # Callers get a copy and cannot corrupt the cached snapshot.
        first["items"].clear()
        assert registry.provider_infos()["items"]
    finally:
        registry.clear_provider_info_cache()


# ------------------------------------------------------------- CSV uploads
def _isolated_upload_dir(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(csv_upload, "UPLOAD_DIR", root)
    return root


def test_csv_upload_rejects_symlinked_user_directory(monkeypatch, tmp_path):
    root = _isolated_upload_dir(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    uid = "u-symlink-dir"
    os.symlink(outside, root / csv_upload.user_scope(uid))
    with pytest.raises(OSError, match="Unsafe per-user upload path"):
        csv_upload.upload_symbol_csv("AAPL", CSV.encode(), uid)


def test_csv_upload_rejects_symlinked_symbol_file(monkeypatch, tmp_path):
    root = _isolated_upload_dir(monkeypatch, tmp_path)
    uid = "u-symlink-file"
    user_dir = root / csv_upload.user_scope(uid)
    user_dir.mkdir()
    target = tmp_path / "outside.csv"
    target.write_text(CSV)
    os.symlink(target, user_dir / "AAPL.csv")
    with pytest.raises(OSError, match="symlink"):
        csv_upload.upload_symbol_csv("AAPL", CSV.encode(), uid)
    assert target.read_text() == CSV  # the symlink target was not overwritten


def test_csv_upload_is_atomic_and_restrictive(monkeypatch, tmp_path):
    root = _isolated_upload_dir(monkeypatch, tmp_path)
    uid = "u-atomic"
    out = csv_upload.upload_symbol_csv("AAPL", CSV.encode(), uid)
    path = root / csv_upload.user_scope(uid) / "AAPL.csv"
    assert out["rows"] == 2
    assert path.is_file() and not path.is_symlink()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".upload-*"))
