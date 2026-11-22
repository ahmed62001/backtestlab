import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

vi.mock('../api/mock/session', () => ({ readSession: () => ({ token: 'test-token' }) }));
vi.mock('../lib/constants', () => ({ USE_MOCK: false, APP_NAME: 'BacktestLab' }));

import { ageLabel, classifyTick, freshnessThresholdSeconds, useStreamedQuotes, type StreamTick } from './useMarketStream';

function tick(sym: string, tsOffsetMs: number, price = 100): StreamTick {
  return {
    symbol: sym,
    price,
    currency: 'USD',
    exchange: 'NASDAQ',
    source: 'twelvedata',
    providerTimestamp: new Date(Date.now() - tsOffsetMs).toISOString(),
    receivedAt: new Date().toISOString(),
  };
}

describe('classifyTick freshness', () => {
  it('crypto goes stale faster than equities', () => {
    const now = Date.now();
    const age = 5 * 60_000; // 5 minutes
    expect(classifyTick(tick('BTC-USD', age), 'crypto', now)).toBe('stale');
    expect(classifyTick(tick('AAPL', age), 'equity', now)).toBe('live');
  });
  it('unknown asset class falls back to default threshold; missing tick is none', () => {
    expect(freshnessThresholdSeconds(undefined)).toBe(900);
    expect(classifyTick(undefined, 'crypto', Date.now())).toBe('none');
  });
  it('garbage timestamps are never live', () => {
    const bad: StreamTick = { ...tick('AAPL', 0), providerTimestamp: 'not-a-date' };
    expect(classifyTick(bad, 'equity', Date.now())).toBe('none');
  });
});

describe('ageLabel', () => {
  it('formats seconds, minutes, hours', () => {
    const now = Date.now();
    const iso = (off: number) => new Date(now - off).toISOString();
    expect(ageLabel(iso(30_000), now)).toBe('30s');
    expect(ageLabel(iso(9 * 60_000), now)).toBe('9m');
    expect(ageLabel(iso(3 * 3_600_000), now)).toBe('3h');
    expect(ageLabel('junk', now)).toBe('');
  });
});

class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  url: string;
  protocols?: string | string[];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
  emit(data: string) {
    this.onmessage?.({ data });
  }
}

type Snap = {
  status: string;
  ticks: Map<string, { price: number }>;
};

describe('stream client (mocked WebSocket)', () => {
  beforeEach(() => {
    FakeWS.instances = [];
    vi.stubGlobal('WebSocket', FakeWS);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ ticket: 'mock-ws-ticket', expiresIn: 30 }),
      })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('subscribes on connected and stores validated ticks only', async () => {
    const snapshots: Snap[] = [];
    function Probe() {
      const out = useStreamedQuotes(['AAPL']);
      snapshots.push(out.snapshot as unknown as Snap);
      return null;
    }
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(React.createElement(Probe));
    });
    await vi.waitFor(() => expect(FakeWS.instances.length).toBe(1));
    const ws = FakeWS.instances[0];
    expect(ws).toBeTruthy();
    expect(ws.url).toContain('/api/v1/market/stream');
    expect(ws.url).not.toContain('token=');
    expect(ws.url).not.toContain('test-token');
    expect(ws.protocols).toEqual(['btlab.v1', 'ticket.mock-ws-ticket']);
    const ts = new Date().toISOString();
    await act(async () => {
      ws.emit(JSON.stringify({ event: 'connected', status: 'connected', config: 'configured', maxSubscriptions: 8 }));
    });
    expect(ws.sent.some((s) => s.includes('AAPL'))).toBe(true);
    await act(async () => {
      ws.emit(JSON.stringify({ event: 'price', symbol: 'AAPL', price: 210.5, providerTimestamp: ts, receivedAt: ts }));
    });
    await act(async () => {
      ws.emit(JSON.stringify({ event: 'price', symbol: 'AAPL', price: -5, providerTimestamp: ts, receivedAt: ts }));
      ws.emit('not json{{');
    });
    const last = snapshots[snapshots.length - 1];
    expect(last.status).toBe('connected');
    expect(last.ticks.get('AAPL')?.price).toBe(210.5);

    // Unmount unsubscribes and destroys the singleton connection.
    await act(async () => {
      root.unmount();
    });
    expect(ws.sent.some((s) => s.includes('unsubscribe'))).toBe(true);
  });
});
