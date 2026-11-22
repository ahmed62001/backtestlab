# Production Dockerfile for the BacktestLab backend.
# Multi-stage: slim Python, non-root user, pinned requirements, no dev deps.
# HEALTHCHECK on /health; uvicorn/gunicorn workers via env.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /srv

# Install only runtime dependencies first (layer cache).
COPY requirements.txt requirements-providers.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-providers.txt

# Copy the vendored Vibe-Trading agent (real vendor engine).
COPY vendor ./vendor

# Copy the application + data that the local market-data provider depends on.
COPY app ./app
COPY data ./data
COPY tests/fixtures ./tests/fixtures
COPY migrations ./migrations
COPY alembic.ini ./

# Runtime config (overridden by compose / .env).
# LOCAL_JWT_SECRET is intentionally unset: ENV=production makes boot fail unless
# the operator supplies a real 32+ character secret.
ENV DATABASE_URL=sqlite:///./backtestlab.db \
    ENV=production \
    CORS_ORIGINS=http://localhost:5173 \
    AUTH_PROVIDER=local \
    DATA_PROVIDER_DEFAULT=yfinance \
    MAX_BARS=5000 \
    JOB_TIMEOUT_SECONDS=120 \
    DATA_CACHE_DIR=/tmp/btlab_cache \
    DATA_UPLOAD_DIR=/tmp/btlab_uploads

# Create writable runtime dirs for the non-root user.
RUN mkdir -p /tmp/btlab_cache /tmp/btlab_uploads /srv && \
    chown -R appuser:appuser /tmp/btlab_cache /tmp/btlab_uploads /srv

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

USER appuser:appuser

# Workers via env. Default is one process: the in-process rate limiter and
# queue cap are per-process, so multiple workers multiply effective limits.
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --no-access-log --timeout-keep-alive 60"]
