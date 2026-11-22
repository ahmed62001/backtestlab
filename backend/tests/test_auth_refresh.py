"""Auth remainder: refresh-token rotation, reuse detection, revoke/logout + argon2 paths."""

import contextlib
import os
import pathlib
import sys

os.environ["DATABASE_URL"] = "sqlite:////tmp/bt_authrefresh.db"
with contextlib.suppress(OSError):
    os.remove("/tmp/bt_authrefresh.db")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import create_app
from fastapi.testclient import TestClient

app = create_app()
c = TestClient(app, raise_server_exceptions=False)


import uuid


def _register_login(email=None, password="password123", name="RF User"):
    if email is None:
        email = "rf" + uuid.uuid4().hex[:8] + "@t.com"
    r = c.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_login_issues_access_and_refresh():
    d = _register_login()
    assert {"token", "access_token", "refresh_token", "user"} <= set(d)
    assert d["token"] == d["access_token"]
    # access token works
    h = {"Authorization": "Bearer " + d["token"]}
    me = c.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == d["user"]["email"]


def test_refresh_rotation_chain_retires_old_tokens():
    d = _register_login()
    rt1 = d["refresh_token"]
    # rotate rt1 -> rt2
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 200, r.text
    rt2 = r.json()["refresh_token"]
    assert rt2 != rt1
    # rotate rt2 -> rt3 (chain still works; each rotation issues a fresh token)
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt2})
    assert r.status_code == 200, r.text
    rt3 = r.json()["refresh_token"]
    assert rt3 != rt2
    # presenting a retired/revoked token (rt1) is treated as reuse -> 401
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 401, r.text


def test_refresh_reuse_revokes_all_tokens():
    d = _register_login()
    rt1 = d["refresh_token"]
    # rotate once
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 200
    rt2 = r.json()["refresh_token"]
    # present the already-rotated-away rt1 again -> reuse: all tokens for user revoked
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 401
    # rt2 (issued after rt1) is also dead because reuse revoked everything
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt2})
    assert r.status_code == 401


def test_refresh_invalid_token_401():
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.valid.token"})
    assert r.status_code == 401
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": ""})
    assert r.status_code == 401


def test_revoke_disables_refresh():
    d = _register_login()
    rt = d["refresh_token"]
    # revoke it
    r = c.post(
        "/api/v1/auth/revoke",
        json={"refresh_token": rt},
        headers={"Authorization": "Bearer " + d["token"]},
    )
    assert r.status_code == 200, r.text
    # can no longer refresh
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401
