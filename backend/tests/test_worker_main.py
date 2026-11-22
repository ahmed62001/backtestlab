"""Regression tests for the hardened worker main block (Phase 6).

Run with: python -m pytest tests/test_worker_main.py -q
"""

import os
import signal
import subprocess
import sys
import time

WORKER_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "worker.py")
BACKEND_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)))


def _read_worker() -> str:
    with open(WORKER_PATH, encoding="utf-8") as _fh:
        return _fh.read()


def test_worker_defines_main_and_main_guard():
    """(a) worker.py must define main() and carry a __main__ guard."""
    src = _read_worker()
    assert "def main()" in src
    assert 'if __name__ == "__main__":' in src


def test_worker_stays_alive_then_graceful_exit():
    """(b) subprocess `python -m app.worker` must stay alive 4s and exit 0 on SIGTERM.

    No live network is used: the worker only polls a temp SQLite DB for queued
    jobs and sleeps when the queue is empty.
    """
    db_path = os.path.join(BACKEND_ROOT, "tmp_worker_test.db")
    proc = None
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{db_path}"
        env["JOB_TIMEOUT_SECONDS"] = "30"
        env["ENV"] = "dev"

        proc = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            cwd=BACKEND_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            time.sleep(4)
            assert proc.poll() is None, (
                "worker exited before the 4s liveness window; "
                f"output: {proc.stdout.read() if proc.stdout else ''}"
            )
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            assert proc.returncode == 0, (
                f"worker exited {proc.returncode} on SIGTERM, expected 0; "
                f"output: {proc.stdout.read() if proc.stdout else ''}"
            )
    finally:
        # Close the pipe even on the success path: an unclosed TextIOWrapper
        # is a real ResourceWarning, not noise to be filtered.
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()
        if os.path.exists(db_path):
            os.remove(db_path)
