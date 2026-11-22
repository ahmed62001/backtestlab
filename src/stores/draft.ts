import { create } from 'zustand';
import type { BacktestConfig, TemplateId } from '../types';

const KEY = 'bl_run_draft';

export interface RunDraft extends Partial<BacktestConfig> {
  oosPct?: number;
  step?: number;
}

interface Draft {
  config: RunDraft;
  set: (patch: RunDraft) => void;
  reset: () => void;
}

const DEFAULTS: RunDraft = {
  initialCapital: 10000,
  feePct: 0.1,
  from: '2022-01-01',
  to: '2023-12-31',
  oosPct: 20,
  step: 0,
};

function load(): RunDraft {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...(JSON.parse(raw) as RunDraft) };
  } catch {
    /* ignore */
  }
  return { ...DEFAULTS };
}

export const useDraft = create<Draft>((set) => ({
  config: typeof window === 'undefined' ? { ...DEFAULTS } : load(),
  set: (patch) =>
    set((s) => {
      const config = { ...s.config, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(config));
      } catch {
        /* ignore */
      }
      return { config };
    }),
  reset: () => {
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    set({ config: { ...DEFAULTS } });
  },
}));

export function prefillFromTemplate(templateId: TemplateId, params: Record<string, number | string>) {
  useDraft.getState().set({ templateId, params, step: 1 });
}
