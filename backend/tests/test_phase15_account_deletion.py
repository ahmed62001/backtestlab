"""Focused D-PH15 account-deletion regressions (SQLite + PostgreSQL).

These tests cover both audited findings independently of the Phase 15 probe
scripts:

* D-PH15-01 — deleting an account that has ``password_resets`` rows must not
  fail on the foreign key, and every dependent row must be removed atomically.
* D-PH15-02 — the user's private CSV upload directory must be removed without
  touching another tenant, the upload root, or any symlink target.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from pathlib import Path

import pytest
from app.data_providers import csv_upload
from app.db import Backtest, Job, PasswordReset, RefreshToken, SessionLocal, Usage, User
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

CSV = "date,open,high,low,close,volume\n2024-01-02,10,11,9,10,100\n2024-01-03,10,11,9,10,100\n"


def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def register(c: TestClient, label: str) -> tuple[str, dict[str, str]]:
    response = c.post(
        "/api/v1/auth/register",
        json={
            "name": "Deletion",
            "email": f"{label}-{uuid.uuid4().hex}@example.test",
            "password": "password123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], {"Authorization": f"Bearer {response.json()['token']}"}


def add_children(user_id: str, reset_count: int = 0) -> None:
    with SessionLocal() as s:
        s.add_all(
            [
                RefreshToken(
                    id=f"rt-{uuid.uuid4().hex}",
                    user_id=user_id,
                    jti=uuid.uuid4().hex,
                    revoked=False,
                    expires_at=dt.datetime.now(dt.UTC).isoformat(),
                ),
                Backtest(id=f"bt-{uuid.uuid4().hex}", user_id=user_id),
                Job(id=f"job-{uuid.uuid4().hex}", user_id=user_id),
                Usage(user_id=user_id, day=dt.date.today().isoformat(), used=1),
            ]
        )
        for _ in range(reset_count):
            s.add(
                PasswordReset(
                    id=f"pr-{uuid.uuid4().hex}",
                    user_id=user_id,
                    token_hash=uuid.uuid4().hex,
                    expires_at=dt.datetime.now(dt.UTC).isoformat(),
                    used=False,
                )
            )
        s.commit()


def count(model, user_id: str) -> int:
    with SessionLocal() as s:
        return int(
            s.scalar(select(func.count()).select_from(model).where(model.user_id == user_id)) or 0
        )


def upload(c: TestClient, headers: dict[str, str]) -> None:
    response = c.post(
        "/api/v1/data-providers/csv-upload", json={"symbol": "AAPL", "csv": CSV}, headers=headers
    )
    assert response.status_code == 200, response.text


def set_upload_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(csv_upload, "UPLOAD_DIR", root)


# ---------------------------------------------------------------------------
# D-PH15-01 — password_resets FK and atomic dependent deletion
# ---------------------------------------------------------------------------
def test_delete_without_resets_deletes_all_dependents_and_repeat_is_safe():
    c = client()
    uid, headers = register(c, "no-reset")
    add_children(uid)
    first = c.delete("/api/v1/auth/me", headers=headers)
    second = c.delete("/api/v1/auth/me", headers=headers)
    assert first.status_code == 200 and first.json() == {"ok": True}
    assert second.status_code == 401
    with SessionLocal() as s:
        assert s.get(User, uid) is None
    for model in (RefreshToken, PasswordReset, Backtest, Job, Usage):
        assert count(model, uid) == 0


@pytest.mark.parametrize("resets", [1, 4])
def test_delete_with_one_or_many_resets_and_all_dependent_rows(resets: int):
    c = client()
    uid, headers = register(c, f"resets-{resets}")
    add_children(uid, resets)
    assert count(PasswordReset, uid) == resets
    response = c.delete("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as s:
        assert s.get(User, uid) is None
    for model in (RefreshToken, PasswordReset, Backtest, Job, Usage):
        assert count(model, uid) == 0


def test_delete_csv_files_only_for_target_account_and_blocks_retrieval(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    set_upload_root(monkeypatch, root)
    c = client()
    target, target_h = register(c, "target")
    other, other_h = register(c, "other")
    add_children(target, 3)
    add_children(other, 2)
    upload(c, target_h)
    upload(c, other_h)
    target_dir = root / csv_upload.user_scope(target)
    other_file = root / csv_upload.user_scope(other) / "AAPL.csv"
    other_bytes = other_file.read_bytes()
    response = c.delete("/api/v1/auth/me", headers=target_h)
    assert response.status_code == 200, response.text
    assert not target_dir.exists()
    assert other_file.read_bytes() == other_bytes
    assert c.get("/api/v1/auth/me", headers=target_h).status_code == 401
    with pytest.raises(csv_upload.ProviderError, match="no uploaded CSV"):
        csv_upload.CsvUploadProvider(target).fetch_ohlcv_raw("AAPL", "2024-01-01", "2024-12-31")
    with SessionLocal() as s:
        assert s.get(User, target) is None and s.get(User, other) is not None
    assert count(PasswordReset, other) == 2


def test_missing_user_directory_is_safe(tmp_path, monkeypatch):
    set_upload_root(monkeypatch, tmp_path / "empty-uploads")
    c = client()
    uid, headers = register(c, "missing-dir")
    assert c.delete("/api/v1/auth/me", headers=headers).status_code == 200
    with SessionLocal() as s:
        assert s.get(User, uid) is None


def test_unexpected_upload_root_fails_closed_before_database_changes(tmp_path, monkeypatch):
    root = tmp_path / "upload-root-file"
    root.write_text("not a directory")
    monkeypatch.setattr(csv_upload, "UPLOAD_DIR", root)
    c = client()
    uid, headers = register(c, "unexpected-root")
    assert c.delete("/api/v1/auth/me", headers=headers).status_code == 500
    with SessionLocal() as s:
        assert s.get(User, uid) is not None


def test_path_traversal_user_ids_cannot_select_another_directory(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    set_upload_root(monkeypatch, root)
    protected = tmp_path / "protected"
    protected.mkdir()
    marker = protected / "keep.csv"
    marker.write_text("keep")
    outside_scope = csv_upload.user_scope("../../protected")
    hashed_path = csv_upload._user_dir("../../protected")
    assert hashed_path.parent == root
    assert hashed_path.name == outside_scope and outside_scope != "../../protected"
    (root / outside_scope).mkdir()
    (root / outside_scope / "AAPL.csv").write_text("not the outside file")
    pending = csv_upload.prepare_user_upload_deletion("../../protected")
    assert pending is not None
    assert not (root / outside_scope).exists()
    assert pending.parent == root
    assert marker.read_text() == "keep"


def test_symlinked_user_directory_is_unlinked_without_following_target(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    set_upload_root(monkeypatch, root)
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "keep.csv"
    protected.write_text("private")
    c = client()
    uid, headers = register(c, "symlink")
    user_path = root / csv_upload.user_scope(uid)
    user_path.symlink_to(outside, target_is_directory=True)
    response = c.delete("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    assert protected.read_text() == "private"
    assert not user_path.exists() and not user_path.is_symlink()


def test_symlink_inside_user_directory_is_not_followed(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    set_upload_root(monkeypatch, root)
    outside = tmp_path / "outside-inner"
    outside.mkdir()
    protected = outside / "keep.csv"
    protected.write_text("private")
    c = client()
    uid, headers = register(c, "nested-symlink")
    upload(c, headers)
    user_dir = root / csv_upload.user_scope(uid)
    (user_dir / "link.csv").symlink_to(protected)
    assert c.delete("/api/v1/auth/me", headers=headers).status_code == 200
    assert protected.read_text() == "private"
    assert not user_dir.exists()


def test_database_rollback_restores_files_and_every_database_row(tmp_path, monkeypatch):
    root = tmp_path / "rollback-uploads"
    set_upload_root(monkeypatch, root)
    c = client()
    uid, headers = register(c, "rollback")
    add_children(uid, 2)
    upload(c, headers)
    active = root / csv_upload.user_scope(uid)
    failed = {"enabled": True}

    def reject_user_delete(_mapper, connection, target):
        if failed["enabled"] and target.id == uid:
            raise RuntimeError("forced delete rollback")

    event.listen(User, "before_delete", reject_user_delete)
    try:
        response = c.delete("/api/v1/auth/me", headers=headers)
    finally:
        event.remove(User, "before_delete", reject_user_delete)
    assert response.status_code == 500
    assert (active / "AAPL.csv").is_file()
    with SessionLocal() as s:
        assert s.get(User, uid) is not None
    assert count(PasswordReset, uid) == 2
    for model in (RefreshToken, Backtest, Job, Usage):
        assert count(model, uid) > 0


def test_cleanup_failure_is_observable_and_retryable_after_commit(tmp_path, monkeypatch, caplog):
    root = tmp_path / "retry-uploads"
    set_upload_root(monkeypatch, root)
    c = client()
    uid, headers = register(c, "retry")
    upload(c, headers)
    scope = csv_upload.user_scope(uid)
    real_rmtree = csv_upload.shutil.rmtree

    def fail_cleanup(path, *args, **kwargs):
        if Path(path).name.startswith(".pending-delete-"):
            raise PermissionError("forced cleanup failure")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(csv_upload.shutil, "rmtree", fail_cleanup)
    response = c.delete("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert "account upload cleanup deferred" in caplog.text
    pending = list(root.glob(f".pending-delete-{scope}-*"))
    assert len(pending) == 1 and (pending[0] / "AAPL.csv").is_file()
    with SessionLocal() as s:
        assert s.get(User, uid) is None
    monkeypatch.setattr(csv_upload.shutil, "rmtree", real_rmtree)
    csv_upload.retry_pending_upload_deletions()
    assert not pending[0].exists()


def test_startup_recovery_restores_live_account_and_purges_deleted_account(tmp_path, monkeypatch):
    root = tmp_path / "startup-recovery"
    set_upload_root(monkeypatch, root)
    c = client()
    live, live_h = register(c, "live")
    deleted, deleted_h = register(c, "deleted")
    upload(c, live_h)
    upload(c, deleted_h)
    live_scope, deleted_scope = csv_upload.user_scope(live), csv_upload.user_scope(deleted)
    live_pending = csv_upload.prepare_user_upload_deletion(live)
    deleted_pending = csv_upload.prepare_user_upload_deletion(deleted)
    assert live_pending is not None and deleted_pending is not None
    assert c.delete("/api/v1/auth/me", headers=deleted_h).status_code == 200
    csv_upload.retry_pending_upload_deletions()
    assert (root / live_scope / "AAPL.csv").is_file()
    assert not (root / deleted_scope).exists()


def test_concurrent_delete_requests_are_safe():
    c = client()
    uid, headers = register(c, "concurrent")
    add_children(uid, 2)
    barrier = threading.Barrier(3)
    responses = []
    errors = []

    def delete_account():
        try:
            barrier.wait(timeout=10)
            responses.append(c.delete("/api/v1/auth/me", headers=headers))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [threading.Thread(target=delete_account) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=10)
    for worker in workers:
        worker.join(timeout=20)
    assert not errors and all(not worker.is_alive() for worker in workers)
    # Both requests may pass authentication before the first commit; if one
    # arrives later the deleted user no longer authorizes it. Both are safe.
    assert len(responses) == 2 and all(r.status_code in (200, 401) for r in responses)
    assert any(r.status_code == 200 for r in responses)
    with SessionLocal() as s:
        assert s.get(User, uid) is None
    assert count(PasswordReset, uid) == 0
