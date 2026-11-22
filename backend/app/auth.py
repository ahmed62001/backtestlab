"""Local auth: argon2id (argon2-cffi) + transparent SHA-256 migration + JWT.

Migration: old hashes are bare hex sha256 (64 chars). On successful login with
an old hash, rehash with argon2id and store. verify_pw() returns
(verified: bool, upgraded_hash: str | None).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select, update

from .db import AuthAttempt, PasswordReset, RefreshToken, SessionLocal, User, init_db

SECRET = os.environ.get(
    "LOCAL_JWT_SECRET", "dev-secret-change-me-do-not-use-in-production-0001"
)
ACCESS_TTL_MIN = int(os.environ.get("JWT_ACCESS_MIN", "30"))
REFRESH_TTL_DAYS = int(os.environ.get("JWT_REFRESH_DAYS", "14"))
LOGIN_MAX_PER_MIN = int(os.environ.get("LOGIN_MAX_PER_MIN", "20"))
# Placeholder secrets that ship in the repository/Dockerfile/compose examples.
# They must never be accepted as a production signing key.
INSECURE_SECRETS = {
    "dev-secret-change-me",
    "dev-secret-change-me-do-not-use-in-production-0001",
    "change-me-to-a-random-32-plus-char-secret",
    "change-me-32-chars-minimum-please",
    "change-me",
    "changeme",
    "secret",
    "test-secret",
}
# Bound the in-process limiter so arbitrary email/IP keys cannot grow memory
# without limit. Entries older than the window are pruned first.
RATE_LIMIT_MAX_KEYS = int(os.environ.get("RATE_LIMIT_MAX_KEYS", "10000"))
bearer = HTTPBearer(auto_error=False)
_ph = PasswordHasher()
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()

# ---- Shared login lockout ---------------------------------------------------
# A wrong password is counted per account and per source IP over a rolling
# window. The ledger lives in the database so every API replica enforces the
# same limit (the old in-memory counter multiplied the effective threshold by
# the number of processes). Values are intentionally conservative; operators
# can tune them through the environment.
LOGIN_FAILURE_WINDOW_S = int(os.environ.get("LOGIN_FAILURE_WINDOW_S", "900"))
LOGIN_MAX_ACCOUNT_FAILURES = int(os.environ.get("LOGIN_MAX_ACCOUNT_FAILURES", "5"))
LOGIN_MAX_IP_FAILURES = int(os.environ.get("LOGIN_MAX_IP_FAILURES", "20"))
# Verified against when the account does not exist, so an attacker cannot tell
# "unknown email" from "wrong password" by timing the Argon2 work.
_DUMMY_HASH: str | None = None
_DUMMY_LOCK = threading.Lock()


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        with _DUMMY_LOCK:
            if _DUMMY_HASH is None:
                _DUMMY_HASH = hash_pw("", "timing-equalizer-not-a-real-password")
    return _DUMMY_HASH


def dummy_verify(password: str) -> None:
    """Spend the same Argon2 cost as a real verification (no enumeration)."""
    with contextlib.suppress(Exception):
        _ph.verify(_dummy_hash()[len("argon2:") :], password)


def _attempt_scopes(ip: str, email: str) -> list[tuple[str, int]]:
    return [
        ("login-em:" + (email or "").strip().lower(), LOGIN_MAX_ACCOUNT_FAILURES),
        ("login-ip:" + (ip or "?"), LOGIN_MAX_IP_FAILURES),
    ]


def login_lockout_remaining(ip: str, email: str) -> int:
    """Seconds until login is allowed again (0 when not locked)."""
    init_db()
    now = dt.datetime.now(dt.UTC)
    cutoff = (now - dt.timedelta(seconds=LOGIN_FAILURE_WINDOW_S)).isoformat()
    s = SessionLocal()
    try:
        for key, limit in _attempt_scopes(ip, email):
            count = (
                s.scalar(
                    select(func.count())
                    .select_from(AuthAttempt)
                    .where(AuthAttempt.scope_key == key, AuthAttempt.created_at >= cutoff)
                )
                or 0
            )
            if count < limit:
                continue
            oldest = s.scalar(
                select(func.min(AuthAttempt.created_at)).where(
                    AuthAttempt.scope_key == key, AuthAttempt.created_at >= cutoff
                )
            )
            try:
                oldest_dt = dt.datetime.fromisoformat(str(oldest))
                if oldest_dt.tzinfo is None:
                    oldest_dt = oldest_dt.replace(tzinfo=dt.UTC)
                remaining = LOGIN_FAILURE_WINDOW_S - (now - oldest_dt).total_seconds()
            except Exception:  # noqa: BLE001
                remaining = LOGIN_FAILURE_WINDOW_S
            return max(1, int(remaining))
        return 0
    finally:
        s.close()


def record_login_failure(ip: str, email: str) -> None:
    """Append a failed attempt for the account and IP, pruning old rows."""
    init_db()
    now = dt.datetime.now(dt.UTC)
    cutoff = (now - dt.timedelta(seconds=LOGIN_FAILURE_WINDOW_S)).isoformat()
    s = SessionLocal()
    try:
        s.execute(delete(AuthAttempt).where(AuthAttempt.created_at < cutoff))
        for key, _limit in _attempt_scopes(ip, email):
            s.add(AuthAttempt(scope_key=key, created_at=now.isoformat()))
        s.commit()
    finally:
        s.close()


def clear_login_failures(email: str) -> None:
    """Clear account-scoped failures after a successful login.

    IP-scoped failures are deliberately left in place: successes for one
    account must not reset an attacker's budget against other accounts.
    """
    init_db()
    s = SessionLocal()
    try:
        s.execute(
            delete(AuthAttempt).where(
                AuthAttempt.scope_key == "login-em:" + (email or "").strip().lower()
            )
        )
        s.commit()
    finally:
        s.close()


def reset_login_attempts() -> None:
    """Test/operator helper: drop the shared failure ledger."""
    init_db()
    s = SessionLocal()
    try:
        s.execute(delete(AuthAttempt))
        s.commit()
    finally:
        s.close()


def _legacy(email: str, password: str) -> str:
    return hashlib.sha256(f"{email.lower()}::{password}".encode()).hexdigest()


def hash_pw(email: str, password: str) -> str:
    del email
    return "argon2:" + _ph.hash(password)


def verify_pw(email: str, password: str, stored: str) -> tuple[bool, str | None]:
    if stored.startswith("argon2:"):
        try:
            _ph.verify(stored[len("argon2:") :], password)
        except VerifyMismatchError:
            return False, None
        if _ph.check_needs_rehash(stored[len("argon2:") :]):
            return True, hash_pw(email, password)
        return True, None
    if hmac.compare_digest(stored, _legacy(email, password)):
        return True, hash_pw(email, password)
    return False, None


def rate_limit(key: str) -> bool:
    """Fixed-window (60 s) limiter: Redis-backed when REDIS_URL is set, else bounded in-process."""
    from .redis_store import redis_rate_limit

    redis_res = redis_rate_limit(key, LOGIN_MAX_PER_MIN, 60)
    if redis_res is not None:
        return redis_res
    now = time.time()
    with _attempts_lock:
        lst = [t for t in _attempts.get(key, []) if now - t < 60]
        if key not in _attempts and len(_attempts) >= RATE_LIMIT_MAX_KEYS:
            for old_key in list(_attempts):
                if not _attempts[old_key] or now - _attempts[old_key][-1] >= 60:
                    del _attempts[old_key]
            while len(_attempts) >= RATE_LIMIT_MAX_KEYS:
                # dict preserves insertion order; evict the least-recent key.
                _attempts.pop(next(iter(_attempts)))
        _attempts[key] = lst
        if len(lst) >= LOGIN_MAX_PER_MIN:
            return False
        lst.append(now)
        return True


def make_token(user_id: str, kind: str = "access") -> str:
    if kind not in ("access", "refresh"):
        raise ValueError(f"unsupported token kind {kind!r}")
    now = dt.datetime.now(dt.UTC)
    ttl = (
        dt.timedelta(minutes=ACCESS_TTL_MIN)
        if kind == "access"
        else dt.timedelta(days=REFRESH_TTL_DAYS)
    )
    return jwt.encode(
        {"sub": user_id, "kind": kind, "jti": uuid.uuid4().hex, "iat": now, "exp": now + ttl},
        SECRET,
        algorithm="HS256",
    )


ACCESS_COOKIE = "btlab_access"
REFRESH_COOKIE = "btlab_refresh"
CSRF_COOKIE = "btlab_csrf"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _cookie_secure() -> bool:
    override = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if override in ("1", "true", "yes"):
        return True
    if override in ("0", "false", "no"):
        return False
    return os.environ.get("ENV", "dev") == "production"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> str:
    """Attach HttpOnly access/refresh cookies and a JS-readable CSRF cookie."""
    secure = _cookie_secure()
    csrf = secrets.token_urlsafe(24)
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=ACCESS_TTL_MIN * 60,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=REFRESH_TTL_DAYS * 86400,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=REFRESH_TTL_DAYS * 86400,
    )
    return csrf


def clear_auth_cookies(response: Response) -> None:
    """Clear auth and CSRF cookies."""
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def verify_csrf(request: Request) -> None:
    """Double-submit CSRF check for cookie-authenticated mutating requests."""
    cookie_val = request.cookies.get(CSRF_COOKIE, "")
    header_val = request.headers.get("x-csrf-token", "")
    if not cookie_val or not header_val or not hmac.compare_digest(cookie_val, header_val):
        raise HTTPException(
            403,
            detail={
                "code": "CSRF_FAILED",
                "message": "Invalid or missing CSRF token",
                "requestId": "-",
            },
        )


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
) -> User:
    token: str | None = None
    via_cookie = False
    if creds is not None and creds.credentials:
        token = creds.credentials
    else:
        cookie_tok = request.cookies.get(ACCESS_COOKIE)
        if cookie_tok:
            token = cookie_tok
            via_cookie = True

    if not token:
        raise HTTPException(
            401, detail={"code": "UNAUTHORIZED", "message": "Missing token", "requestId": "-"}
        )
    if via_cookie and request.method.upper() in _MUTATING_METHODS:
        verify_csrf(request)
    try:
        payload = jwt.decode(
            token,
            SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "kind"]},
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(
            401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid token", "requestId": "-"},
        ) from None
    # Only access tokens may authenticate API calls. Refresh tokens (including
    # replayed/revoked ones) must never be accepted as bearer credentials.
    if payload.get("kind") != "access":
        raise HTTPException(
            401,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Invalid token kind",
                "requestId": "-",
            },
        )
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            401, detail={"code": "UNAUTHORIZED", "message": "Invalid subject", "requestId": "-"}
        )
    init_db()
    s = SessionLocal()
    try:
        u = s.get(User, sub)
        if u is None:
            raise HTTPException(
                401, detail={"code": "UNAUTHORIZED", "message": "Unknown user", "requestId": "-"}
            )
        s.expunge(u)
        return u
    finally:
        s.close()


def validate_prod_boot() -> None:
    """Refuse production boot with weak config. Called from create_app()."""
    if os.environ.get("ENV", "dev") != "production":
        return
    errs = []
    low_secret = SECRET.strip().lower()
    if (
        len(SECRET) < 32
        or low_secret in INSECURE_SECRETS
        or any(marker in low_secret for marker in ("change-me", "placeholder", "example-secret"))
    ):
        errs.append("LOCAL_JWT_SECRET weak/missing or a shipped placeholder")
    co = os.environ.get("CORS_ORIGINS", "")
    if "*" in co:
        errs.append('CORS "*" forbidden in production')
    if os.environ.get("DATABASE_URL", "").startswith("sqlite"):
        errs.append("SQLite forbidden in production")
    if os.environ.get("DEBUG", "false").lower() == "true":
        errs.append("DEBUG on in production")
    if os.environ.get("ENGINE_MODE", "vendor") != "vendor":
        errs.append("ENGINE_MODE must be 'vendor' in production")
    if os.environ.get("AUTH_RESET_TOKEN_LOG", "0") == "1":
        errs.append("AUTH_RESET_TOKEN_LOG must be off in production")
    if os.environ.get("AUTH_PROVIDER", "local") != "local":
        # The Supabase/JWKS verifier is not wired into the request path. Fail
        # closed instead of silently continuing with local JWT auth while the
        # operator believes another provider is enforcing identity.
        errs.append("AUTH_PROVIDER other than 'local' is not implemented")
    if errs:
        raise RuntimeError("REFUSE_BOOT: " + "; ".join(errs))


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _new_refresh_token(s, user_id: str) -> tuple[str, str, str]:
    """Build a refresh JWT and add its JTI row to an existing session.

    The caller owns the transaction. Keeping the insert in the same
    transaction as the old-token revocation makes rotation atomic.
    """
    now = dt.datetime.now(dt.UTC)
    exp = now + dt.timedelta(days=REFRESH_TTL_DAYS)
    jti = uuid.uuid4().hex
    token = jwt.encode(
        {"sub": user_id, "kind": "refresh", "jti": jti, "iat": now, "exp": exp},
        SECRET,
        algorithm="HS256",
    )
    s.add(
        RefreshToken(
            id="rt-" + uuid.uuid4().hex[:8],
            user_id=user_id,
            jti=jti,
            revoked=False,
            expires_at=exp.isoformat(),
            created_at=_now_iso(),
        )
    )
    return token, jti, exp.isoformat()


def issue_refresh_token(user_id: str) -> tuple[str, str, str]:
    """Create a refresh JWT and persist its jti. Returns (token, jti, expires_at)."""
    init_db()
    s = SessionLocal()
    try:
        out = _new_refresh_token(s, user_id)
        s.commit()
    finally:
        s.close()
    return out


def _revoke_all_refresh_tokens(s, user_id: str) -> None:
    """Revoke every refresh token for a user (kept for operator/logout flows)."""
    for r in s.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id)).all():
        r.revoked = True


def rotate_refresh_token(refresh_token: str) -> tuple[str, str] | None:
    """Validate + rotate a refresh token atomically.

    Returns (new_access_token, new_refresh_token) on success, or None on failure
    (invalid, expired, reuse, or a lost concurrent-rotation race). On *reuse*
    (a jti presented after it was already revoked/used) every refresh token for
    that user is revoked and None is returned so the caller must re-login.

    The old JTI is claimed with a compare-and-set UPDATE (``revoked=False ->
    True``) and the replacement token is inserted in the same transaction.
    Two concurrent requests therefore cannot both rotate the same refresh
    token (D-RC-01).
    """
    try:
        payload = jwt.decode(refresh_token, SECRET, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None
    if payload.get("kind") != "refresh":
        return None
    user_id = payload.get("sub")
    jti = payload.get("jti")
    if not user_id or not jti:
        return None
    init_db()
    s = SessionLocal()
    try:
        row = s.scalar(
            select(RefreshToken).where(RefreshToken.jti == jti, RefreshToken.user_id == user_id)
        )
        if row is None:
            return None
        if row.revoked:
            # Already rotated/revoked: classic refresh-token reuse. Revoke the
            # entire family so a stolen token cannot outlive detection. A
            # concurrent request that lost the CAS race below does *not* take
            # this path and never revokes the winner's replacement token.
            _revoke_all_refresh_tokens(s, user_id)
            s.commit()
            return None
        try:
            exp = dt.datetime.fromisoformat(row.expires_at)
        except Exception:  # noqa: BLE001
            exp = None
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=dt.UTC)
        if exp is not None and dt.datetime.now(dt.UTC) > exp:
            s.execute(
                update(RefreshToken)
                .where(RefreshToken.id == row.id, RefreshToken.revoked.is_(False))
                .values(revoked=True)
            )
            s.commit()
            return None

        claimed = s.execute(
            update(RefreshToken)
            .where(RefreshToken.id == row.id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        if (getattr(claimed, "rowcount", 0) or 0) == 0:
            # A concurrent request won the rotation. Do not revoke the
            # winner's fresh token; this request simply fails closed.
            s.rollback()
            return None

        new_access = make_token(user_id, "access")
        new_refresh, _new_jti, _new_exp = _new_refresh_token(s, user_id)
        s.commit()
        return new_access, new_refresh
    finally:
        s.close()


def revoke_refresh_tokens(user_id: str, jti: str | None = None) -> None:
    """Revoke refresh token(s) for a user (all if jti is None)."""
    init_db()
    s = SessionLocal()
    try:
        if jti is None:
            rows = s.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id)).all()
        else:
            rows = s.scalars(
                select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.jti == jti)
            ).all()
        for r in rows:
            r.revoked = True
        s.commit()
    finally:
        s.close()


RESET_TTL_MIN = int(os.environ.get("PASSWORD_RESET_TTL_MIN", "30"))


def _hash_reset(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_password_reset(user_id: str) -> str:
    """Create a single-use reset token and return the raw value once.

    Only the SHA-256 hash is stored. Delivery is out of band (operator/CLI or
    a future mail integration); the HTTP endpoint never returns the token.
    """
    raw = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.UTC)
    exp = now + dt.timedelta(minutes=RESET_TTL_MIN)
    init_db()
    s = SessionLocal()
    try:
        s.add(
            PasswordReset(
                id="pr-" + uuid.uuid4().hex[:10],
                user_id=user_id,
                token_hash=_hash_reset(raw),
                expires_at=exp.isoformat(),
                used=False,
                created_at=now.isoformat(),
            )
        )
        s.commit()
    finally:
        s.close()
    return raw


def consume_password_reset(token: str) -> str | None:
    """Validate a reset token, mark it used and return the user id."""
    token = (token or "").strip()
    if not token:
        return None
    init_db()
    s = SessionLocal()
    try:
        row = s.scalar(select(PasswordReset).where(PasswordReset.token_hash == _hash_reset(token)))
        if row is None or row.used:
            return None
        try:
            exp = dt.datetime.fromisoformat(row.expires_at)
        except Exception:  # noqa: BLE001
            return None
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=dt.UTC)
        if dt.datetime.now(dt.UTC) > exp:
            return None
        # Atomically claim the token: only the request that flips used
        # False->True may proceed, so concurrent submissions cannot both reset.
        claimed = s.execute(
            update(PasswordReset)
            .where(PasswordReset.id == row.id, PasswordReset.used.is_(False))
            .values(used=True)
        )
        if (getattr(claimed, "rowcount", 0) or 0) == 0:
            s.rollback()
            return None
        s.commit()
        return row.user_id
    finally:
        s.close()
