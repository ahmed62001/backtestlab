import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { useDraft } from './draft';

const KEY = 'bl_run_draft';

beforeEach(() => {
  localStorage.removeItem(KEY);
});
afterEach(() => {
  localStorage.removeItem(KEY);
});

describe('useDraft', () => {
  it('starts with defaults', () => {
    const s = useDraft.getState();
    expect(s.config).toMatchObject({
      initialCapital: 10000,
      feePct: 0.1,
      from: '2022-01-01',
      to: '2023-12-31',
      oosPct: 20,
      step: 0,
    });
  });

  it('set merges patch into config and persists to localStorage', () => {
    useDraft.getState().set({ initialCapital: 5000, step: 1 });
    const s = useDraft.getState();
    expect(s.config.initialCapital).toBe(5000);
    expect(s.config.step).toBe(1);
    // untouched defaults are preserved (deep merge, not replace)
    expect(s.config.feePct).toBe(0.1);
    expect(s.config.from).toBe('2022-01-01');

    const raw = localStorage.getItem(KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.initialCapital).toBe(5000);
    expect(parsed.step).toBe(1);
  });

  it('reset restores defaults and clears localStorage', () => {
    useDraft.getState().set({ initialCapital: 99999, step: 2 });
    useDraft.getState().reset();

    const s = useDraft.getState();
    expect(s.config.initialCapital).toBe(10000);
    expect(s.config.step).toBe(0);
    expect(localStorage.getItem(KEY)).toBeNull();
  });
});