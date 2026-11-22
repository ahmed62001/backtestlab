# BacktestLab - Design Tokens Reference

Single source: `src/lib/tokens.ts` + CSS vars in `src/styles/globals.css`.
Charts read tokens via `src/lib/chartTheme.ts`. No hex/rgb anywhere else.

## Visual identity: Terminal Ink + Signal Gold (2026-11-13)

A near-black blue trading-terminal surface, a signal-blue primary, and a gold
accent reserved for the featured metal and live-data markers. Light mode is a
cool paper terminal (never generic SaaS gray). Prices use the `.fin` mono
stack (ui-monospace, tabular nums, always LTR-isolated). Layout: primary
navbar + secondary ticker-tape asset bar + market dashboard.

## Colors - light
bg #EEF1F6 / card #FFFFFF / text #0A1220 / muted #4B5A73 / primary #0E5FD7 / hover #0A4BA8 / ring #0E5FD7 / border #D7DFEC / input #A9B8D2 / gold #9A6B00 on #FBF0D3.

## Colors - dark
bg #070C16 / card #0E1930 / text #EAF0FA / muted #93A5C4 / primary #4C9AFF / hover #7AB6FF / ring #4C9AFF / border #1E2C48 / input #3A4E78 / gold #E3B341 on #453206.

## Gain / loss (Binding Rule 1)
gain text #007A5C on #E2F2EC (light), #2FD49A on #0B3D2C (dark).
loss text #C01F2E on #FBE7E9 (light), #FF6B6B on #4A1116 (dark).
Always render via `<ValueDelta />`: sign + icon + color, sr text for positive/negative.

## Warn
text #8A5E00 on #FBF0D3 (light), #E3B341 on #453206 (dark). Used for risk + overfitting banners and the "delayed / end-of-day" market-data honesty marker.

## Spacing / radii / shadows
page 1rem -> 1.5rem / card gap 1rem / radius cards 12px inputs 8px / sidebar 260px / container 1280px.
shadow card 0 1px 3px rgba(0,0,0,.08), hover 0 4px 12px rgba(0,0,0,.1).

## Typography
Arabic: IBM Plex Sans Arabic 400-700. Latin/numbers: Inter 400-700 + tnum.
Type scale: display clamp(1.875rem,4vw,2.25rem) / h1 clamp(1.5rem,3vw,1.875rem) / h2 1.25rem / body 1rem / small 0.875rem / caption 0.75rem / KPI 1.75rem.
Time-series + numbers/tickers/dates: dir=ltr + unicode-bidi isolate (Binding Rule 3).

## Backtest configuration form conventions (2026-11-12)

The `/app/new` wizard is the reference implementation for data-dense forms.
Source of truth: `src/pages/NewBacktest.tsx`; full change log:
`docs/UI_REDESIGN_PROGRESS.md`.

- **Structure:** three steps (strategy → configure → review). Step 2 is grouped
  into *Instrument → Data provider → Period & capital → Strategy parameters →
  Advanced*. Every group is a `Card` with an icon tile, an `h2`, and a short
  helper line (`SectionHeading` pattern).
- **Controls:** text/date use `Input`; numbers use `NumberField`
  (`src/components/ui/NumberField.tsx`). `NumberField` keeps raw keystrokes
  while focused and emits `number | undefined`, so clearing a field never
  silently becomes `0` and decimals can be typed. Labels, hints, and errors are
  rendered by the control.
- **Validation:** mirror backend rules (`src/lib/backtestDates.ts`, capital
  100…1,000,000, fees 0…5%, `paramSpecs` min/max). Errors appear under the
  field with `role="alert"`; a `role="status"` line explains why *Next* is
  disabled. Submission is blocked, user input is preserved, and backend errors
  are mapped through `src/lib/authErrors.ts` into a visible alert.
- **Providers:** radio cards grouped by provider category. Status precedence is
  *unavailable (with reason) → disabled → available*; key-required and
  timeframes are badges. Only `enabled && available` providers are selectable.
  Never imply a keyed/disabled provider works.
- **Unimplemented settings:** keep the control, place it under **Advanced**, and
  label it *Not applied yet* in both languages. Do not fake backend support.
- **Icons/motion:** lucide-react only (no glyph icons); `prefers-reduced-motion`
  is handled globally. Focus uses the global `--ring` outline; 44px minimum
  touch targets are retained.
- **RTL/numbers:** logical spacing utilities only (`ms-/me-/ps-/pe-/start/end`);
  numeric and ticker output is wrapped in `bdi dir="ltr"` with `.tnum`.
- **Tokens:** reuse the variables above; no component-local hex/rgb. The
  `check-colors` and `check-rtl` guards must stay green.

