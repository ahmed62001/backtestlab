/** Single source of truth for every color in the app (Binding Rule 2).
 * Charts + components must import from here or use the CSS vars below.
 * NO hex/rgb literals anywhere else — enforced by scripts/check-colors.cjs.
 *
 * Visual identity: "Noir Amethyst & Molten Gold" (Dark) / "Ivory Silk & Royal Violet" (Light).
 * Deep velvet obsidian surfaces with vivid royal-violet primary brand, emerald-mint gains,
 * coral-rose losses, and molten-amber gold highlights. */
export const lightTokens = {
  bg: '#F8F6F1',
  card: '#FFFFFF',
  surface: '#EFECE4',
  text: '#14111F',
  mutedText: '#5E5A72',
  primary: '#6D28D9',
  primaryHover: '#5B21B6',
  ring: '#7C3AED',
  border: '#E4DFD3',
  input: '#CBC4B6',
  gain: '#059669',
  gainBg: '#ECFDF5',
  loss: '#E11D48',
  lossBg: '#FFF1F2',
  warn: '#B45309',
  warnBg: '#FFFBEB',
  gold: '#D97706',
  goldBg: '#FEF3C7',
  chartGrid: '#E4DFD3',
  chartAxis: '#5E5A72',
  chartTooltipBg: '#FFFFFF',
  chartTooltipBorder: '#E4DFD3',
  series: {
    strategy: '#6D28D9',
    benchmark: '#64748B',
    drawdown: '#E11D48',
    teal: '#0D9488',
    violet: '#7C3AED',
    amber: '#D97706',
    gain: '#059669',
  },
} as const;

export const darkTokens = {
  bg: '#0B0A10',
  card: '#14121D',
  surface: '#1D1A2B',
  text: '#F5F3FA',
  mutedText: '#9B95B0',
  primary: '#7C3AED',
  primaryHover: '#8B5CF6',
  ring: '#A78BFA',
  border: '#29253B',
  input: '#3B3554',
  gain: '#34D399',
  gainBg: '#063B2C',
  loss: '#FB7185',
  lossBg: '#440F1D',
  warn: '#FBBF24',
  warnBg: '#3E2A06',
  gold: '#F59E0B',
  goldBg: '#3E2A06',
  chartGrid: '#29253B',
  chartAxis: '#9B95B0',
  chartTooltipBg: '#14121D',
  chartTooltipBorder: '#29253B',
  series: {
    strategy: '#A78BFA',
    benchmark: '#9B95B0',
    drawdown: '#FB7185',
    teal: '#2DD4BF',
    violet: '#8B5CF6',
    amber: '#F59E0B',
    gain: '#34D399',
  },
} as const;

export type ThemeName = 'light' | 'dark';
export type Tokens = typeof lightTokens;

export function tokensFor(theme: ThemeName): Tokens {
  return theme === 'dark' ? (darkTokens as unknown as Tokens) : lightTokens;
}

export const spacing = {
  pageMobile: '1rem',
  pageDesktop: '1.5rem',
  cardGap: '1.25rem',
  radiusCard: '20px',
  radiusInput: '12px',
  sidebarWidth: '256px',
  containerMax: '1340px',
} as const;

export const typographyScale = {
  display: 'clamp(2.125rem, 4.4vw, 3.35rem)',
  h1: 'clamp(1.625rem, 3vw, 2.25rem)',
  h2: '1.375rem',
  body: '1rem',
  small: '0.875rem',
  caption: '0.75rem',
  kpiValue: '1.875rem',
} as const;
