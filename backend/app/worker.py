"""Job runner: executes job rows with the vendor adapter (Phase 1/10).

Phase 10 reliability contract
-----------------------------
* **Lease + heartbeat** — a job is claimed with a compare-and-set UPDATE
  (`status='queued' -> 'running'`). A background heartbeat extends
  `lease_expires_at` while it runs. If the process dies the lease expires and
  `recover_stale_jobs()` requeues it (or fails it after `max_attempts`).
* **Idempotency** — claiming is atomic, and result writes only happen while
  this worker still owns the running lease with its `worker_id`. Replaying a
  finished job never overwrites results or double-counts usage.
* **Bounded retries** — transient upstream failures are retried up to
  `JOB_MAX_ATTEMPTS` with a small backoff; validation failures are terminal.
* **Timeout** — the compute step runs in a daemon thread and is abandoned
  after `JOB_TIMEOUT_SECONDS`; the job is failed with a safe `TIMEOUT:` code.
* **Graceful shutdown** — SIGTERM finishes the in-flight job then exits 0;
  a second signal releases (requeues) the job immediately.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid

from sqlalchemy import and_, or_, select, update

from .observability import configure_logging, log_context
from .observability import inc as metric_inc

log = logging.getLogger("backtestlab.worker")

JOB_TIMEOUT_S = float(os.environ.get("JOB_TIMEOUT_SECONDS", "120"))
JOB_LEASE_S = float(os.environ.get("JOB_LEASE_SECONDS", "90"))
JOB_HEARTBEAT_S = float(os.environ.get("JOB_HEARTBEAT_SECONDS", "15"))
JOB_MAX_ATTEMPTS = int(os.environ.get("JOB_MAX_ATTEMPTS", "3"))
JOB_RETRY_BACKOFF_S = float(os.environ.get("JOB_RETRY_BACKOFF_S", "5"))
JOB_RECOVERY_INTERVAL_S = float(os.environ.get("JOB_RECOVERY_INTERVAL_S", "30"))
WORKER_POLL_S = float(os.environ.get("WORKER_POLL_SECONDS", "2"))
WORKER_ID = os.environ.get(
    "WORKER_ID", f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
)

# Transient provider failures worth a bounded retry.
_RETRYABLE_CODES = {
    "UPSTREAM_BLOCKED",
    "UPSTREAM_UNAVAILABLE",
    "UPSTREAM_BAD_RESPONSE",
    "RATE_LIMITED",
    "PROVIDER_DOWN",
    "PROVIDER_TIMEOUT",
}

_current_job_id = ""
_current_jobs: set[str] = set()
_current_job_lock = threading.Lock()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _iso_after(seconds: float) -> str:
    return (_now() + dt.timedelta(seconds=seconds)).isoformat()


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _cache_state(result: dict) -> str:
    pv = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
    cache = pv.get("cache")
    if cache in ("hit", "miss", "partial"):
        return str(cache)
    return {"store": "hit", "partial": "partial", "live": "miss"}.get(
        str(pv.get("retrieval") or ""), "miss"
    )


def _is_transient(exc: BaseException) -> bool:
    code = getattr(exc, "code", "")
    if code in _RETRYABLE_CODES:
        return True
    # ProviderError -> RuntimeError wrapping in _compute keeps only the message,
    # so also recognise the stable code prefixes in the text.
    text = str(exc)
    return any(f"'{c}'" in text or f": {c}" in text or c in text[:200] for c in _RETRYABLE_CODES)


def _claim_job(jid: str, worker_id: str) -> bool:
    """Atomically claim a queued job. Returns True only for the winning caller."""
    from .db import Job, SessionLocal, init_db

    init_db()
    now = _iso()
    s = SessionLocal()
    try:
        result = s.execute(
            update(Job)
            .where(
                Job.id == jid,
                Job.status == "queued",
                or_(Job.next_attempt_at == "", Job.next_attempt_at <= now),
            )
            .values(
                status="running",
                progress=5,
                started_at=now,
                heartbeat_at=now,
                lease_expires_at=_iso_after(JOB_LEASE_S),
                attempts=Job.attempts + 1,
                worker_id=worker_id,
                next_attempt_at="",
                error="",
            )
        )
        s.commit()
        return bool(result.rowcount)
    finally:
        s.close()


def _heartbeat_once(jid: str, worker_id: str) -> bool:
    """Extend the lease. Returns False when the job is no longer ours."""
    from .db import Job, SessionLocal

    s = SessionLocal()
    try:
        now = _iso()
        result = s.execute(
            update(Job)
            .where(Job.id == jid, Job.status == "running", Job.worker_id == worker_id)
            .values(heartbeat_at=now, lease_expires_at=_iso_after(JOB_LEASE_S))
        )
        s.commit()
        return bool(result.rowcount)
    except Exception:
        log.warning("heartbeat update failed", exc_info=True)
        return True
    finally:
        s.close()


def _heartbeat_loop(
    stop: threading.Event, jid: str, worker_id: str, interval: float | None = None
) -> None:
    period = (
        interval if interval and interval > 0 else max(1.0, min(JOB_HEARTBEAT_S, JOB_LEASE_S / 3.0))
    )
    while not stop.wait(period):
        if not _heartbeat_once(jid, worker_id):
            log.warning("lease lost; stopping heartbeat", extra={"job_id": jid})
            stop.set()
            return


def _owned(jid: str, worker_id: str):
    """Return a session + job when this worker still owns the running lease."""
    from .db import Job, SessionLocal

    s = SessionLocal()
    j = s.get(Job, jid)
    if j is None or j.status != "running" or j.worker_id != worker_id:
        s.close()
        return None, None
    return s, j


def _finish_ok(jid: str, worker_id: str, result: dict) -> bool:
    """Persist results exactly once while we still own the lease."""
    from .db import Backtest

    s, j = _owned(jid, worker_id)
    if s is None or j is None:
        return False
    try:
        b = s.get(Backtest, j.backtest_id)
        if b is not None:
            # Idempotency: a replayed/crashed run must not rewrite a finished
            # backtest (results are deterministic, but usage/provenance order
            # must stay stable).
            already_done = b.status == "done" and b.result_json not in ("", "{}", None)
            if not already_done:
                b.status = "done"
                b.total_return_pct = result["totalReturnPct"]
                b.max_drawdown_pct = result["maxDrawdownPct"]
                b.sharpe = result["sharpe"]
                b.win_rate_pct = result["winRatePct"]
                b.trades = result["trades"]
                b.vs_buy_hold_pct = result["vsBuyHoldPct"]
                pv = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
                b.data_provider = str(pv.get("provider", ""))
                b.data_symbol = str(pv.get("symbol", ""))
                b.data_interval = str(pv.get("interval", ""))
                b.data_start = str(pv.get("start") or "")
                b.data_end = str(pv.get("end") or "")
                b.data_hash = str(pv.get("dataHash", ""))
                b.data_rows = int(pv.get("rows") or pv.get("bars") or 0)
                b.result_json = json.dumps(result, default=str)
        j.status = "done"
        j.progress = 100
        j.finished_at = _iso()
        j.lease_expires_at = ""
        s.commit()
        return True
    finally:
        s.close()


def _fail_terminal(jid: str, worker_id: str, code: str, message: str) -> bool:
    from .db import Backtest

    s, j = _owned(jid, worker_id)
    if s is None or j is None:
        return False
    try:
        _refund(s, j.user_id)
        j.status = "failed"
        j.error = f"{code}:{message}"[:400]
        j.finished_at = _iso()
        j.lease_expires_at = ""
        b = s.get(Backtest, j.backtest_id)
        if b is not None and b.status != "done":
            b.status = "failed"
        s.commit()
        return True
    finally:
        s.close()


def _requeue(jid: str, worker_id: str, message: str, backoff_s: float) -> bool:
    from .db import Backtest

    s, j = _owned(jid, worker_id)
    if s is None or j is None:
        return False
    try:
        if j.attempts >= (j.max_attempts or JOB_MAX_ATTEMPTS):
            s.close()
            return False
        j.status = "queued"
        j.progress = 0
        j.error = f"RETRY:{message}"[:400]
        j.next_attempt_at = _iso_after(max(0.0, backoff_s))
        j.lease_expires_at = ""
        j.worker_id = ""
        b = s.get(Backtest, j.backtest_id)
        if b is not None and b.status != "done":
            b.status = "queued"
        s.commit()
        return True
    finally:
        s.close()


def execute_job(jid: str, timeout_s: float | None = None, worker_id: str | None = None) -> str:
    """Execute one job. Returns done|failed|requeued|timeout|skipped.

    Safe to call concurrently and safe to replay: only the caller that wins
    the atomic claim does any work.
    """
    global _current_job_id
    from .adapter import EngineRejectedError

    timeout = JOB_TIMEOUT_S if timeout_s is None else float(timeout_s)
    wid = worker_id or WORKER_ID
    t0 = time.time()
    if not _claim_job(jid, wid):
        log.info("job skipped (not claimable)", extra={"job_id": jid, "status": "skipped"})
        return "skipped"
    with _current_job_lock:
        _current_job_id = jid
        _current_jobs.add(jid)

    stop = threading.Event()
    hb = threading.Thread(
        target=_heartbeat_loop, args=(stop, jid, wid), name=f"heartbeat-{jid}", daemon=True
    )
    hb.start()
    try:
        from .db import Job, SessionLocal

        s = SessionLocal()
        try:
            j = s.get(Job, jid)
            if j is None:
                return "skipped"
            cfg = json.loads(j.config_json or "{}")
            job_user_id = j.user_id
            provider_label = str(cfg.get("dataProvider") or "")
            if not provider_label:
                from .data_providers.registry import default_provider_id

                provider_label = default_provider_id()
            symbol_label = str(cfg.get("asset", ""))
            backtest_id = j.backtest_id
            attempts = j.attempts
            max_attempts = j.max_attempts or JOB_MAX_ATTEMPTS
            j.progress = 20
            s.commit()
        finally:
            s.close()

        with log_context(
            job_id=jid, backtest_id=backtest_id, provider=provider_label, symbol=symbol_label
        ):
            log.info("job started", extra={"attempt": attempts, "max_attempts": max_attempts})
            box: dict[str, object] = {}
            err: dict[str, BaseException] = {}

            def _runner() -> None:
                try:
                    box["result"] = _compute(cfg, job_user_id)
                except BaseException as exc:  # noqa: BLE001
                    err["exc"] = exc

            compute = threading.Thread(target=_runner, name=f"compute-{jid}", daemon=True)
            compute.start()
            compute.join(max(0.0, timeout))
            if compute.is_alive():
                _fail_terminal(jid, wid, "TIMEOUT", "job exceeded the maximum runtime")
                metric_inc("backtestlab_jobs_total", status="timeout")
                log.warning(
                    "job timed out",
                    extra={"status": "timeout", "duration_ms": int((time.time() - t0) * 1000)},
                )
                return "timeout"

            exc = err.get("exc")
            if exc is not None:
                if isinstance(exc, EngineRejectedError):
                    _fail_terminal(jid, wid, "VALIDATION", str(exc))
                    metric_inc("backtestlab_jobs_total", status="failed")
                    log.warning(
                        "job rejected",
                        extra={"status": "failed", "duration_ms": int((time.time() - t0) * 1000)},
                    )
                    return "failed"
                if _is_transient(exc) and attempts < max_attempts:
                    backoff = JOB_RETRY_BACKOFF_S * max(1, attempts)
                    if _requeue(jid, wid, str(exc)[:200], backoff):
                        metric_inc("backtestlab_jobs_total", status="retried")
                        log.warning(
                            "transient failure; job requeued",
                            extra={
                                "status": "retried",
                                "attempt": attempts,
                                "duration_ms": int((time.time() - t0) * 1000),
                            },
                        )
                        return "requeued"
                _fail_terminal(jid, wid, "OUR_FAULT", str(exc)[:300])
                metric_inc("backtestlab_jobs_total", status="failed")
                log.error(
                    "job failed",
                    extra={"status": "failed", "duration_ms": int((time.time() - t0) * 1000)},
                )
                return "failed"

            result = box.get("result")
            if not isinstance(result, dict):
                _fail_terminal(jid, wid, "OUR_FAULT", "engine returned no result")
                metric_inc("backtestlab_jobs_total", status="failed")
                return "failed"

            if not _finish_ok(jid, wid, result):
                log.warning(
                    "lost lease before persisting results",
                    extra={"job_id": jid, "status": "skipped"},
                )
                return "skipped"

            pv = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
            metric_inc("backtestlab_jobs_total", status="done")
            log.info(
                "job finished",
                extra={
                    "status": "done",
                    "duration_ms": int((time.time() - t0) * 1000),
                    "cache": _cache_state(result),
                    "provider": str(pv.get("provider") or provider_label),
                    "symbol": str(pv.get("symbol") or symbol_label),
                    "rows": int(pv.get("rows") or pv.get("bars") or 0),
                },
            )
            return "done"
    finally:
        stop.set()
        hb.join(timeout=2)
        with _current_job_lock:
            _current_jobs.discard(jid)
            if _current_job_id == jid:
                _current_job_id = ""


def recover_stale_jobs(
    stale_seconds: float | None = None, worker_id: str | None = None
) -> dict[str, int]:
    """Requeue or fail jobs whose lease expired (worker crash / kill -9).

    Also adopts legacy `running` rows that predate leases once they are older
    than the stale threshold.
    """
    from .db import Job, SessionLocal

    wid = worker_id or WORKER_ID
    threshold = stale_seconds if stale_seconds is not None else JOB_LEASE_S
    cutoff = _iso_after(-threshold)
    now = _iso()
    recovered = 0
    failed = 0
    s = SessionLocal()
    try:
        stale = s.scalars(
            select(Job).where(
                Job.status == "running",
                or_(
                    and_(Job.lease_expires_at != "", Job.lease_expires_at < now),
                    and_(Job.lease_expires_at == "", Job.created_at < cutoff),
                ),
            )
        ).all()
        for j in stale:
            from .db import Backtest

            b = s.get(Backtest, j.backtest_id)
            if (j.max_attempts or JOB_MAX_ATTEMPTS) <= j.attempts:
                claimed = s.execute(
                    update(Job)
                    .where(Job.id == j.id, Job.status == "running")
                    .values(
                        status="failed",
                        error=(
                            "LEASE_EXPIRED: worker stopped before the job "
                            "finished and retries are exhausted"
                        ),
                        finished_at=now,
                        lease_expires_at="",
                    )
                )
                if not claimed.rowcount:
                    continue
                _refund(s, j.user_id)
                if b is not None and b.status != "done":
                    b.status = "failed"
                failed += 1
            else:
                backoff = JOB_RETRY_BACKOFF_S * max(1, j.attempts)
                claimed = s.execute(
                    update(Job)
                    .where(Job.id == j.id, Job.status == "running")
                    .values(
                        status="queued",
                        progress=0,
                        error="LEASE_EXPIRED: requeued after worker crash",
                        next_attempt_at=_iso_after(backoff),
                        lease_expires_at="",
                        worker_id="",
                    )
                )
                if not claimed.rowcount:
                    continue
                if b is not None and b.status != "done":
                    b.status = "queued"
                recovered += 1
        if stale:
            s.commit()
    finally:
        s.close()
    if recovered or failed:
        log.warning(
            "stale jobs recovered",
            extra={
                "recovered": recovered,
                "failed": failed,
                "worker_id": wid,
                "status": "recovered",
            },
        )
        metric_inc("backtestlab_jobs_recovered_total", amount=float(recovered))
        metric_inc("backtestlab_jobs_recovery_failed_total", amount=float(failed))
    return {"recovered": recovered, "failed": failed}


def release_current_job(reason: str = "WORKER_SHUTDOWN") -> bool:
    """Best-effort requeue of the job(s) currently owned by this process."""
    with _current_job_lock:
        jids = list(_current_jobs)
    if not jids:
        return False
    from .db import Job, SessionLocal

    released = False
    s = SessionLocal()
    try:
        for jid in jids:
            j = s.get(Job, jid)
            if j is None or j.status != "running":
                continue
            j.status = "queued"
            j.progress = 0
            j.error = f"RELEASED:{reason}"
            j.next_attempt_at = _iso()
            j.lease_expires_at = ""
            j.worker_id = ""
            released = True
            log.warning(
                "released in-flight job for graceful shutdown",
                extra={"job_id": jid, "status": "released"},
            )
        if released:
            s.commit()
        return released
    finally:
        s.close()


def _compute(cfg: dict, user_id: str | None = None) -> dict:
    from .engine import ENGINE_MODE, engine_block

    if ENGINE_MODE == "local":
        from .synthetic_engine import run_backtest as synth

        r = synth(cfg)
        r.setdefault("warnings", []).append({"code": "SYNTHETIC_DATA"})
        r["engine"] = engine_block()
        return r
    from .adapter import EngineRejectedError
    from .data import quality_guards
    from .data_providers import ProviderError, fetch_bars
    from .data_providers.base import (
        ERR_BAD_INPUT,
        ERR_DATA_NOT_IN_STORE,
        ERR_EMPTY_DATA,
        ERR_NO_DATA,
        ERR_UNKNOWN_SYMBOL,
    )
    from .pipeline import run_and_normalize

    try:
        _dp, prov = fetch_bars(
            cfg.get("dataProvider"),
            str(cfg.get("asset", "AAPL")),
            str(cfg.get("from", "") or ""),
            str(cfg.get("to", "") or ""),
            str(cfg.get("interval", "1D")),
            user_id=user_id,
        )
    except ProviderError as e:
        # names the provider; request/validation outcomes -> EngineRejectedError
        # (422), transient upstream failures -> RuntimeError (503/502) so the
        # lease/retry loop can retry the latter only.
        if e.code in (
            ERR_BAD_INPUT,
            ERR_UNKNOWN_SYMBOL,
            ERR_DATA_NOT_IN_STORE,
            ERR_EMPTY_DATA,
            ERR_NO_DATA,
        ):
            raise EngineRejectedError(str(e)) from e
        raise RuntimeError(str(e)) from e
    guards = quality_guards(prov.frame)
    if prov.provenance.get("license_class") != "commercial_ok":
        guards = guards + [{"code": "DATA_DEV_SOURCE"}]
    # A VendorUnavailableError propagates: NO silent fallback (ENGINE_UNAVAILABLE).
    return run_and_normalize(cfg, prov.frame, prov.provenance, guards)


def _refund(s, user_id: str) -> None:
    from sqlalchemy import select as _select

    from .db import Usage, today_key

    row = s.scalar(_select(Usage).where(Usage.user_id == user_id, Usage.day == today_key()))
    if row is not None and row.used > 0:
        row.used -= 1


def main() -> int:
    """Run the job loop until SIGTERM/SIGINT; exit 0 on graceful shutdown."""
    from .db import Job, SessionLocal, init_db

    configure_logging()
    stop_requested = False

    def _shutdown(signum, frame) -> None:
        nonlocal stop_requested
        if stop_requested:
            # Second signal: don't wait for the current job — release it and
            # unwind immediately (the daemon compute thread dies with us).
            release_current_job("WORKER_SHUTDOWN_FORCED")
            raise SystemExit(0)
        stop_requested = True

    timeout_s = float(os.environ.get("JOB_TIMEOUT_SECONDS", str(JOB_TIMEOUT_S)))
    if timeout_s <= 0:
        log.error("fatal: JOB_TIMEOUT_SECONDS must be > 0")
        return 1

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Startup self-check: with ENGINE_MODE=vendor the vendor engine must be
    # importable or this process exits non-zero (never a silent fallback).
    from .engine import ENGINE_MODE

    if ENGINE_MODE == "vendor":
        try:
            from .adapter import load_vendor_engine

            load_vendor_engine()
        except Exception as e:  # noqa: BLE001
            log.error("fatal: vendor engine unavailable: %s", e)
            return 1

    init_db()
    recover_stale_jobs()
    log.info("worker loop started", extra={"worker_id": WORKER_ID})
    last_recovery = time.monotonic()
    while not stop_requested:
        try:
            if time.monotonic() - last_recovery >= JOB_RECOVERY_INTERVAL_S:
                recover_stale_jobs()
                last_recovery = time.monotonic()
            now = _iso()
            s = SessionLocal()
            try:
                j = s.scalar(
                    select(Job)
                    .where(
                        Job.status == "queued",
                        or_(Job.next_attempt_at == "", Job.next_attempt_at <= now),
                    )
                    .order_by(Job.created_at, Job.id)
                    .limit(1)
                )
            finally:
                s.close()
            try:
                with open(os.environ.get("WORKER_ALIVE_FILE", "/tmp/worker.alive"), "w") as _hb:
                    _hb.write(str(time.time()))
            except OSError:
                pass
            if j is not None:
                log.info("executing queued job", extra={"job_id": j.id})
                execute_job(j.id, timeout_s)
            else:
                time.sleep(WORKER_POLL_S)
        except Exception:
            log.exception("worker loop error")
            time.sleep(5)

    log.info("shutdown signal received, exiting gracefully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
