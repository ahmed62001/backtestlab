"""SQLite-backed storage (SQLAlchemy 2.x, portable to Postgres)."""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker, validates

log = logging.getLogger("backtestlab.db")


def _json_has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_json_has_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_json_has_non_finite(v) for v in value)
    return False


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./backtestlab.db")

# ---- Connection/engine tuning (Phase 10) ----------------------------------
# PostgreSQL: pre-ping + bounded pool + recycling + server-side statement
# timeout so a wedged query can never pin a request/worker forever.
# SQLite: WAL for concurrent readers during a write + busy_timeout so writers
# wait instead of failing immediately with "database is locked".
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
DB_POOL_RECYCLE_S = int(os.environ.get("DB_POOL_RECYCLE_S", "1800"))
DB_POOL_TIMEOUT_S = int(os.environ.get("DB_POOL_TIMEOUT_S", "30"))
DB_STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
SQLITE_BUSY_TIMEOUT_MS = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "5000"))


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory_sqlite(url: str) -> bool:
    return _is_sqlite(url) and (":memory:" in url or url.endswith("sqlite://"))


def _configure_sqlite_connection(dbapi_conn, _record) -> None:
    """Apply per-connection PRAGMAs: WAL + busy_timeout + foreign keys."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        # In-memory databases do not support WAL; journal_mode returns "memory".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _build_engine(url: str):
    if _is_sqlite(url):
        eng = create_engine(
            url,
            connect_args={
                "check_same_thread": False,
                "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000.0,
            },
            future=True,
            pool_pre_ping=True,
        )
        if not _is_memory_sqlite(url):
            event.listen(eng, "connect", _configure_sqlite_connection)
        return eng

    connect_args: dict[str, object] = {}
    if url.startswith("postgresql"):
        # psycopg accepts libpq `options`; statement_timeout bounds every query.
        connect_args["options"] = f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"
        connect_args["application_name"] = "backtestlab"
    return create_engine(
        url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_recycle=DB_POOL_RECYCLE_S,
        pool_timeout=DB_POOL_TIMEOUT_S,
        pool_use_lifo=True,
    )


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300), default="")
    plan: Mapped[str] = mapped_column(String(16), default="free")
    language: Mapped[str] = mapped_column(String(8), default="ar")
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    template_id: Mapped[str] = mapped_column(String(64), default="ma-crossover")
    asset: Mapped[str] = mapped_column(String(32), default="AAPL")
    status: Mapped[str] = mapped_column(String(16), default="done")
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )
    total_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    vs_buy_hold_pct: Mapped[float] = mapped_column(Float, default=0.0)
    # Data provenance (Phase 2): which provider/symbol/range/hash were used.
    data_provider: Mapped[str] = mapped_column(String(32), default="")
    data_symbol: Mapped[str] = mapped_column(String(32), default="")
    data_interval: Mapped[str] = mapped_column(String(16), default="")
    data_start: Mapped[str] = mapped_column(String(32), default="")
    data_end: Mapped[str] = mapped_column(String(32), default="")
    data_hash: Mapped[str] = mapped_column(String(80), default="")
    data_rows: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")

    @validates(
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "win_rate_pct",
        "vs_buy_hold_pct",
    )
    def _validate_finite_metric(self, key: str, value: Any) -> Any:
        """Reject NaN/Inf at the persistence boundary on every backend (D-PH5-03)."""
        if value is None:
            return value
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be numeric") from None
        if not math.isfinite(numeric):
            raise ValueError(f"{key} must be finite, got {value!r}")
        return numeric

    @validates("config_json", "result_json")
    def _validate_finite_json(self, key: str, value: Any) -> Any:
        if value is None:
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            # Leave malformed JSON handling to the existing write path.
            return value
        if _json_has_non_finite(parsed):
            raise ValueError(f"{key} must not contain NaN/Infinity")
        return value

    __table_args__ = (
        # Hot list query: WHERE user_id = ? ORDER BY created_at DESC
        Index("ix_backtests_user_created", "user_id", "created_at"),
        # Status filters per user (queued/running/done dashboards).
        Index("ix_backtests_user_status", "user_id", "status"),
    )


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(16), index=True)
    used: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # One usage counter per user per day; the queue increments it atomically.
        UniqueConstraint("user_id", "day", name="uq_usage_user_day"),
        # Daily-limit lookup: WHERE user_id = ? AND day = ?
        Index("ix_usage_user_day", "user_id", "day"),
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    backtest_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    idem_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )
    # --- Phase 10 lease/heartbeat/retry metadata ---------------------------
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[str] = mapped_column(String(32), default="")
    finished_at: Mapped[str] = mapped_column(String(32), default="")
    heartbeat_at: Mapped[str] = mapped_column(String(32), default="")
    lease_expires_at: Mapped[str] = mapped_column(String(32), default="")
    next_attempt_at: Mapped[str] = mapped_column(String(32), default="")
    worker_id: Mapped[str] = mapped_column(String(64), default="")

    __table_args__ = (
        # Worker poll query: WHERE status = 'queued' AND next_attempt_at <= now
        Index("ix_jobs_status_next_attempt", "status", "next_attempt_at"),
        # Crash recovery: find running jobs whose lease has expired.
        Index("ix_jobs_status_lease", "status", "lease_expires_at"),
        # Owner-scoped history.
        Index("ix_jobs_user_created", "user_id", "created_at"),
        # Idempotency: at most one non-empty idem key per user.
        Index(
            "uq_jobs_user_idem",
            "user_id",
            "idem_key",
            unique=True,
            sqlite_where=text("idem_key <> ''"),
            postgresql_where=text("idem_key <> ''"),
        ),
    )


class RefreshToken(Base):
    """Persisted refresh-token JTI for rotation + reuse detection."""

    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class PasswordReset(Base):
    """Single-use password-reset token (hash at rest)."""

    __tablename__ = "password_resets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[str] = mapped_column(String(32))
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class AuthAttempt(Base):
    """A failed authentication attempt for shared (cross-process) lockout.

    Rows are append-only and pruned by the auth module after the failure
    window. Keeping the counter in the database means two API replicas (or the
    API and a CLI process) enforce one lockout instead of independent
    per-process counters.
    """

    __tablename__ = "auth_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # e.g. "login-em:user@example.com" or "login-ip:203.0.113.9"
    scope_key: Mapped[str] = mapped_column(String(320), index=True)
    created_at: Mapped[str] = mapped_column(String(32), index=True)

    __table_args__ = (
        # Window count: WHERE scope_key = ? AND created_at >= ?
        Index("ix_auth_attempts_scope_created", "scope_key", "created_at"),
    )


class ProviderState(Base):
    """Shared per-provider runtime state (anti-bot cooldown).

    Provider challenges are per-source-IP, not per-process: once Stooq (or any
    provider) answers with a challenge or 429, every API/worker process should
    stop hammering it for the cooldown window. Stored in the DB so the state is
    shared and survives a process restart.
    """

    __tablename__ = "provider_state"
    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cooldown_until: Mapped[str] = mapped_column(String(32), default="")
    reason: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class BillingCustomer(Base):
    """Stripe customer & subscription state per user (inactive when BILLING_ENABLED=false)."""

    __tablename__ = "billing_customers"
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="stripe")
    customer_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    subscription_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    plan: Mapped[str] = mapped_column(String(16), default="free")
    status: Mapped[str] = mapped_column(String(32), default="inactive")
    current_period_end: Mapped[str] = mapped_column(String(32), default="")
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class BillingEvent(Base):
    """Idempotency ledger for processed billing webhook events."""

    __tablename__ = "billing_events"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), default="")
    processed_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )


class MarketInstrument(Base):
    """A canonical instrument (symbol + asset class) tracked in the market data store."""

    __tablename__ = "market_instruments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    asset_class: Mapped[str] = mapped_column(String(16), index=True)
    currency: Mapped[str | None] = mapped_column(String(8), default=None)
    exchange: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    name: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )

    __table_args__ = (
        UniqueConstraint("symbol", "asset_class", name="uq_market_instrument_symbol_asset_class"),
    )


class MarketBar(Base):
    """A single OHLCV bar from a provider, stored in the market data store."""

    __tablename__ = "market_bars"
    instrument_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("market_instruments.id"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)  # UTC ISO-8601
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float | None] = mapped_column(Float, default=None)
    adjusted: Mapped[bool] = mapped_column(default=False, primary_key=True)
    ingested_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )

    __table_args__ = (
        Index("ix_market_bars_instrument_timeframe_ts", "instrument_id", "timeframe", "ts"),
    )


class MarketCoverage(Base):
    """Coverage record describing which ranges are already stored per instrument/provider/timeframe."""

    __tablename__ = "market_coverage"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("market_instruments.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    adjusted: Mapped[bool] = mapped_column(default=False, index=True)
    range_start: Mapped[str] = mapped_column(String(32), index=True)
    range_end: Mapped[str] = mapped_column(String(32), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    data_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    fetched_at: Mapped[str] = mapped_column(
        String(32), default=lambda: dt.datetime.now(dt.UTC).isoformat()
    )
    expires_at: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="complete", index=True
    )  # complete|partial|failed
    last_error_code: Mapped[str | None] = mapped_column(String(32), default=None)

    __table_args__ = (
        # One logical coverage row per instrument/provider/timeframe/adjusted/range.
        UniqueConstraint(
            "instrument_id",
            "provider",
            "timeframe",
            "adjusted",
            "range_start",
            "range_end",
            name="uq_market_coverage_key",
        ),
    )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def today_key() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
