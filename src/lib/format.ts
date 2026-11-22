/**
 * Centralized Intl-based formatting (Step 1.5).
 * - Default to Western digits (latn) in BOTH languages for financial readability.
 * - NUMBERING_SYSTEM is the single switch point (e.g. change to 'arab' later).
 * - No ad-hoc toFixed/toLocaleString in components — use these helpers.
 * - Outputs are plain strings; render them LTR-isolated (<bdi dir="ltr">,
 *   className "ltr-isolate", or dir="ltr" wrapper).
 */

/** Single switch point for digit shaping. Keep 'latn' for financial readability. */
export const NUMBERING_SYSTEM = 'latn' as const;

export type AppLang = 'ar' | 'en';

function baseLocale(lang: AppLang): string {
  return `${lang}-u-nu-${NUMBERING_SYSTEM}`;
}

export function formatNumber(value: number, lang: AppLang = 'en', decimals = 2): string {
  return new Intl.NumberFormat(baseLocale(lang), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatCurrency(value: number, lang: AppLang = 'en', currency = 'USD', decimals = 2): string {
  return new Intl.NumberFormat(baseLocale(lang), {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatPercent(value: number, lang: AppLang = 'en', decimals = 2): string {
  return new Intl.NumberFormat(baseLocale(lang), {
    style: 'percent',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value / 100);
}

export function formatCompact(value: number, lang: AppLang = 'en'): string {
  return new Intl.NumberFormat(baseLocale(lang), { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function formatDate(d: string | number | Date, lang: AppLang = 'en'): string {
  const date = d instanceof Date ? d : new Date(d);
  return new Intl.DateTimeFormat(baseLocale(lang), { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
}

/** Wrap a pre-formatted string in LTR isolates so it renders safely inside RTL text. */
export function ltrIsolate(s: string): string {
  return `\u2066${s}\u2069`;
}
