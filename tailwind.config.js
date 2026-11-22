/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: 'rgb(var(--bg-rgb) / <alpha-value>)',
        card: 'rgb(var(--card-rgb) / <alpha-value>)',
        surface: 'rgb(var(--surface-rgb) / <alpha-value>)',
        ink: 'rgb(var(--text-rgb) / <alpha-value>)',
        mutedink: 'rgb(var(--muted-text-rgb) / <alpha-value>)',
        brand: {
          DEFAULT: 'rgb(var(--primary-rgb) / <alpha-value>)',
          hover: 'rgb(var(--primary-hover-rgb) / <alpha-value>)',
          ring: 'rgb(var(--ring-rgb) / <alpha-value>)',
        },
        gain: {
          DEFAULT: 'rgb(var(--gain-rgb) / <alpha-value>)',
          bg: 'rgb(var(--gain-bg-rgb) / <alpha-value>)',
        },
        loss: {
          DEFAULT: 'rgb(var(--loss-rgb) / <alpha-value>)',
          bg: 'rgb(var(--loss-bg-rgb) / <alpha-value>)',
        },
        warn: {
          DEFAULT: 'rgb(var(--warn-rgb) / <alpha-value>)',
          bg: 'rgb(var(--warn-bg-rgb) / <alpha-value>)',
        },
        gold: {
          DEFAULT: 'rgb(var(--gold-rgb) / <alpha-value>)',
          bg: 'rgb(var(--gold-bg-rgb) / <alpha-value>)',
        },
        line: 'rgb(var(--border-rgb) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', '"IBM Plex Sans Arabic"', 'system-ui', 'sans-serif'],
        arabic: ['"IBM Plex Sans Arabic"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', '"Cascadia Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        xl2: '20px',
        xl3: '26px',
      },
      boxShadow: {
        bento: 'var(--shadow-bento)',
        'bento-hover': 'var(--shadow-bento-hover)',
        glow: '0 8px 30px -6px var(--glow-brand)',
        'glow-gold': '0 8px 30px -6px var(--glow-gold)',
      },
      maxWidth: { shell: '1340px' },
    },
  },
  plugins: [],
};
