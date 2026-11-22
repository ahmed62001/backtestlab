import { create } from 'zustand';

interface Prefs {
  theme: 'light' | 'dark';
  lang: 'ar' | 'en';
  toggleTheme: () => void;
  setLang: (l: 'ar' | 'en') => void;
}

function initialTheme(): 'light' | 'dark' {
  const s = localStorage.getItem('bl_theme');
  if (s === 'light' || s === 'dark') return s;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const usePrefs = create<Prefs>((set, get) => ({
  theme: typeof window === 'undefined' ? 'light' : initialTheme(),
  lang: (localStorage.getItem('bl_lang') as 'ar' | 'en' | null) ?? 'ar',
  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('bl_theme', next);
    document.documentElement.classList.toggle('dark', next === 'dark');
    set({ theme: next });
  },
  setLang: (lang) => {
    localStorage.setItem('bl_lang', lang);
    set({ lang });
  },
}));

export function applyThemeClass(theme: 'light' | 'dark') {
  document.documentElement.classList.toggle('dark', theme === 'dark');
}
