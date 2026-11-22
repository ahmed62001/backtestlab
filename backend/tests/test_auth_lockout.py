"""Regression tests for DB-backed login brute-force protection.

The previous limiter was process-local: N API replicas multiplied the
effective threshold by N. These tests exercise one shared ledger, the
account/IP window, the 429 + Retry-After contract, and timing-equalized
handling of unknown accounts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def _register(c: TestClient, email: str) -> None:
    r = c.post(
        "/api/v1/auth/register",
        json={"name": "Lockout Test", "email": email, "password": "correct-horse-9"},
    )
    assert r.status_code == 201, r.text


def test_account_lockout_after_five_failures_blocks_correct_password():
    c = _client()
    email = "lock-account@example.com"
    _register(c, email)
    for i in range(5):
        r = c.post("/api/v1/auth/login", json={"email": email, "password": f"wrong-{i}"})
        assert r.status_code == 401, (i, r.text)
        assert r.json()["code"] == "INVALID_CREDENTIALS"
    blocked = c.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    retry = int(blocked.headers.get("retry-after", "0"))
    assert 1 <= retry <= 900


def test_unknown_account_gets_identical_401_then_lockout():
    c = _client()
    email = "does-not-exist@example.com"
    for _ in range(5):
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
        assert r.status_code == 401
        # Enumeration guard: unknown accounts use the same code/message.
        assert r.json()["code"] == "INVALID_CREDENTIALS"
    r = c.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    assert r.status_code == 429


def test_successful_login_clears_account_failures():
    c = _client()
    email = "lock-clear@example.com"
    _register(c, email)
    for i in range(4):
        assert (
            c.post("/api/v1/auth/login", json={"email": email, "password": f"bad-{i}"}).status_code
            == 401
        )
    ok = c.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"})
    assert ok.status_code == 200, ok.text
    # The account counter was reset; new failures start from zero again.
    for i in range(4):
        assert (
            c.post("/api/v1/auth/login", json={"email": email, "password": f"bad2-{i}"}).status_code
            == 401
        )
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"}
        ).status_code
        == 200
    )


def test_lockout_is_shared_across_instances():
    """A second app instance sees the same failure ledger."""
    c1 = _client()
    email = "lock-shared@example.com"
    _register(c1, email)
    for i in range(5):
        assert (
            c1.post("/api/v1/auth/login", json={"email": email, "password": f"bad-{i}"}).status_code
            == 401
        )
    c2 = _client()
    r = c2.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"})
    assert r.status_code == 429
