import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import ar from './ar.json';
import en from './en.json';

const stored = localStorage.getItem('bl_lang') as 'ar' | 'en' | null;

void i18n.use(initReactI18next).init({
  resources: { ar: { translation: ar }, en: { translation: en } },
  lng: stored ?? 'ar',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export function setLanguage(lng: 'ar' | 'en') {
  localStorage.setItem('bl_lang', lng);
  document.documentElement.lang = lng;
  document.documentElement.dir = lng === 'ar' ? 'rtl' : 'ltr';
  void i18n.changeLanguage(lng);
}

if (typeof document !== 'undefined') {
  const lng = (stored ?? 'ar') as 'ar' | 'en';
  document.documentElement.lang = lng;
  document.documentElement.dir = lng === 'ar' ? 'rtl' : 'ltr';
}

export default i18n;
