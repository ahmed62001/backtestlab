import { describe, it, expect } from 'vitest';
import { tradesToCsv } from './csv';
import type { Trade } from '../types';

describe('tradesToCsv', () => {
  it('returns only the header for an empty list', () => {
    expect(tradesToCsv([])).toBe('id,date,side,price,qty,pnl,returnPct');
  });

  it('emits header + one row per trade with correct column order', () => {
    const trades: Trade[] = [
      { id: 'tr-1', date: '2023-01-01', side: 'buy', price: 150, qty: 10, pnl: 5.5, returnPct: 0.5 },
      { id: 'tr-2', date: '2023-01-02', side: 'sell', price: 155, qty: 5, pnl: null, returnPct: null },
    ];
    const out = tradesToCsv(trades);
    const lines = out.split('\n');
    expect(lines).toHaveLength(3);
    expect(lines[0]).toBe('id,date,side,price,qty,pnl,returnPct');
    expect(lines[1]).toBe('tr-1,2023-01-01,buy,150,10,5.5,0.5');
    // null values become empty fields
    expect(lines[2]).toBe('tr-2,2023-01-02,sell,155,5,,');
  });

  it('escapes fields containing quotes or commas', () => {
    const trades: Trade[] = [
      { id: 'tr-3', date: '2023,"weird"', side: 'buy', price: 100, qty: 1, pnl: 0, returnPct: 0 },
    ];
    const out = tradesToCsv(trades);
    const lines = out.split('\n');
    expect(lines[1]).toContain('"2023,""weird"""');
  });
});