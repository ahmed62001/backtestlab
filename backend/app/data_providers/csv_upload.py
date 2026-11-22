"""csv_upload provider: user-supplied OHLCV CSV files (validated).

Files live under DATA_UPLOAD_DIR, **namespaced per authenticated user**:

    <DATA_UPLOAD_DIR>/<sha256(user_id)[:32]>/<SYMBOL>.csv

The user scope is always derived from the verified JWT subject on the server;
it is never accepted from the request body. Consequently two tenants may upload
the same symbol without colliding, and one tenant can never read another
tenant's file. Legacy un-namespaced files at the root of DATA_UPLOAD_DIR are
deliberately ignored (fail closed) because they carry no ownership record.

Validation on upload: required columns, UTC-parseable dates, strict ascending
order, duplicate detection, gap reporting, 5 MB size limit, max rows, formula
injection rejection, and the shared OHLCV normalization pipeline (finite,
positive prices, valid OHLC relationships and volume).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from .base import UPLOAD_DIR, Capabilities, Category, DataProvider, ProviderError

MAX_UPLOAD_BYTES = int("5242880")
MAX_UPLOAD_ROWS = int(os.environ.get("MAX_UPLOAD_ROWS", "5000"))
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
# Formula-injection prefixes that must be stripped/rejected in any echoed string.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _reject_formula_injection(df: pd.DataFrame) -> None:
    """Reject any cell whose string value starts with a formula prefix."""
    for col in df.columns:
        for idx, val in df[col].items():
            if isinstance(val, str) and val.strip() and val.strip()[0] in _FORMULA_PREFIXES:
                raise ProviderError(
                    "csv_upload",
                    "BAD_INPUT",
                    f"formula-injection prefix in column {col!r} at row {idx}",
                )


def user_scope(user_id: str) -> str:
    """Stable, filesystem-safe namespace for an authenticated user id.

    Hashing removes any possibility of path traversal via a crafted user id and
    keeps the on-disk name opaque.
    """
    uid = str(user_id or "")
    if not uid:
        raise ProviderError(
            "csv_upload", "BAD_INPUT", "csv_upload requires an authenticated user scope"
        )
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:32]


def _user_dir(user_id: str) -> Path:
    return UPLOAD_DIR / user_scope(user_id)


def _ensure_user_dir(user_id: str) -> Path:
    """Create/validate the per-user upload directory without following symlinks."""
    if not _upload_root_exists():
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    directory = _user_dir(user_id)
    try:
        mode = directory.lstat().st_mode
    except FileNotFoundError:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        return directory
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise OSError(f"Unsafe per-user upload path (not a real directory): {directory.name}")
    return directory


def _existing_symbol_path(symbol: str, user_id: str) -> Path | None:
    """Return the symbol file only if it is a regular non-symlink file."""
    path = _symbol_path(symbol, user_id)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise OSError(f"Unsafe uploaded file path (not a regular file): {path.name}")
    return path


def _atomic_write(path: Path, raw: bytes) -> None:
    """Write ``raw`` atomically via a restrictive temp file in the same dir."""
    if path.is_symlink():
        raise OSError(f"Refusing to overwrite symlinked upload: {path.name}")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".upload-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _symbol_path(symbol: str, user_id: str) -> Path:
    if not _SYMBOL_RE.match(symbol or ""):
        raise ProviderError("csv_upload", "BAD_INPUT", f"invalid symbol {symbol!r}")
    return _user_dir(user_id) / f"{symbol.upper()}.csv"


# Account deletion uses a two-phase upload cleanup so a database rollback can
# restore the user's files. The active per-user directory is atomically renamed
# to a private tombstone before the SQL transaction; after a successful commit
# the tombstone is removed. A failed removal stays on disk and is retried at the
# next application start (never by trusting a client-supplied path).
_PENDING_DELETE_RE = re.compile(r"^\.pending-delete-([0-9a-f]{32})-([0-9a-f]{32})$")
_upload_log = logging.getLogger("backtestlab.uploads")


def _upload_root_exists() -> bool:
    try:
        root_stat = UPLOAD_DIR.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise OSError(f"Upload root is not a real directory: {UPLOAD_DIR}")
    return True


def _remove_pending_path(path: Path) -> None:
    """Remove a quarantined per-user path without following its final symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        path.unlink()
    elif stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        raise OSError(f"Unexpected non-directory upload quarantine: {path.name}")


def prepare_user_upload_deletion(user_id: str) -> Path | None:
    """Atomically hide only this user's upload directory before DB deletion.

    The path is derived exclusively from the authenticated server-side user ID.
    The returned private tombstone can be restored if the SQL transaction rolls
    back, or removed after commit. A missing user directory is a normal case.
    """
    scope = user_scope(user_id)
    if not _upload_root_exists():
        return None
    active = UPLOAD_DIR / scope
    try:
        mode = active.lstat().st_mode
    except FileNotFoundError:
        return None
    if not (stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
        raise OSError(f"Unexpected per-user upload path type: {scope}")

    pending = UPLOAD_DIR / f".pending-delete-{scope}-{uuid.uuid4().hex}"
    os.replace(active, pending)
    return pending


def restore_user_upload_deletion(user_id: str, pending: Path | None) -> None:
    """Restore the quarantined directory if account deletion rolls back."""
    if pending is None:
        return
    scope = user_scope(user_id)
    if pending.parent != UPLOAD_DIR or not _PENDING_DELETE_RE.fullmatch(pending.name):
        raise OSError("Refusing to restore an upload path outside the deletion quarantine")
    match = _PENDING_DELETE_RE.fullmatch(pending.name)
    if match is None or match.group(1) != scope:
        raise OSError("Refusing to restore another user's upload quarantine")
    active = UPLOAD_DIR / scope
    try:
        active.lstat()
    except FileNotFoundError:
        os.replace(pending, active)
        return
    raise FileExistsError(f"Cannot restore upload directory; destination already exists: {scope}")


def finalize_user_upload_deletion(pending: Path | None) -> bool:
    """Remove a committed deletion's quarantine; failures remain retryable."""
    if pending is None:
        return True
    try:
        _remove_pending_path(pending)
    except OSError:
        _upload_log.exception("account upload cleanup deferred: quarantine=%s", pending.name)
        return False
    return True


def retry_pending_upload_deletions() -> None:
    """Recover only app-generated per-user tombstones using current DB ownership.

    If a process stopped after staging files but before the SQL commit, its user
    row still exists and the directory must be restored. If the commit finished,
    there is no user row and final removal is safe to retry.
    """
    try:
        if not _upload_root_exists():
            return
        pending_paths = [
            (path, _PENDING_DELETE_RE.fullmatch(path.name)) for path in UPLOAD_DIR.iterdir()
        ]
        pending_paths = [(path, match) for path, match in pending_paths if match is not None]
    except OSError:
        _upload_log.exception("could not inspect account upload deletion quarantine")
        return
    if not pending_paths:
        return

    from ..db import SessionLocal, User

    session = SessionLocal()
    try:
        live_scopes = {user_scope(uid): uid for uid in session.scalars(select(User.id)).all()}
    except Exception:
        _upload_log.exception("could not verify upload quarantine owners; cleanup deferred")
        return
    finally:
        session.close()

    for pending, match in pending_paths:
        if match is None:  # defensive: only matched quarantine names are queued
            continue
        scope = match.group(1)
        if scope in live_scopes:
            try:
                restore_user_upload_deletion(live_scopes[scope], pending)
            except OSError:
                _upload_log.exception(
                    "could not restore upload quarantine for active account: scope=%s", scope
                )
        else:
            finalize_user_upload_deletion(pending)


def validate_upload_csv(raw: bytes, symbol: str) -> pd.DataFrame:
    """Validate + parse an uploaded OHLCV CSV. Raises ProviderError."""
    if not _SYMBOL_RE.match(symbol or ""):
        raise ProviderError("csv_upload", "BAD_INPUT", f"invalid symbol {symbol!r}")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ProviderError(
            "csv_upload", "BAD_INPUT", f"file over {MAX_UPLOAD_BYTES // 1048576} MB limit"
        )
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        raise ProviderError("csv_upload", "BAD_INPUT", f"unparseable CSV: {e}") from e
    if len(df) > MAX_UPLOAD_ROWS:
        raise ProviderError("csv_upload", "BAD_INPUT", f"file over {MAX_UPLOAD_ROWS} rows limit")
    cols = {c.strip().lower() for c in df.columns}
    if "date" not in cols and "trade_date" not in cols:
        raise ProviderError(
            "csv_upload", "BAD_INPUT", "CSV needs a 'date' (or 'trade_date') column"
        )
    missing = [c for c in ("open", "high", "low", "close") if c not in cols]
    if missing:
        raise ProviderError("csv_upload", "BAD_INPUT", f"missing OHLC columns {missing}")
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    date_col = "date" if "date" in df.columns else "trade_date"
    parsed = pd.to_datetime(df[date_col], utc=True, errors="coerce")
    if parsed.isna().any():
        raise ProviderError("csv_upload", "BAD_INPUT", "unparseable dates in 'date' column")
    if not parsed.is_monotonic_increasing:
        raise ProviderError(
            "csv_upload", "BAD_INPUT", "dates must be strictly ascending (sort the file)"
        )
    if parsed.duplicated().any():
        raise ProviderError("csv_upload", "BAD_INPUT", "duplicate dates found")
    df = df.assign(**{date_col: parsed}).set_index(date_col)
    df = df.drop(columns=[c for c in ("unnamed: 0",) if c in df.columns])
    _reject_formula_injection(df)

    # Shared market-data validation pipeline. Uploads are strict: any dropped
    # row or coerced value rejects the whole file instead of silently storing
    # partial/invalid market data.
    from ..data_store.normalize import normalize_bars

    norm = normalize_bars(df, symbol, "csv_upload", "1d")
    bad = [
        w
        for w in norm.warnings
        if w["code"].startswith(("DROPPED_", "COERCED_")) or w["code"] == "EMPTY_DATA"
    ]
    if norm.frame.empty or norm.rows_dropped or bad:
        reason = bad[0]["message"] if bad else "invalid OHLCV rows"
        raise ProviderError("csv_upload", "BAD_INPUT", f"invalid OHLCV data: {reason}")
    return norm.frame


def upload_symbol_csv(symbol: str, raw: bytes, user_id: str) -> dict:
    """Validate + store an uploaded CSV for the authenticated *user_id*."""
    df = validate_upload_csv(raw, symbol)
    gaps = int((df.index.to_series().diff().dt.days > 10).sum())
    _ensure_user_dir(user_id)
    path = _symbol_path(symbol, user_id)
    _atomic_write(path, raw)
    return {
        "symbol": symbol.upper(),
        "rows": len(df),
        "start": str(df.index.min().date()),
        "end": str(df.index.max().date()),
        "largeGaps": gaps,
        # Do not disclose an absolute server path; the logical, user-scoped
        # relative name is enough for diagnostics.
        "path": f"{user_scope(user_id)}/{symbol.upper()}.csv",
    }


class CsvUploadProvider(DataProvider):
    id = "csv_upload"
    name_en = "Uploaded CSV"
    name_ar = "ملف CSV مرفوع"
    markets = ("equity", "crypto")
    intervals = ("1D",)
    license_class = "user_supplied"
    adjusted = None  # depends on the user's file
    cache_ok = False  # per-user data must never enter a shared cache
    capabilities = Capabilities(
        category=Category.UPLOAD,
        asset_classes=("equity", "crypto"),
        timeframes=("1D",),
        supports_adjusted=False,
        rate_limit_per_minute=0,
        description_en="User-uploaded OHLCV CSV files",
        description_ar="ملفات CSV مرفوعة من المستخدم لبيانات OHLCV",
    )

    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id

    def fetch_ohlcv_raw(
        self, symbol: str, start: str, end: str, interval: str = "1D"
    ) -> pd.DataFrame:
        if not self.user_id:
            raise ProviderError(
                self.id,
                "BAD_INPUT",
                "csv_upload requires an authenticated user scope",
            )
        path = _existing_symbol_path(symbol, self.user_id)
        if path is None:
            raise ProviderError(
                self.id,
                "UNKNOWN_SYMBOL",
                f"no uploaded CSV for {symbol!r} (POST /api/v1/data-providers/csv-upload)",
            )
        df = validate_upload_csv(path.read_bytes(), symbol)
        if start:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        if len(df) == 0:
            raise ProviderError(
                self.id, "EMPTY_DATA", f"uploaded file has no rows in {start}..{end}"
            )
        return df
