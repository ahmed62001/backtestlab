"""Phase 9 gates: JSON logging, request-id propagation, redaction, health/ready, metrics."""

from __future__ import annotations

import io
import json
import logging

from fastapi.testclient import TestClient


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord("backtestlab.test", logging.INFO, __file__, 1, msg, args, None)


def test_json_formatter_is_valid_json_with_context():
    from app.observability import JsonFormatter, log_context

    with log_context(
        request_id="rid-123", job_id="job-1", backtest_id="bt-1", provider="yfinance", symbol="AAPL"
    ):
        rec = _record("hello %s", "world")
        rec.duration_ms = 12.5
        rec.cache = "hit"
        rec.status = 200
        payload = json.loads(JsonFormatter().format(rec))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "backtestlab.test"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "rid-123"
    assert payload["job_id"] == "job-1"
    assert payload["backtest_id"] == "bt-1"
    assert payload["provider"] == "yfinance"
    assert payload["symbol"] == "AAPL"
    assert payload["duration_ms"] == 12.5
    assert payload["cache"] == "hit"
    assert payload["status"] == 200
    assert payload["ts"].endswith("+00:00")


def test_redaction_removes_api_keys_jwts_passwords_and_bearer():
    from app.observability import JsonFormatter, RedactionFilter, redact

    raw = (
        "GET https://api.example.com/v1?symbol=AAPL&apikey=secret12345&token=abc "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig "
        '{"password": "hunter2"} api_key=sk-live-999'
    )
    cleaned = redact(raw)
    for secret in ("secret12345", "eyJhbGciOiJIUzI1NiJ9", "hunter2", "sk-live-999"):
        assert secret not in cleaned
    assert "***REDACTED***" in cleaned

    rec = _record(raw)
    RedactionFilter().filter(rec)
    payload = json.loads(JsonFormatter().format(rec))
    assert "secret12345" not in payload["message"]
    assert "hunter2" not in payload["message"]
    assert "***REDACTED***" in payload["message"]


def test_request_id_propagation_in_header_and_json_logs():
    from app.main import create_app
    from app.observability import JsonFormatter

    app = create_app()
    logger = logging.getLogger("backtestlab")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/health", headers={"X-Request-ID": "trace-abc_123"})
        assert r.status_code == 200
        assert r.headers["x-request-id"] == "trace-abc_123"

        generated = c.get("/health")
        rid = generated.headers["x-request-id"]
        assert len(rid) == 32 and all(ch in "0123456789abcdef" for ch in rid)

        # Unreasonable client-supplied ids are replaced, never echoed.
        bad = c.get("/health", headers={"X-Request-ID": "bad id!"})
        assert bad.headers["x-request-id"] != "bad id!"
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    events = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    completed = [e for e in events if e.get("message") == "request completed"]
    assert completed, events
    traced = [e for e in completed if e.get("request_id") == "trace-abc_123"]
    assert traced, completed
    assert traced[0]["path"] == "/health"
    assert traced[0]["method"] == "GET"
    assert traced[0]["status"] == 200
    assert "duration_ms" in traced[0]


def test_health_ready_and_metrics_endpoints(monkeypatch):
    from app import main

    main.init_db()
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(main, "_migration_status", lambda: (None, "head-rev"))
    c = TestClient(main.create_app(), raise_server_exceptions=False)

    assert c.get("/health").json()["ok"] is True

    ready = c.get("/ready")
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert body["ok"] is True
    assert body["db"] == "ok"
    assert body["store"] == "ok"
    assert body["migrations"]["status"] == "unmanaged-dev"

    # At head is also ready.
    monkeypatch.setattr(main, "_migration_status", lambda: ("head-rev", "head-rev"))
    body = c.get("/ready").json()
    assert body["ok"] is True
    assert body["migrations"]["status"] == "head"

    # Behind head -> 503.
    monkeypatch.setattr(main, "_migration_status", lambda: ("old-rev", "head-rev"))
    behind = c.get("/ready")
    assert behind.status_code == 503
    assert behind.json()["migrations"]["status"] == "behind"

    # DB unreachable -> 503.
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(main, "engine", BrokenEngine())
    down = c.get("/ready")
    assert down.status_code == 503
    assert down.json()["db"]["status"] == "error"


def test_metrics_endpoint_is_prometheus_text():
    from app.main import create_app
    from app.observability import reset_metrics

    reset_metrics()
    c = TestClient(create_app(), raise_server_exceptions=False)
    assert c.get("/health").status_code == 200
    r = c.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'backtestlab_http_requests_total{method="GET",path="/health",status="200"}' in r.text
    assert "backtestlab_http_request_duration_ms_count" in r.text


def test_worker_cache_state_mapping():
    from app.worker import _cache_state

    assert _cache_state({"provenance": {"retrieval": "store"}}) == "hit"
    assert _cache_state({"provenance": {"retrieval": "live"}}) == "miss"
    assert _cache_state({"provenance": {"retrieval": "partial"}}) == "partial"
    assert _cache_state({"provenance": {"cache": "hit"}}) == "hit"
    assert _cache_state({}) == "miss"
