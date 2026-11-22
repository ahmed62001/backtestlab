"""Async job queue: DB-backed in-process worker.

Decision: RQ/arq both need Redis; free-tier has no Redis, so default is a
DB-backed in-process worker (jobs table + thread) with queued/running/done/
failed + progress + timeout + cancel + idempotency + concurrency cap +
SERVER_BUSY backpressure + global kill switch. Redis/RQ later behind this API.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select, update

from .observability import inc as metric_inc
from .observability import log_context

log = logging.getLogger("backtestlab.queue")

MAX_WORKERS = int(os.environ.get("QUEUE_MAX_WORKERS", "2"))
JOB_TIMEOUT_S = float(os.environ.get("JOB_TIMEOUT_SECONDS", os.environ.get("JOB_TIMEOUT_S", "120")))
JOB_MAX_ATTEMPTS = int(os.environ.get("JOB_MAX_ATTEMPTS", "3"))
_kill = False
_lock = threading.Lock()
_running = 0


def kill_switch(on: bool) -> None:
    global _kill
    _kill = on


def acquire_slot() -> None:
    """Reserve a bounded worker slot or raise ``RuntimeError`` (SERVER_BUSY).

    The check-and-increment is atomic under ``_lock`` so concurrent submits
    cannot exceed ``MAX_WORKERS`` (previously the cap was never enforced).
    """
    global _running
    with _lock:
        if _kill:
            raise RuntimeError("SERVER_BUSY: queue paused by kill switch")
        if _running >= MAX_WORKERS:
            raise RuntimeError(f"SERVER_BUSY: queue at capacity ({MAX_WORKERS} worker slots)")
        _running += 1


def release_slot() -> None:
    global _running
    with _lock:
        if _running > 0:
            _running -= 1


def running_jobs() -> int:
    with _lock:
        return _running


@contextmanager
def worker_slot() -> Iterator[None]:
    """Context manager that holds one bounded slot for a synchronous run."""
    acquire_slot()
    try:
        yield
    finally:
        release_slot()


def _reserve_quota(s, user_id: str, day: str, limit: int) -> None:
    """Atomically reserve one daily run, or raise LookupError.

    Concurrency-safe on SQLite and PostgreSQL: UPDATE ... WHERE used < limit,
    with an insert-if-absent fallback. There is no check-then-increment window
    (D-PH5-01).
    """
    from .db import Usage, engine

    table = Usage.__table__
    insert_fn = None
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        insert_fn = pg_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert_fn = sqlite_insert

    for _ in range(3):
        res = s.execute(
            update(table)
            .where(
                table.c.user_id == user_id,
                table.c.day == day,
                table.c.used < limit,
            )
            .values(used=table.c.used + 1)
        )
        if (res.rowcount or 0) > 0:
            return
        exists = s.scalar(select(table.c.id).where(table.c.user_id == user_id, table.c.day == day))
        if exists is not None:
            raise LookupError("DAILY_LIMIT_REACHED")
        stmt = (
            insert_fn(table)
            .values(user_id=user_id, day=day, used=1)
            .on_conflict_do_nothing(index_elements=["user_id", "day"])
            .returning(table.c.id)
        )
        if s.execute(stmt).fetchone() is not None:
            return
        # Lost the insert race; loop and increment the winner's row.
    raise LookupError("DAILY_LIMIT_REACHED")


def _use_inprocess_worker() -> bool:
    return os.environ.get("QUEUE_INPROCESS_WORKER", "1") not in ("0", "false", "False", "no")


def submit_job(user_id: str, cfg: dict[str, Any], idem_key: str = "") -> dict[str, Any]:
    from sqlalchemy.exc import IntegrityError

    from .db import Backtest, Job, SessionLocal, User, init_db, today_key
    from .main import FREE_LIMIT, PRO_LIMIT
    from .worker import recover_stale_jobs

    init_db()
    if os.environ.get("QUEUE_RECOVER_ON_SUBMIT", "1") != "0":
        # In-process mode has no separate worker process to sweep on startup;
        # recover expired leases before accepting new work.
        recover_stale_jobs()
    s = SessionLocal()
    slot_acquired = False
    handed_off = False
    try:
        u = s.get(User, user_id)
        limit = PRO_LIMIT if (u and u.plan == "pro") else FREE_LIMIT
        if idem_key:
            j = s.scalar(select(Job).where(Job.user_id == user_id, Job.idem_key == idem_key))
            if j is not None:
                return {
                    "job_id": j.id,
                    "backtest_id": j.backtest_id,
                    "status": j.status,
                    "deduped": True,
                }
        inprocess = _use_inprocess_worker()
        with _lock:
            if _kill:
                raise RuntimeError("SERVER_BUSY: queue paused by kill switch")
        if inprocess:
            # Enforce the worker cap atomically *before* reserving quota or
            # spawning a thread, so a burst cannot allocate unbounded work.
            acquire_slot()
            slot_acquired = True
        day = today_key()
        _reserve_quota(s, user_id, day, limit)
        bid = "bt-" + uuid.uuid4().hex[:8]
        jid = "job-" + uuid.uuid4().hex[:8]
        s.add(
            Backtest(
                id=bid,
                user_id=user_id,
                name=str(cfg.get("asset", "AAPL"))
                + " / "
                + str(cfg.get("templateId", "ma-crossover")),
                template_id=str(cfg.get("templateId", "ma-crossover")),
                asset=str(cfg.get("asset", "AAPL")),
                status="queued",
                created_at=dt.datetime.now(dt.UTC).isoformat(),
                config_json=json.dumps(cfg, default=str),
                result_json="{}",
            )
        )
        s.add(
            Job(
                id=jid,
                user_id=user_id,
                backtest_id=bid,
                status="queued",
                progress=0,
                idem_key=idem_key,
                max_attempts=JOB_MAX_ATTEMPTS,
                config_json=json.dumps(cfg, default=str),
            )
        )
        try:
            s.commit()
        except IntegrityError:
            # A concurrent submit with the same idem key won; roll back the
            # quota reservation and return the winning job (D-PH5-02).
            s.rollback()
            if idem_key:
                j = s.scalar(select(Job).where(Job.user_id == user_id, Job.idem_key == idem_key))
                if j is not None:
                    return {
                        "job_id": j.id,
                        "backtest_id": j.backtest_id,
                        "status": j.status,
                        "deduped": True,
                    }
            raise
        with log_context(
            job_id=jid,
            backtest_id=bid,
            provider=str(cfg.get("dataProvider") or ""),
            symbol=str(cfg.get("asset", "")),
        ):
            log.info("job queued")
            metric_inc("backtestlab_jobs_total", status="queued")
        if inprocess:
            th = threading.Thread(target=_wrap, args=(jid,), daemon=True)
            th.start()
            # Ownership of the reserved slot moves to the worker thread.
            handed_off = True
        return {"job_id": jid, "backtest_id": bid, "status": "queued", "deduped": False}
    finally:
        s.close()
        if slot_acquired and not handed_off:
            release_slot()


def _wrap(jid: str) -> None:
    try:
        from .worker import execute_job

        execute_job(jid, JOB_TIMEOUT_S)
    finally:
        release_slot()
