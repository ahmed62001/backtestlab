# BacktestLab - Design Decisions (Step 0 - ui-ux-pro MCP)

Source: ui-ux-pro MCP queries run 2026-10-16 (get_design_system + search_all + search_patterns + search_styles + search_components + search_platforms + search_stack).
Stack: Vite + React 18 + TS + Tailwind + Recharts. RTL-first (Arabic default, English second).

## 1. Product archetype
- Financial Dashboard + Analytics Dashboard: KPI Cards Row | Chart Grid | Data Tables | Filters Sidebar.
- Secondary styles: Minimalism + Data-Dense + Trust and Authority (no glassmorphism/neon).
- Clarity over aesthetics. Color-coded data priority. Accuracy paramount.

## 2. Color system (WCAG AA, light + dark)
Light: bg #F8FAFC, card #FFFFFF, text #0F172A, muted #475569 (AA on white).
Primary #1D4ED8 (blue-700, white text on buttons), hover #1E40AF, ring #1D4ED8.
Border #E2E8F0, input #CBD5E1. Gain text #047857 on bg #ECFDF5. Loss text #DC2626 on bg #FEF2F2.
Warn text #B45309 on bg #FFFBEB. Charts: #2563EB #0D9488 #64748B #059669 #DC2626 #D97706.
Dark: bg #0F172A, card #1E293B, text #F1F5F9, muted #CBD5E1, border #334155.
Primary #60A5FA, ring #93C5FD, gain #34D399, loss #F87171. Never pure black bg. No glow effects.
Deltas always pair color with icon + text (lucide TrendingUp/Down), never color alone.

## 3. Typography (RTL-first, bilingual)
- Arabic default: IBM Plex Sans Arabic (400/500/600/700). Latin/numbers: Inter with tnum tabular figures.
- Mono only for tickers/code-ish values. Scale: display 30-36 / h1 24-30 / h2 20 / body 15-16 / small 13-14.
- Arabic body line-height 1.6. Numbers, tickers, dates, chart axes: dir=ltr, unicode-bidi isolate.

## 4. Layout and spacing
- Shell: sidebar 260px sticky desktop, drawer below 1024px. Topbar: theme/lang/notifications/avatar.
- Content max-w 1280px, padding 1rem mobile to 1.5rem desktop, card gap 1rem.
- Radius 12px cards / 8px inputs. KPI grid auto-fit minmax(200px,1fr) 4-2-1. Chart grid 12-col.
- Logical properties only: ms-/me-/ps-/pe-/start-/end-, border-e. Back-to-top on long pages.

## 5. Components (shadcn-style + Tailwind, Radix primitives)
- Buttons min-height 44px, variants primary/outline/destructive/ghost, visible focus-visible 2px ring.
- KPI card: 13px muted label + 28px/700 tabular value + delta chip + 40px sparkline. Hover lift -2px.
- Tables: 12px uppercase muted header, row hover, overflow-x-auto wrapper, aria-sort, pagination.
- Modal confirm for destructive actions. Tooltip for plain-language param explainers.
- Badge: Halal-screened, difficulty, risk. Toast role=status/alert. Skeleton shimmer. EmptyState icon+copy+CTA.
- Theme toggle sun #F59E0B / moon rotation crossfade, 40px target.
- Pricing: monthly/yearly pill toggle + save badge, popular card highlighted, FAQ accordion.

## 6. Charts: Recharts (justified)
- Recharts over lightweight-charts: declarative React, theming, custom RTL-aware tooltips,
  ResponsiveContainer, SSR-safe, 9/10 framework compat. lightweight-charts is canvas-heavy, weaker a11y.
- Equity: AreaChart strategy vs dashed benchmark + localized tooltip. Drawdown: red area below zero.
- Monthly heatmap: CSS grid table with diverging bg, AA text. Sparklines 100x40, no axes.
- Every chart: title, text legend, role=img + aria-label + adjacent SR summary, reduced-motion disables animation.

## 7. Forms/auth (RHForm + Zod)
- Inline errors + aria-invalid/describedby. Submit loading/success/error states. Show-password toggle.
- Split layout desktop, stacked mobile. API errors role=alert with retry.

## 8. States (every page)
- Loading: layout-matching skeleton shimmer, never bare spinner. Empty: icon + copy + CTA.
- Error: message + Retry + support link. Run page: Queued-Running-Done stepper + bar, cancellable mock.

## 9. A11y + responsive (WCAG 2.2 AA)
- Contrast 4.5:1 body, 3:1 large/UI. Skip-to-content link. Logical focus order, no traps, Esc closes overlays.
- Touch targets 44px min. html[dir] flips on language switch. Keyboard: tabs/arrows/sort all reachable.
- Mobile-first 360px base. Sidebar to drawer. Tables scroll. Pricing sticky bottom CTA. Safe-area padding.

## 10. Rejected from MCP
- Viridis/plasma #440154/#FDE725 (heatmap, not fintech trust) -> slate+blue+emerald/red.
- OLED pure-black + neon glow (eye strain, AA failures) -> slate dark + flat accents.
- Exaggerated-minimal giant type -> compact data-dense scale. Nivo (heavier) -> Recharts.

## 11. Build tokens (Step 2)
- Tailwind extend colors {brand, gain, loss, warn}, fonts {sans:[Inter,IBM Plex Sans Arabic]}.
- CSS vars per section 2, .dark overrides, focus-visible 2px ring offset 2px.
- Motion tween 200-300ms easeInOut, prefers-reduced-motion disables lift/shimmer/count-up.

## 12. Binding rules (user-approved, 2026-10-16)
1. Gain/loss only via `<ValueDelta />`: sign + icon + token color, AA both themes.
2. Charts/components use tokens only (`src/lib/tokens.ts`, CSS vars, `src/lib/chartTheme.ts`); enforced by `scripts/check-colors.cjs`.
3. Time axes stay LTR in Arabic (`TimeSeriesBox` dir=ltr); numbers/tickers/dates LTR-isolated; surrounding UI flips.
