import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type DeepPartial, type ChartOptions } from 'lightweight-charts';
import { usePrefs } from '../../../stores/prefs';
import { getTradingViewChartOptions } from '../../../lib/chartTheme';

export interface TradingViewChartProps {
  height?: number;
  isIntraday?: boolean;
  options?: DeepPartial<ChartOptions>;
  onInit: (chart: IChartApi) => (() => void) | void;
  className?: string;
  testId?: string;
}

/**
 * Reusable, lifecycle-safe React wrapper around TradingView Lightweight Charts.
 * - Handles auto-resizing via ResizeObserver
 * - Automatically updates theme when user toggles light/dark mode
 * - Clean unmount, removing chart instance and event listeners
 * - Ensures LTR time-scale alignment
 */
export function TradingViewChart({
  height = 360,
  isIntraday = false,
  options: customOptions,
  onInit,
  className = '',
  testId,
}: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const cleanupRef = useRef<(() => void) | void>(undefined);
  const { theme } = usePrefs();

  // Create chart instance once on mount
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const baseOptions = getTradingViewChartOptions(theme, { isIntraday, height });
    const mergedOptions: DeepPartial<ChartOptions> = {
      ...baseOptions,
      ...customOptions,
      width: container.clientWidth || 600,
      height,
    };

    const chart = createChart(container, mergedOptions);
    chartRef.current = chart;

    // Run user initialization (attaching series, data, subscriptions)
    cleanupRef.current = onInit(chart);

    // Responsive resize handler
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries.length || !chartRef.current) return;
      const { width } = entries[0].contentRect;
      if (width > 0) {
        chartRef.current.applyOptions({ width });
      }
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      if (typeof cleanupRef.current === 'function') {
        cleanupRef.current();
        cleanupRef.current = undefined;
      }
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
    // Recreate only if isIntraday or height changes; theme is handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isIntraday, height]);

  // Update chart theme on the fly without destroying chart or series
  useEffect(() => {
    if (!chartRef.current) return;
    const themeOpts = getTradingViewChartOptions(theme, { isIntraday, height });
    chartRef.current.applyOptions(themeOpts);
  }, [theme, isIntraday, height]);

  return (
    /* rtl-ok: TradingView canvas axes stay LTR by design inside an RTL page */
    <div
      ref={containerRef}
      dir="ltr"
      data-testid={testId}
      className={`relative w-full overflow-hidden ${className}`}
      style={{ height }}
    />
  );
}
