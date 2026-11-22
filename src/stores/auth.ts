import { create } from 'zustand';
import type { User } from '../types';
import { USE_MOCK } from '../lib/constants';
import { apiGetMe, apiLogout } from '../api/client';
import { clearSession, readSession, writeSession } from '../api/mock/session';

interface AuthState {
  user: User | null;
  token: string | null;
  ready: boolean;
  init: () => void;
  setSession: (token: string, user: User, refreshToken?: string) => void;
  updateUser: (user: User) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  token: null,
  ready: false,
  init: () => {
    if (USE_MOCK) {
      const s = readSession();
      set({ user: s?.user ?? null, token: s?.token ?? null, ready: true });
      return;
    }
    // Scrub any legacy localStorage token persistence; real auth uses HttpOnly cookies.
    clearSession();
    apiGetMe()
      .then((user) => set({ user, token: null, ready: true }))
      .catch(() => set({ user: null, token: null, ready: true }));
  },
  setSession: (token, user, refreshToken) => {
    if (USE_MOCK) {
      writeSession(token, user, refreshToken);
      set({ token, user });
      return;
    }
    clearSession();
    set({ token: null, user });
  },
  updateUser: (user) => {
    if (USE_MOCK) {
      const t = readSession()?.token ?? '';
      writeSession(t, user);
    }
    set({ user });
  },
  logout: () => {
    void apiLogout();
    set({ token: null, user: null });
  },
}));
