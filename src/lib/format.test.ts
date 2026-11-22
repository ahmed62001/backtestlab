import { describe, it, expect } from 'vitest';
import {
  formatCurrency,
  formatPercent,
  formatNumber,
  formatDate,
  ltrIsolate,
} from './format';

describe('formatNumber', () => {
  it('formats with two decimals and grouping (en)', () => {
    expect(formatNumber(1234.5, 'en')).toBe('1,234.50');
  });

  it('arabic still uses western digits (latn numbering system)', () => {
    const ar = formatNumber(1234.5, 'ar');
    expect(ar).not.toMatch(/[\u0660-\u0669]/); // no arabic-indic digits
    expect(ar).toMatch(/\d/);
  });
});

describe('formatCurrency', () => {
  it('formats USD with symbol and two decimals (en)', () => {
    expect(formatCurrency(1000, 'en')).toBe('$1,000.00');
  });

  it('formats negative values with minus sign', () => {
    const out = formatCurrency(-250.5, 'en');
    expect(out).toContain('250.50');
    expect(out.startsWith('-') || out.includes('(')).toBe(true);
  });
});

describe('formatPercent', () => {
  it('divides input by 100 before percent formatting', () => {
    expect(formatPercent(5, 'en')).toBe('5.00%');
    expect(formatPercent(50, 'en')).toBe('50.00%');
  });

  it('handles negative percent', () => {
    expect(formatPercent(-12.5, 'en')).toBe('-12.50%');
  });
});

describe('formatDate', () => {
  it('formats ISO date short (en)', () => {
    expect(formatDate('2023-01-15', 'en')).toMatch(/Jan/);
    expect(formatDate('2023-01-15', 'en')).toMatch(/15/);
    expect(formatDate('2023-01-15', 'en')).toMatch(/2023/);
  });

  it('accepts Date objects and numbers', () => {
    const d = new Date('2023-06-10T00:00:00Z');
    expect(formatDate(d, 'en')).toMatch(/Jun/);
    expect(formatDate(d.getTime(), 'en')).toMatch(/Jun/);
  });
});

describe('ltrIsolate', () => {
  it('wraps the string in LRI/PDI bidi marks', () => {
    expect(ltrIsolate('123.45')).toBe('\u2066123.45\u2069');
  });

  it('does not alter empty strings', () => {
    expect(ltrIsolate('')).toBe('\u2066\u2069');
  });
});