import { describe, expect, it } from 'vitest';
import ar from './ar.json';
import en from './en.json';

type Tree = { [key: string]: string | Tree };

function leafKeys(tree: Tree, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === 'string' ? [path] : leafKeys(value, path);
  });
}

const EN_KEYS = leafKeys(en as unknown as Tree).sort();
const AR_KEYS = leafKeys(ar as unknown as Tree).sort();

// Mirrors backend/app/synthetic_engine.py TEMPLATES (11 catalog entries).
const TEMPLATE_IDS = [
  'ma-crossover',
  'rsi',
  'breakout',
  'mean-reversion',
  'buy-hold',
  'ema-cross',
  'macd',
  'bollinger',
  'donchian',
  'dca',
  'momentum',
];

describe('i18n catalog parity', () => {
  it('English and Arabic expose the same leaf keys', () => {
    expect(AR_KEYS).toEqual(EN_KEYS);
  });

  it('every backend strategy template has a name and description', () => {
    for (const id of TEMPLATE_IDS) {
      expect(EN_KEYS).toContain(`templates.${id}.name`);
      expect(EN_KEYS).toContain(`templates.${id}.desc`);
      expect(AR_KEYS).toContain(`templates.${id}.name`);
      expect(AR_KEYS).toContain(`templates.${id}.desc`);
    }
  });

  it('result KPI tooltips and provider badges are translated', () => {
    for (const key of ['totalReturn', 'maxDrawdown', 'sharpe', 'winRate', 'trades', 'vsBuyHold']) {
      expect(EN_KEYS).toContain(`results.explain.${key}`);
      expect(AR_KEYS).toContain(`results.explain.${key}`);
    }
    expect(EN_KEYS).toContain('common.disabled');
    expect(AR_KEYS).toContain('common.disabled');
  });
});
