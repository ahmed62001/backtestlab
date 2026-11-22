"""Live tick streaming: Twelve Data adapter + shared manager + WS endpoint.

Architecture (see docs/MARKET_STREAMING_IMPLEMENTATION_REPORT.md):
- ``TwelveDataAdapter`` owns exactly one upstream WebSocket to Twelve Data,
  authenticates with ``TWELVEDATA_API_KEY`` (server-side only), subscribes
  to the union of symbols requested by frontend clients, parses provider
  events into normalized ticks, and reconnects with exponential backoff.
- ``StreamManager`` is a per-process singleton. It reference-counts symbols
  across all authenticated frontend WebSocket clients, deduplicates,
  enforces ``MARKET_STREAM_MAX_SUBSCRIPTIONS`` (default 8, matching the
  Twelve Data Basic/Grow trial entitlement), fans ticks out to bounded
  per-client queues (slow-client protection), and never opens a second
  upstream connection per browser tab.
- ``WS /api/v1/market/stream`` is the authenticated frontend endpoint.
  Clients first exchange their Bearer JWT at ``POST /api/v1/auth/ws-ticket``
  for a short-lived, single-use, user-bound WebSocket ticket, then pass it via
  the ``Sec-WebSocket-Protocol`` subprotocol (``btlab.v1, ticket.<ticket>``)
  or ``?ticket=<ticket>``. Long-lived JWTs are never accepted in the WS URL.

Live ticks NEVER go through the 24h historical REST cache. REST stays the
source for history; this layer is the only live-price path.

Deployment note: with ``UVICORN_WORKERS > 1`` each process runs its own
manager (documented limitation; default compose runs one worker).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, Response, WebSocket

from .auth import current_user

log = logging.getLogger("backtestlab.streaming")

# --------------------------------------------------------------------------
# Configuration (server-side environment only; never VITE_ prefixed)
# --------------------------------------------------------------------------


def streaming_enabled() -> bool:
    return os.environ.get("MARKET_STREAMING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def max_subscriptions() -> int:
    try:
        return max(1, min(200, int(os.environ.get("MARKET_STREAM_MAX_SUBSCRIPTIONS", "8"))))
    except ValueError:
        return 8


def _key_placeholders() -> set[str]:
    return {"", "your_twelvedata_api_key", "demo", "changeme"}


def _api_key() -> str | None:
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    return key if key not in _key_placeholders() else None


def _ws_url() -> str:
    return os.environ.get("TWELVEDATA_WS_URL", "wss://ws.twelvedata.com/v1/quotes/price")


def _config_status() -> str:
    """One of: not_configured | disabled | configured."""
    if not streaming_enabled():
        return "disabled"
    if _api_key() is None:
        return "not_configured"
    return "configured"


# Priority order for the shared subscription budget: when the number of
# distinct requested symbols exceeds the configured cap, symbols earlier in
# this list win.
LIVE_PRIORITY: tuple[str, ...] = (
    "BTC-USD", "EURUSD", "XAU/USD", "AAPL", "NVDA", "MSFT", "TSLA", "ETH-USD",
    "GBPUSD", "USDJPY", "GOOGL", "AMZN", "META", "SPY",
)

# Bounded per-client queue; overflow drops intermediate ticks (latest wins)
# and flags the client as degraded until it drains.
_CLIENT_QUEUE_SIZE = 200


# --------------------------------------------------------------------------
# Symbol mapping (canonical registry symbol <-> provider stream symbol)
# --------------------------------------------------------------------------


def stream_symbol_for(canonical: str) -> str:
    """Provider subscription symbol for a canonical registry symbol."""
    from .instruments import get_instrument
    from .data_providers.twelvedata import TwelveDataProvider

    inst = get_instrument(canonical)
    if inst is not None:
        override = inst.metadata.get("stream_symbol")
        if override:
            return str(override)
    return TwelveDataProvider()._twelvedata_symbol(canonical)


def canonical_for_stream_symbol(stream_symbol: str) -> str | None:
    """Reverse map: provider symbol -> canonical registry symbol."""
    from .instruments import list_instruments
    from .data_providers.twelvedata import TwelveDataProvider

    td = TwelveDataProvider()
    for inst in list_instruments():
        if (
            stream_symbol_for(inst.symbol) == stream_symbol
            or inst.symbol == stream_symbol
            or td._twelvedata_symbol(inst.symbol) == stream_symbol
        ):
            return inst.symbol
    if stream_symbol in ("BTC/USD", "BTC-USD"):
        return "BTC-USD"
    if stream_symbol in ("XAU/USD", "XAUUSD"):
        return "XAU/USD"
    return None


def _validate_universe(symbols: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split requested symbols into (valid canonical, {symbol: reason})."""
    from .instruments import get_instrument, normalize_symbol

    valid: list[str] = []
    errors: dict[str, str] = {}
    for raw in symbols:
        canonical = normalize_symbol(str(raw))
        inst = get_instrument(canonical)
        if inst is None:
            errors[str(raw)] = "unknown_symbol"
            continue
        if canonical not in valid:
            valid.append(canonical)
    return valid, errors


# --------------------------------------------------------------------------
# Normalized tick
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Tick:
    symbol: str  # canonical registry symbol
    price: float
    currency: str | None
    exchange: str | None
    provider_ts: dt.datetime
    received_at: dt.datetime
    day_volume: float | None = None
    bid: float | None = None
    ask: float | None = None

    def to_event(self) -> dict[str, Any]:
        latency_ms = int(max(0, (self.received_at - self.provider_ts).total_seconds() * 1000))
        return {
            "event": "price",
            "symbol": self.symbol,
            "price": self.price,
            "currency": self.currency,
            "exchange": self.exchange,
            "source": "twelvedata",
            "transport": "websocket",
            "quality": "live",
            "providerTimestamp": self.provider_ts.astimezone(dt.UTC).isoformat(),
            "receivedAt": self.received_at.astimezone(dt.UTC).isoformat(),
            "latencyMs": latency_ms,
            "dayVolume": self.day_volume,
            "bid": self.bid,
            "ask": self.ask,
        }


def _parse_price_event(msg: dict[str, Any]) -> Tick | None:
    """Validate a Twelve Data ``price`` event. Malformed -> None (dropped)."""
    stream_symbol = msg.get("symbol")
    if not isinstance(stream_symbol, str) or not stream_symbol:
        return None
    try:
        price = float(msg["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0 or price != price:  # reject non-positive / NaN
        return None
    canonical = canonical_for_stream_symbol(stream_symbol)
    if canonical is None:
        return None
    raw_ts = msg.get("timestamp")
    try:
        provider_ts = dt.datetime.fromtimestamp(float(raw_ts), tz=dt.UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None

    def _opt_float(key: str) -> float | None:
        try:
            v = float(msg[key])
            return v if v == v else None
        except (KeyError, TypeError, ValueError):
            return None

    return Tick(
        symbol=canonical,
        price=price,
        currency=str(msg.get("currency")) if msg.get("currency") else None,
        exchange=str(msg.get("exchange")) if msg.get("exchange") else None,
        provider_ts=provider_ts,
        received_at=dt.datetime.now(dt.UTC),
        day_volume=_opt_float("day_volume"),
        bid=_opt_float("bid"),
        ask=_opt_float("ask"),
    )


# --------------------------------------------------------------------------
# Twelve Data upstream adapter (one shared connection per process)
# --------------------------------------------------------------------------


class TwelveDataAdapter:
    """Thin, reconnecting WS client for the Twelve Data price stream.

    Owns the connection lifecycle; the manager owns subscription policy.
    Subscribes are sent as one comma-joined message; ``subscribe-status``
    events resolve per-symbol success/failure.
    """

    def __init__(self, url: str, api_key: str):
        self._url = url
        self._api_key = api_key
        self._ws: Any | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.on_tick: Any | None = None  # Callable[[Tick], None]
        self.on_status: Any | None = None  # Callable[[str, dict], None]
        self.stats = {"ticks": 0, "malformed": 0, "reconnects": 0}

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._ws = None

    async def _run(self) -> None:
        import websockets

        delay = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._url,
                    additional_headers={"X-TD-APIKEY": self._api_key},
                    open_timeout=10,
                    ping_interval=10,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    delay = 1.0
                    self._emit_status("connected", {})
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        await self._dispatch(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect loop must not die
                log.warning("twelvedata stream disconnected: %s", type(exc).__name__)
                if not self._stop.is_set():
                    self.stats["reconnects"] += 1
                    self._emit_status("reconnecting", {"retryInSec": round(delay, 1)})
                    await asyncio.sleep(delay + random.uniform(0, 0.5))
                    delay = min(delay * 2, 30.0)
            finally:
                self._ws = None

    def _emit_status(self, status: str, extra: dict[str, Any]) -> None:
        if self.on_status is not None:
            try:
                self.on_status(status, extra)
            except Exception:  # noqa: BLE001 - manager callbacks must not kill the loop
                log.exception("stream status callback failed")

    # -- subscriptions --------------------------------------------------------
    async def subscribe(self, stream_symbols: list[str]) -> None:
        if not stream_symbols or self._ws is None:
            return
        await self._ws.send(json.dumps({"action": "subscribe", "params": {"symbols": ",".join(stream_symbols)}}))

    async def unsubscribe(self, stream_symbols: list[str]) -> None:
        if not stream_symbols or self._ws is None:
            return
        await self._ws.send(json.dumps({"action": "unsubscribe", "params": {"symbols": ",".join(stream_symbols)}}))

    # -- inbound --------------------------------------------------------------
    async def _dispatch(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            self.stats["malformed"] += 1
            return
        if not isinstance(msg, dict):
            self.stats["malformed"] += 1
            return
        event = msg.get("event")
        if event == "price":
            tick = _parse_price_event(msg)
            if tick is None:
                self.stats["malformed"] += 1
                return
            self.stats["ticks"] += 1
            if self.on_tick is not None:
                self.on_tick(tick)
        elif event == "subscribe-status":
            # Per-symbol outcomes are surfaced via stream_status (manager
            # tracks membership); failures join the detail payload.
            self._emit_status("subscribe_status", {"raw": msg})
        else:
            # heartbeat / unknown events carry no price data: ignore.
            pass


# --------------------------------------------------------------------------
# Shared streaming manager (singleton per process)
# --------------------------------------------------------------------------


@dataclass
class _Client:
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE))
    symbols: set[str] = field(default_factory=set)
    high_priority: set[str] = field(default_factory=set)
    degraded: bool = False
    user_id: str = ""


class StreamManager:
    """Reference-counted fan-out over one upstream connection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refcount: dict[str, int] = {}
        self._clients: dict[str, _Client] = {}
        self._adapter: TwelveDataAdapter | None = None
        self._adapter_lock = threading.Lock()
        self.status: str = "disconnected"  # disconnected|connecting|connected|reconnecting|not_configured|disabled
        self._loop: asyncio.AbstractEventLoop | None = None
        self._upstream_synced: set[str] = set()
        self._latest_ticks: dict[str, Tick] = {}

    def get_latest_tick(self, symbol: str) -> Tick | None:
        from .instruments import normalize_symbol

        canon = normalize_symbol(symbol)
        with self._lock:
            tick = self._latest_ticks.get(symbol) or self._latest_ticks.get(canon)
            if tick is None and symbol == "BTC/USD":
                tick = self._latest_ticks.get("BTC-USD")
            elif tick is None and symbol == "BTC-USD":
                tick = self._latest_ticks.get("BTC/USD")
            return tick

    # -- client registration ----------------------------------------------------
    def register_client(self, client_id: str, user_id: str = "") -> asyncio.Queue:
        with self._lock:
            client = _Client(user_id=user_id)
            self._clients[client_id] = client
            return client.queue

    def unregister_client(self, client_id: str) -> list[str]:
        released: list[str] = []
        with self._lock:
            client = self._clients.pop(client_id, None)
            if client is not None:
                released = sorted(client.symbols)
                for sym in released:
                    nxt = self._refcount.get(sym, 1) - 1
                    if nxt <= 0:
                        self._refcount.pop(sym, None)
                    else:
                        self._refcount[sym] = nxt
        self._sync_upstream(released)
        return released

    # -- subscription policy ----------------------------------------------------
    def priority_key(self, canonical: str) -> tuple[int, str]:
        try:
            return (LIVE_PRIORITY.index(canonical), canonical)
        except ValueError:
            return (len(LIVE_PRIORITY), canonical)

    def acquire(
        self, client_id: str, symbols: list[str], *, high_priority: bool = False
    ) -> tuple[list[str], dict[str, str]]:
        """Return (granted, {symbol: reason}) applying validation + the cap."""
        valid, errors = _validate_universe(symbols)
        granted: list[str] = []
        evicted: list[str] = []
        with self._lock:
            client = self._clients.get(client_id)
            if client is None:
                return [], {"*": "unknown_client"}
            # Prune any stale zero-count entries defensively
            for k in [s for s, n in self._refcount.items() if n <= 0]:
                self._refcount.pop(k, None)
            cap = max_subscriptions()
            room = cap - len(self._refcount)
            ordered = sorted(valid, key=self.priority_key)
            for sym in ordered:
                if sym in self._refcount:
                    granted.append(sym)
                elif room > 0:
                    self._refcount[sym] = 0
                    room -= 1
                    granted.append(sym)
                elif high_priority:
                    # High-priority focus (e.g. active Asset page) may evict the
                    # lowest-priority background symbol so the viewed asset gets live ticks.
                    protected = set()
                    for c in self._clients.values():
                        protected.update(c.high_priority)
                    protected.update(granted)
                    evictable = [s for s in self._refcount if s not in protected]
                    if evictable:
                        victim = max(evictable, key=self.priority_key)
                        self._refcount.pop(victim, None)
                        for c in self._clients.values():
                            c.symbols.discard(victim)
                        evicted.append(victim)
                        self._refcount[sym] = 0
                        granted.append(sym)
                    else:
                        errors[sym] = "subscription_limit"
                else:
                    errors[sym] = "subscription_limit"
            newly = [s for s in granted if s not in client.symbols]
            for sym in granted:
                if sym not in client.symbols:
                    self._refcount[sym] = self._refcount.get(sym, 0) + 1
                    client.symbols.add(sym)
                if high_priority:
                    client.high_priority.add(sym)
        self._sync_upstream(newly + evicted)
        return granted, errors

    def release(self, client_id: str, symbols: list[str]) -> list[str]:
        from .instruments import normalize_symbol

        released: list[str] = []
        with self._lock:
            client = self._clients.get(client_id)
            if client is None:
                return released
            for raw_sym in symbols:
                sym = normalize_symbol(str(raw_sym))
                if sym in client.symbols:
                    client.symbols.discard(sym)
                    client.high_priority.discard(sym)
                    nxt = self._refcount.get(sym, 1) - 1
                    if nxt <= 0:
                        self._refcount.pop(sym, None)
                    else:
                        self._refcount[sym] = nxt
                    released.append(sym)
        self._sync_upstream(released)
        return released

    @property
    def current_symbols(self) -> list[str]:
        with self._lock:
            return [s for s, n in self._refcount.items() if n > 0]

    # -- upstream sync ------------------------------------------------------------
    def _sync_upstream(self, changed: list[str]) -> None:
        """Subscribe/unsubscribe the upstream for symbols whose refcount
        just crossed a threshold. `changed` is advisory; the authoritative
        upstream set is derived from refcounts vs. the last-synced set."""
        with self._lock:
            desired = {s for s, n in self._refcount.items() if n > 0}
            current = set(getattr(self, "_upstream_synced", set()))
            to_add = sorted(desired - current, key=self.priority_key)
            to_remove = sorted(current - desired)
            self._upstream_synced = set(desired)
        if _config_status() != "configured":
            return
        adapter = self._get_adapter()
        if adapter is None:
            return
        stream_add = [stream_symbol_for(s) for s in to_add]
        stream_remove = [stream_symbol_for(s) for s in to_remove]
        if not stream_add and not stream_remove:
            return
        loop = self._loop
        if loop is not None and loop.is_running():
            if stream_add:
                asyncio.run_coroutine_threadsafe(adapter.subscribe(stream_add), loop)
            if stream_remove:
                asyncio.run_coroutine_threadsafe(adapter.unsubscribe(stream_remove), loop)

    def _get_adapter(self) -> TwelveDataAdapter | None:
        with self._adapter_lock:
            if self._adapter is None:
                key = _api_key()
                if key is None:
                    return None
                adapter = TwelveDataAdapter(_ws_url(), key)
                adapter.on_tick = self._fanout_tick
                adapter.on_status = self._on_upstream_status
                self._adapter = adapter
            return self._adapter

    def _on_upstream_status(self, status: str, extra: dict[str, Any]) -> None:
        if status == "connected":
            self.status = "connected"
            # Resubscribe everything after a reconnect.
            loop = self._loop
            adapter = self._adapter
            if loop is not None and loop.is_running() and adapter is not None:
                symbols = [stream_symbol_for(s) for s in self.current_symbols]
                if symbols:
                    asyncio.run_coroutine_threadsafe(adapter.subscribe(symbols), loop)
            self._broadcast({"event": "stream_status", "status": "connected", "provider": "twelvedata"})
        elif status == "reconnecting":
            self.status = "reconnecting"
            self._broadcast({"event": "stream_status", "status": "reconnecting", **extra})
        elif status == "subscribe_status":
            raw = extra.get("raw") or {}
            fails = raw.get("fails") or []
            for f in fails:
                if isinstance(f, dict) and f.get("symbol"):
                    canonical = canonical_for_stream_symbol(str(f["symbol"]))
                    if canonical:
                        # Free the slot held by a provider-rejected symbol so it
                        # does not permanently consume the subscription budget.
                        with self._lock:
                            self._refcount.pop(canonical, None)
                            self._upstream_synced.discard(canonical)
                            for c in self._clients.values():
                                c.symbols.discard(canonical)
                                c.high_priority.discard(canonical)
                        self._broadcast(
                            {"event": "subscription_error", "symbol": canonical, "reason": "provider_rejected"}
                        )

    # -- fan-out --------------------------------------------------------------------
    def _fanout_tick(self, tick: Tick) -> None:
        event = tick.to_event()
        with self._lock:
            self._latest_ticks[tick.symbol] = tick
            if tick.symbol == "BTC-USD":
                self._latest_ticks["BTC/USD"] = tick
            elif tick.symbol == "BTC/USD":
                self._latest_ticks["BTC-USD"] = tick
            targets = [
                c for c in self._clients.values()
                if tick.symbol in c.symbols
                or (tick.symbol == "BTC-USD" and "BTC/USD" in c.symbols)
                or (tick.symbol == "BTC/USD" and "BTC-USD" in c.symbols)
            ]
        for client in targets:
            try:
                if "BTC/USD" in client.symbols and event.get("symbol") == "BTC-USD":
                    evt = dict(event)
                    evt["symbol"] = "BTC/USD"
                    client.queue.put_nowait(evt)
                else:
                    client.queue.put_nowait(event)
                if client.degraded and client.queue.qsize() < _CLIENT_QUEUE_SIZE // 2:
                    client.degraded = False
                    self._send_now(client, {"event": "stream_status", "status": "recovered"})
            except asyncio.QueueFull:
                # Slow consumer: drop (latest-wins on next tick) and flag once.
                if not client.degraded:
                    client.degraded = True
                    self._send_now(client, {"event": "stream_status", "status": "degraded", "reason": "slow_client"})

    def _broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            self._send_now(client, event)

    @staticmethod
    def _send_now(client: _Client, event: dict[str, Any]) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            client.queue.put_nowait(event)

    # -- connection bootstrap ---------------------------------------------------------
    def ensure_started(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if _config_status() != "configured":
            self.status = _config_status()
            return
        adapter = self._get_adapter()
        if adapter is None:
            return
        self.status = "connecting"
        adapter.start()


_manager = StreamManager()


def get_manager() -> StreamManager:
    return _manager


# --------------------------------------------------------------------------
# Authenticated WebSocket endpoint (short-lived, single-use tickets)
# --------------------------------------------------------------------------

router = APIRouter()

WS_TICKET_TTL_S = int(os.environ.get("WS_TICKET_TTL_S", "30"))
_WS_TICKET_MAX = 4096
_WS_SUBPROTOCOL = "btlab.v1"
_ws_tickets: dict[str, tuple[str, float]] = {}  # sha256(ticket) -> (user_id, expires_at)
_ws_ticket_lock = threading.Lock()


def issue_ws_ticket(user_id: str) -> tuple[str, int]:
    """Create a cryptographically secure, short-lived, single-use WS ticket."""
    from .redis_store import store_ws_ticket

    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    ttl = max(1, WS_TICKET_TTL_S)
    if store_ws_ticket(digest, user_id, ttl):
        return raw, ttl
    now = time.monotonic()
    with _ws_ticket_lock:
        expired = [k for k, (_, exp) in _ws_tickets.items() if exp <= now]
        for k in expired:
            del _ws_tickets[k]
        while len(_ws_tickets) >= _WS_TICKET_MAX:
            oldest = next(iter(_ws_tickets))
            del _ws_tickets[oldest]
        _ws_tickets[digest] = (user_id, now + ttl)
    return raw, ttl


def consume_ws_ticket(ticket: str) -> str | None:
    """Atomically consume a WS ticket. Returns user_id if valid and unexpired."""
    from .redis_store import consume_ws_ticket_redis

    if not ticket or len(ticket) > 256:
        return None
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    handled, uid = consume_ws_ticket_redis(digest)
    if handled:
        return uid
    with _ws_ticket_lock:
        entry = _ws_tickets.pop(digest, None)
    if entry is None:
        return None
    user_id, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return user_id


def clear_ws_tickets() -> None:
    """Clear all pending WS tickets (for test isolation)."""
    with _ws_ticket_lock:
        _ws_tickets.clear()


@router.post("/api/v1/auth/ws-ticket")
def create_ws_ticket(response: Response, u: Any = Depends(current_user)) -> dict[str, Any]:  # noqa: B008
    """Exchange a valid Bearer JWT for a short-lived, single-use WS ticket."""
    response.headers["Cache-Control"] = "no-store"
    ticket, ttl = issue_ws_ticket(u.id)
    return {"ticket": ticket, "expiresIn": ttl}


def _extract_ws_ticket(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Extract (ticket, selected_subprotocol) from subprotocol header or ?ticket=.

    Long-lived JWTs in ``?token=`` are never accepted.
    """
    proto_hdr = websocket.headers.get("sec-websocket-protocol") or ""
    if proto_hdr:
        parts = [p.strip() for p in proto_hdr.split(",") if p.strip()]
        selected = _WS_SUBPROTOCOL if _WS_SUBPROTOCOL in parts else None
        for p in parts:
            if p.startswith("ticket.") and len(p) > 7:
                return p[7:], selected
    ticket = websocket.query_params.get("ticket") or ""
    if ticket:
        return ticket, None
    return None, None


def _authenticate(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Validate and atomically consume a single-use WS ticket.

    Returns (user_id, selected_subprotocol). Credentials are never logged.
    """
    from .db import SessionLocal, User  # noqa: PLC0415

    ticket, subprotocol = _extract_ws_ticket(websocket)
    if not ticket:
        return None, None
    user_id = consume_ws_ticket(ticket)
    if not user_id:
        return None, None
    if user_id == "public":
        return ("public", subprotocol)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        return (user.id, subprotocol) if user is not None else (None, None)
    finally:
        db.close()


@router.websocket("/api/v1/market/stream")
async def market_stream(websocket: WebSocket) -> None:
    user_id, subprotocol = _authenticate(websocket)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept(subprotocol=subprotocol)

    import uuid

    client_id = uuid.uuid4().hex
    manager = get_manager()
    loop = asyncio.get_running_loop()
    queue = manager.register_client(client_id, user_id=user_id)
    config = _config_status()
    if config == "configured":
        manager.ensure_started(loop)

    await websocket.send_json(
        {
            "event": "connected",
            "status": manager.status,
            "config": config,
            "provider": "twelvedata",
            "maxSubscriptions": max_subscriptions(),
        }
    )

    async def pump() -> None:
        while True:
            event = await queue.get()
            await websocket.send_json(event)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                await websocket.send_json({"event": "error", "reason": "invalid_json"})
                continue
            if not isinstance(msg, dict):
                await websocket.send_json({"event": "error", "reason": "invalid_message"})
                continue
            action = msg.get("action")
            symbols = msg.get("symbols") or []
            if not isinstance(symbols, list):
                await websocket.send_json({"event": "error", "reason": "invalid_symbols"})
                continue
            if action == "subscribe":
                if config != "configured":
                    reason = "not_configured" if config == "not_configured" else "disabled"
                    await websocket.send_json(
                        {
                            "event": "subscription_error",
                            "errors": [{"symbol": str(s), "reason": reason} for s in symbols],
                            "status": config,
                        }
                    )
                    continue
                high_priority = str(msg.get("priority", "")).strip().lower() == "high"
                granted, errors = manager.acquire(
                    client_id, [str(s) for s in symbols], high_priority=high_priority
                )
                if granted:
                    await websocket.send_json({"event": "subscribed", "symbols": granted})
                if errors:
                    await websocket.send_json(
                        {
                            "event": "subscription_error",
                            "errors": [{"symbol": s, "reason": r} for s, r in errors.items()],
                        }
                    )
            elif action == "unsubscribe":
                released = manager.release(client_id, [str(s) for s in symbols])
                await websocket.send_json({"event": "unsubscribed", "symbols": released})
            else:
                await websocket.send_json({"event": "error", "reason": "unknown_action"})
    except Exception:  # noqa: BLE001 - client disconnects land here
        pass
    finally:
        pump_task.cancel()
        manager.unregister_client(client_id)
        with contextlib.suppress(Exception):
            await websocket.close()
