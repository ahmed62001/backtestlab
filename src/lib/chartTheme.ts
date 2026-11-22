import {
  ColorType,
  CrosshairMode,
  LineStyle,
  type ChartOptions,
  type DeepPartial,
} from 'lightweight-charts';
import { tokensFor, type ThemeName } from './tokens';

/** Shared chart theme (Binding Rule 2): every chart color comes from tokens.
 * Reads live CSS vars so charts react to light/dark switching. */

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export interface ChartTheme {
  mode: ThemeName;
  grid: string;
  axis: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  strategy: string;
  benchmark: string;
  drawdown: string;
  gain: string;
  loss: string;
  teal: string;
  violet: string;
  amber: string;
}

export function getChartTheme(mode: ThemeName): ChartTheme {
  const t = tokensFor(mode);
  const live = (v: string, fb: string) => cssVar(v, fb);
  return {
    mode,
    grid: live('--border', t.chartGrid),
    axis: live('--muted-text', t.chartAxis),
    tooltipBg: live('--card', t.chartTooltipBg),
    tooltipBorder: live('--border', t.chartTooltipBorder),
    tooltipText: live('--text', t.text),
    strategy: t.series.strategy,
    benchmark: t.series.benchmark,
    drawdown: t.series.drawdown,
    gain: t.series.gain,
    loss: t.series.drawdown,
    teal: t.series.teal,
    violet: t.series.violet,
    amber: t.series.amber,
  };
}

/** Heatmap cell: gain/loss bg tokens with AA-safe text. Never hardcode colors. */
export function heatCellStyle(mode: ThemeName, value: number | null): { background: string; color: string } {
  const t = tokensFor(mode);
  if (value === null || Number.isNaN(value)) {
    return { background: t.chartGrid, color: t.mutedText };
  }
  const intensity = Math.min(Math.abs(value) / 8, 1);
  const alpha = 0.12 + intensity * 0.5;
  const base = value >= 0 ? t.gain : t.loss;
  return { background: hexWithAlpha(base, alpha), color: value >= 0 ? t.gain : t.loss };
}

export function hexWithAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, '0');
  return `${hex}${a}`;
}

/**
 * TradingView Lightweight Charts options derived from application tokens.
 */
export function getTradingViewChartOptions(
  mode: ThemeName,
  options?: { isIntraday?: boolean; height?: number },
): DeepPartial<ChartOptions> {
  const ct = getChartTheme(mode);
  return {
    height: options?.height ?? 360,
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: ct.axis,
      fontSize: 11,
      fontFamily: 'Inter, system-ui, sans-serif',
    },
    grid: {
      vertLines: { color: ct.grid, visible: true },
      horzLines: { color: ct.grid, visible: true },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: ct.axis,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: ct.tooltipBg,
      },
      horzLine: {
        color: ct.axis,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: ct.tooltipBg,
      },
    },
    rightPriceScale: {
      borderColor: ct.grid,
      scaleMargins: {
        top: 0.1,
        bottom: 0.15,
      },
    },
    timeScale: {
      borderColor: ct.grid,
      timeVisible: Boolean(options?.isIntraday),
      secondsVisible: false,
    },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: true,
    },
    handleScale: {
      axisPressedMouseMove: true,
      mouseWheel: true,
      pinch: true,
    },
  };
}

export function getCandlestickSeriesOptions(mode: ThemeName) {
  const t = tokensFor(mode);
  return {
    upColor: t.gain,
    downColor: t.loss,
    borderVisible: false,
    wickUpColor: t.gain,
    wickDownColor: t.loss,
  };
}

export function getAreaSeriesOptions(mode: ThemeName, color?: string) {
  const t = tokensFor(mode);
  const primary = color ?? t.series.strategy;
  return {
    lineColor: primary,
    topColor: hexWithAlpha(primary, 0.28),
    bottomColor: hexWithAlpha(primary, 0.02),
    lineWidth: 2 as const,
  };
}

export function getDrawdownSeriesOptions(mode: ThemeName) {
  const t = tokensFor(mode);
  return {
    lineColor: t.series.drawdown,
    topColor: hexWithAlpha(t.series.drawdown, 0.02),
    bottomColor: hexWithAlpha(t.series.drawdown, 0.35),
    lineWidth: 2 as const,
  };
}

export function getBenchmarkSeriesOptions(mode: ThemeName) {
  const t = tokensFor(mode);
  return {
    color: t.series.benchmark,
    lineWidth: 2 as const,
    lineStyle: LineStyle.Dashed,
  };
}
