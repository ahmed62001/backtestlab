"""Phase 9 observability primitives.

- Structured JSON logging (stdlib only) with `LOG_FORMAT=json|text` and
  `LOG_LEVEL` env configuration.
- Request/job context stored in `contextvars` so every log line can carry
  `request_id`, `job_id`, `backtest_id`, `provider` and `symbol`.
- Secret/PII redaction filter (API keys, JWTs, passwords, Authorization
  headers and URL query parameters such as `?apikey=`).
- A tiny in-process Prometheus text registry (no extra dependency).
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import os
import re
import sys
import threading
import uuid
from typing import Any, Self

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="")
backtest_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("backtest_id", default="")
provider_var: contextvars.ContextVar[str] = contextvars.ContextVar("provider", default="")
symbol_var: contextvars.ContextVar[str] = contextvars.ContextVar("symbol", default="")

_CONTEXT_FIELDS: dict[str, contextvars.ContextVar[str]] = {
    "request_id": request_id_var,
    "job_id": job_id_var,
    "backtest_id": backtest_id_var,
    "provider": provider_var,
    "symbol": symbol_var,
}


def new_request_id() -> str:
    """Generate a 128-bit hex request id."""
    return uuid.uuid4().hex


def get_request_id() -> str:
    return request_id_var.get()


class log_context:
    """Bind structured fields for the duration of a block.

    Usage::

        with log_context(job_id=jid, provider="yfinance", symbol="AAPL"):
            ...
    """

    def __init__(self, **fields: Any):
        self._tokens: list[tuple[contextvars.ContextVar[str], contextvars.Token]] = []
        self._fields = fields

    def __enter__(self) -> Self:
        for key, value in self._fields.items():
            var = _CONTEXT_FIELDS.get(key)
            if var is None or value is None:
                continue
            self._tokens.append((var, var.set(str(value))))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for var, token in reversed(self._tokens):
            var.reset(token)
        self._tokens.clear()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
_compile = re.compile
_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # URL query params: ?apikey=..., &token=..., &key=...
    (
        _compile(r"(?i)([?&](?:api[_-]?key|apikey|token|key|secret|password)=)[^&\s\"']+"),
        r"\1***REDACTED***",
    ),
    # key=value / key: value / "password": "value" / Authorization: Bearer ...
    (
        _compile(
            r"(?i)((?:api[_-]?key|apikey|token|secret|password|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}&]+"
        ),
        r"\1***REDACTED***",
    ),
    # Bearer tokens
    (_compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+"), r"\1***REDACTED***"),
    # Standalone JWT (three base64url segments)
    (_compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "***REDACTED***"),
]


def redact(text: Any) -> str:
    """Return *text* with credentials removed. Never raises."""
    try:
        out = str(text)
    except Exception:  # pragma: no cover - defensive  # noqa: BLE001
        return "<unprintable>"
    for pattern, replacement in _REDACTION_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


class RedactionFilter(logging.Filter):
    """Redact credentials from every log record before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed record  # noqa: BLE001
            msg = str(record.msg)
        record.msg = redact(msg)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
_EXTRA_FIELDS = (
    "duration_ms",
    "cache",
    "status",
    "method",
    "path",
    "rows",
    "provider",
    "job_id",
    "backtest_id",
    "symbol",
    "request_id",
    "client",
    "user_agent",
    "query",
    "timings",
)


def _record_fields(record: logging.LogRecord) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field, var in _CONTEXT_FIELDS.items():
        value = var.get()
        if value:
            data[field] = value
    for field in _EXTRA_FIELDS:
        if hasattr(record, field):
            value = getattr(record, field)
            if value is not None and value != "":
                data[field] = value
    return data


class JsonFormatter(logging.Formatter):
    """Small, dependency-free JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        payload.update(_record_fields(record))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter that still includes request/job context."""

    def format(self, record: logging.LogRecord) -> str:
        ts = dt.datetime.fromtimestamp(record.created, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [ts, record.levelname, record.name]
        fields = _record_fields(record)
        if fields:
            parts.append(" ".join(f"{k}={v}" for k, v in fields.items()))
        parts.append(redact(record.getMessage()))
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + redact(self.formatException(record.exc_info))
        return line


_CONFIGURED = False


def configure_logging(force: bool = False) -> None:
    """Configure root logging once (idempotent unless *force* is set)."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.environ.get("LOG_FORMAT", "").strip().lower()
    if fmt not in ("json", "text"):
        fmt = "json" if os.environ.get("ENV", "dev") == "production" else "text"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Uvicorn emits its own access line by default while the HTTP middleware
    # below emits a structured "request completed" record. Both describe the
    # same request, so production logs contained every call twice. Disable the
    # duplicate unless the operator explicitly asks for it.
    if os.environ.get("UVICORN_ACCESS_LOG", "0") != "1":
        access = logging.getLogger("uvicorn.access")
        access.disabled = True
        access.propagate = False
        for h in list(access.handlers):
            access.removeHandler(h)
    _CONFIGURED = True


# ---------------------------------------------------------------------------
# Lightweight metrics (Prometheus text exposition, stdlib only)
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def inc(name: str, amount: float = 1.0, **labels: str) -> None:
    """Increment a counter. Label values are stringified."""
    key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
    with _metrics_lock:
        _counters[key] = _counters.get(key, 0.0) + amount


def _escape_label_value(value: str) -> str:
    """Escape a Prometheus label value (backslash, double quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics() -> str:
    """Render all counters in Prometheus text exposition format."""
    with _metrics_lock:
        snapshot = sorted(_counters.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    lines: list[str] = []
    for (name, labels), value in snapshot:
        if labels:
            label_text = ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in labels)
            lines.append(f"{name}{{{label_text}}} {value:g}")
        else:
            lines.append(f"{name} {value:g}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset_metrics() -> None:
    """Clear the in-process registry (tests)."""
    with _metrics_lock:
        _counters.clear()
