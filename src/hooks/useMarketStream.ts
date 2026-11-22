/**
 * Authenticated market-stream client (singleton) + per-asset freshness.
 *
 * One WebSocket per browser tab talks to `WS /api/v1/market/stream`. The
 * backend owns the single shared upstream Twelve Data connection and the
 * subscription budget; this client only sends subscribe/unsubscribe for the
 * symbols active components need and maintains the latest tick per symbol.
 *
 * Live state is computed from provider timestamps, never from the presence
 * of a connection: a symbol is LIVE only while a fresh provider-originated
 * tick exists. Thresholds are asset-class specific (crypto ticks
 * continuously; FX trades 24/5; equities tick only during sessions, so a
 * quiet equity feed goes STALE rather than being called live).
 */

import { useEffect, useRef, useState } from 'react';
import { getCsrfToken } from '../api/client';
import { readSession } from '../api/mock/session';
import { USE_MOCK } from '../lib/constants';

function wsEndpointUrl(): string {
  const base = import.meta.env.VITE_API_BASE as string | undefined;
  if (base && /^https?:\/\//.test(base)) {
    const wsBase = base.replace(/^http/, 'ws').replace(/\/$/, '');
    return `${wsBase}/api/v1/market/stream`;
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/api/v1/market/stream`;
}

function ticketEndpointUrl(): string {
  const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
  return `${base.replace(/\/$/, '')}/api/v1/auth/ws-ticket`;
}

function readAccessToken(): string | null {
  if (USE_MOCK) return null; // demo mode has no backend stream: never connect
  try {
    return readSession()?.token ?? null;
  } catch {
    return null;
  }
}

async function fetchWsTicket(token: string | null): Promise<string | null> {
  try {
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
    const res = await fetch(ticketEndpointUrl(), {
      method: 'POST',
      credentials: 'include',
      headers,
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { ticket?: unknown };
    return typeof data.ticket === 'string' && data.ticket ? data.ticket : null;
  } catch {
    return null;
  }
}

async function fetchPublicWsTicket(): Promise<string | null> {
  try {
    const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
    const res = await fetch(`${base.replace(/\/$/, '')}/api/v1/public/market/ws-ticket`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { ticket?: unknown };
    return typeof data.ticket === 'string' && data.ticket ? data.ticket : null;
  } catch {
    return null;
  }
}

export type StreamConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'disconnected'
  | 'not_configured'
  | 'disabled';

export interface StreamTick {
  symbol: string;
  price: number;
  currency: string | null;
  exchange: string | null;
  source: string;
  providerTimestamp: string;
  receivedAt: string;
}

export interface StreamSnapshot {
  status: StreamConnectionStatus;
  maxSubscriptions: number;
  ticks: Map<string, StreamTick>;
  subscriptionErrors: Map<string, string>;
}

const FRESHNESS_SECONDS: Record<string, number> = {
  crypto: 120,
  fx: 600,
  equity: 1200,
  index: 1200,
  commodity: 1200,
  default: 900,
};

export function freshnessThresholdSeconds(assetClass: string | undefined): number {
  return FRESHNESS_SECONDS[assetClass ?? 'default'] ?? FRESHNESS_SECONDS.default;
}

export type TickFreshness = 'live' | 'stale';

export function classifyTick(
  tick: StreamTick | undefined,
  assetClass: string | undefined,
  now: number,
): TickFreshness | 'none' {
  if (!tick) return 'none';
  const ts = new Date(tick.providerTimestamp).getTime();
  if (Number.isNaN(ts)) return 'none';
  const ageSeconds = Math.max(0, (now - ts) / 1000);
  return ageSeconds <= freshnessThresholdSeconds(assetClass) ? 'live' : 'stale';
}

export function ageLabel(providerTimestamp: string, now: number): string {
  const ts = new Date(providerTimestamp).getTime();
  if (Number.isNaN(ts)) return '';
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h`;
}

type Listener = (snapshot: StreamSnapshot) => void;

class StreamClient {
  private ws: WebSocket | null = null;
  private snapshot: StreamSnapshot = {
    status: 'disconnected',
    maxSubscriptions: 8,
    ticks: new Map(),
    subscriptionErrors: new Map(),
  };
  private listeners = new Set<Listener>();
  private wanted = new Map<string, number>();
  private highPriority = new Map<string, number>();
  private retryTimer: number | null = null;
  private retryDelayMs = 1000;
  private destroyed = false;
  private connecting = false;

  subscribe(symbols: string[], priority: 'high' | 'normal' = 'normal') {
    const clean = symbols.filter(Boolean);
    const toSend: string[] = [];
    for (const s of clean) {
      const prev = this.wanted.get(s) ?? 0;
      this.wanted.set(s, prev + 1);
      if (priority === 'high') {
        this.highPriority.set(s, (this.highPriority.get(s) ?? 0) + 1);
      }
      if (prev === 0 || priority === 'high') {
        toSend.push(s);
      }
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN && toSend.length) {
      const payload: Record<string, unknown> = { action: 'subscribe', symbols: toSend };
      if (priority === 'high') payload.priority = 'high';
      this.ws.send(JSON.stringify(payload));
    }
    if (clean.length) this.connect();
  }

  unsubscribe(symbols: string[], priority: 'high' | 'normal' = 'normal') {
    const released: string[] = [];
    for (const s of symbols) {
      if (!s) continue;
      if (priority === 'high') {
        const hp = (this.highPriority.get(s) ?? 0) - 1;
        if (hp <= 0) this.highPriority.delete(s);
        else this.highPriority.set(s, hp);
      }
      const next = (this.wanted.get(s) ?? 0) - 1;
      if (next <= 0) {
        if (this.wanted.delete(s)) released.push(s);
      } else {
        this.wanted.set(s, next);
      }
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN && released.length) {
      this.ws.send(JSON.stringify({ action: 'unsubscribe', symbols: released }));
    }
  }

  private connect() {
    if (this.destroyed || this.connecting) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    if (USE_MOCK) {
      this.setStatus('disconnected');
      return;
    }
    const token = readAccessToken();
    this.connecting = true;
    this.setStatus('connecting');
    void this.openWithTicket(token);
  }

  private async openWithTicket(token: string | null) {
    try {
      let ticket = await fetchWsTicket(token);
      if (!ticket) {
        ticket = await fetchPublicWsTicket();
      }
      if (this.destroyed) return;
      if (!ticket) {
        this.setStatus('disconnected');
        this.scheduleRetry();
        return;
      }
      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsEndpointUrl(), ['btlab.v1', `ticket.${ticket}`]);
      } catch {
        this.scheduleRetry();
        return;
      }
      this.ws = ws;
      ws.onopen = () => {
        this.retryDelayMs = 1000;
      };
      ws.onmessage = (ev) => this.handle(ev.data);
      ws.onerror = () => {
        // onclose follows and performs the state transition.
      };
      ws.onclose = () => {
        if (this.ws === ws) this.ws = null;
        this.setStatus(this.destroyed ? 'disconnected' : 'reconnecting');
        this.scheduleRetry();
      };
    } finally {
      this.connecting = false;
    }
  }

  private scheduleRetry() {
    if (this.destroyed || this.ws) return;
    if (this.retryTimer !== null) return;
    const delay = this.retryDelayMs + Math.floor(Math.random() * 500);
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, 10_000);
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  destroy() {
    this.destroyed = true;
    if (this.retryTimer !== null) window.clearTimeout(this.retryTimer);
    this.retryTimer = null;
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
  }

  private setStatus(status: StreamConnectionStatus) {
    if (this.snapshot.status === status) return;
    this.snapshot = { ...this.snapshot, status };
    this.emit();
  }

  private emit() {
    for (const l of this.listeners) l(this.snapshot);
  }

  private handle(raw: string) {
    let msg: unknown;
    try {
      msg = JSON.parse(raw);
    } catch {
      return; // malformed server frames are never rendered
    }
    if (!msg || typeof msg !== 'object') return;
    const m = msg as { event?: string; status?: string; config?: string; maxSubscriptions?: number; symbol?: string; price?: number; errors?: { symbol: string; reason: string }[] };
    switch (m.event) {
      case 'connected': {
        const config = m.config === 'not_configured' ? 'not_configured' : m.status === 'disabled' ? 'disabled' : 'connected';
        const next: StreamSnapshot = {
          ...this.snapshot,
          status: config as StreamConnectionStatus,
          maxSubscriptions: m.maxSubscriptions ?? this.snapshot.maxSubscriptions,
        };
        this.snapshot = next;
        if (this.wanted.size && this.ws && this.ws.readyState === WebSocket.OPEN) {
          const hp = [...this.highPriority.keys()];
          const normal = [...this.wanted.keys()].filter((s) => !this.highPriority.has(s));
          if (hp.length) {
            this.ws.send(JSON.stringify({ action: 'subscribe', symbols: hp, priority: 'high' }));
          }
          if (normal.length) {
            this.ws.send(JSON.stringify({ action: 'subscribe', symbols: normal }));
          }
        }
        this.emit();
        break;
      }
      case 'subscribed': {
        const syms = (msg as { symbols?: unknown }).symbols;
        if (Array.isArray(syms) && this.snapshot.subscriptionErrors.size > 0) {
          const errors = new Map(this.snapshot.subscriptionErrors);
          let changed = false;
          for (const s of syms) {
            if (typeof s === 'string' && errors.delete(s)) changed = true;
          }
          if (changed) this.snapshot = { ...this.snapshot, subscriptionErrors: errors };
        }
        this.emit();
        break;
      }
      case 'subscription_error': {
        const errors = new Map(this.snapshot.subscriptionErrors);
        if (m.symbol && m.errors === undefined) errors.set(m.symbol, 'provider_rejected');
        for (const e of m.errors ?? []) errors.set(e.symbol, e.reason);
        this.snapshot = { ...this.snapshot, subscriptionErrors: errors };
        this.emit();
        break;
      }
      case 'price': {
        if (typeof m.symbol !== 'string' || typeof m.price !== 'number' || !(m.price > 0)) break;
        const ticks = new Map(this.snapshot.ticks);
        const tickData: StreamTick = {
          symbol: m.symbol,
          price: m.price,
          currency: (msg as { currency?: string | null }).currency ?? null,
          exchange: (msg as { exchange?: string | null }).exchange ?? null,
          source: 'twelvedata',
          providerTimestamp: (msg as { providerTimestamp?: string }).providerTimestamp ?? '',
          receivedAt: (msg as { receivedAt?: string }).receivedAt ?? new Date().toISOString(),
        };
        ticks.set(m.symbol, tickData);
        if (m.symbol === 'BTC-USD') {
          ticks.set('BTC/USD', { ...tickData, symbol: 'BTC/USD' });
        } else if (m.symbol === 'BTC/USD') {
          ticks.set('BTC-USD', { ...tickData, symbol: 'BTC-USD' });
        } else if (m.symbol === 'XAU/USD') {
          ticks.set('XAUUSD', { ...tickData, symbol: 'XAUUSD' });
        } else if (m.symbol === 'XAUUSD') {
          ticks.set('XAU/USD', { ...tickData, symbol: 'XAU/USD' });
        } else if (/^[A-Z]{6}$/.test(m.symbol)) {
          const slash = `${m.symbol.slice(0, 3)}/${m.symbol.slice(3)}`;
          ticks.set(slash, { ...tickData, symbol: slash });
        }
        const errors = this.snapshot.subscriptionErrors.has(m.symbol)
          ? (() => {
              const nextErr = new Map(this.snapshot.subscriptionErrors);
              nextErr.delete(m.symbol);
              return nextErr;
            })()
          : this.snapshot.subscriptionErrors;
        this.snapshot = { ...this.snapshot, ticks, subscriptionErrors: errors };
        this.emit();
        break;
      }
      case 'stream_status': {
        this.setStatus(m.status === 'reconnecting' ? 'reconnecting' : 'connected');
        break;
      }
      default:
        break;
    }
  }

  addListener(l: Listener) {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
      // The singleton connection intentionally outlives mount cycles
      // (React StrictMode double-mounts): destroying here would leave a
      // permanently dead client. The browser closes it on page unload.
    };
  }

  snapshotNow(): StreamSnapshot {
    return this.snapshot;
  }
}

let client: StreamClient | null = null;

function getClient(): StreamClient {
  if (!client) client = new StreamClient();
  return client;
}

/**
 * Subscribe the calling component's symbols for as long as it is mounted.
 * Returns the shared snapshot; ticks update at most once per upstream event.
 */
export function useStreamedQuotes(
  symbols: string[],
  assetClassBySymbol: Map<string, string> = new Map(),
  options?: { priority?: 'high' | 'normal' },
) {
  const key = symbols.join(',');
  const priority = options?.priority ?? 'normal';
  const [snapshot, setSnapshot] = useState<StreamSnapshot>(() => getClient().snapshotNow());
  const classesRef = useRef(assetClassBySymbol);
  classesRef.current = assetClassBySymbol;

  useEffect(() => {
    const c = getClient();
    const wanted = key ? key.split(',').filter(Boolean) : [];
    const off = c.addListener(setSnapshot);
    if (wanted.length) c.subscribe(wanted, priority);
    setSnapshot(c.snapshotNow());
    return () => {
      if (wanted.length) c.unsubscribe(wanted, priority);
      off();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, priority]);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const liveTicks = new Map<string, StreamTick>();
  for (const [sym, tick] of snapshot.ticks) {
    if (classifyTick(tick, classesRef.current.get(sym), now) === 'live') liveTicks.set(sym, tick);
  }
  return { snapshot, liveTicks, now };
}
