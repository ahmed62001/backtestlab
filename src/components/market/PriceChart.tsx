import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AreaSeries,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import {
  buildChartRows,
  isIntradayInterval,
  rowBoundary,
  type ChartRow,
} from '../../lib/chartData';
import {
  barsToCandlestickData,
  barsToLineData,
  barsToVolumeData,
  tradesToMarkers,
} from '../../lib/tradingviewAdapters';
import {
  getAreaSeriesOptions,
  getCandlestickSeriesOptions,
  getChartTheme,
} from '../../lib/chartTheme';
import { formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { ALL_TIMEFRAMES, daysForTimeframe, priceDecimals } from '../../lib/market';
import { usePrefs } from '../../stores/prefs';
import type { MarketBar } from '../../types';
import type { Trade } from '../../types/backtest';
import { EmptyState, ErrorState, Skeleton } from '../ui';
import { TradingViewChart } from '../charts/tradingview/TradingViewChart';

export type ChartType = 'line' | 'candles';

interface HoverLegendData {
  timeStr?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  changePct?: number;
}

export function PriceChart({
  bars,
  loading,
  error,
  onRetry,
  timeframe,
  onTimeframeChange,
  availableTimeframes,
  showTimeframes = true,
  symbol = '',
  assetClass,
  testId = 'chart-price',
  trades,
}: {
  bars: MarketBar[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  timeframe: string;
  onTimeframeChange: (tf: string) => void;
  availableTimeframes: string[];
  /** The public chart renders its own symbol/interval controls. */
  showTimeframes?: boolean;
  /** Symbol the chart is bound to (readiness contract). */
  symbol?: string;
  /** Optional asset class for precision formatting (e.g. 5 decimals for FX). */
  assetClass?: string;
  /** `data-testid` prefix for the readiness contract. */
  testId?: string;
  /** Optional trade markers for backtested asset visualizations. */
  trades?: Trade[];
}) {
  const { t, i18n } = useTranslation();
  const { theme } = usePrefs();
  const ct = useMemo(() => getChartTheme(theme), [theme]);
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const [chartType, setChartType] = useState<ChartType>('candles');
  const [hoverData, setHoverData] = useState<HoverLegendData | null>(null);

  // References to active TradingView series for zero-flicker live updates
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const areaSeriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const lastFitKeyRef = useRef<string>('');

  // Normalization via buildChartRows preserves single-source-of-truth readiness contract
  const { rows, received, rejected } = useMemo(
    () => buildChartRows(bars, timeframe, lang),
    [bars, timeframe, lang],
  );

  const chartState = loading ? 'loading' : error ? 'error' : rows.length === 0 ? 'empty' : 'ready';
  const firstTs = rowBoundary(rows, 'first');
  const lastTs = rowBoundary(rows, 'last');

  const tfs = ALL_TIMEFRAMES.filter((x) => availableTimeframes.includes(x.id));
  const tfButtons = (tfs.length ? tfs : [{ id: timeframe, days: daysForTimeframe(timeframe) }] as const).map(
    (x) => x.id,
  );

  const isIntraday = isIntradayInterval(timeframe);
  const samplePrice = rows.length ? rows[rows.length - 1].c : null;
  const decimals = useMemo(() => priceDecimals(symbol, assetClass, samplePrice), [symbol, assetClass, samplePrice]);
  const priceFormat = useMemo(
    () => ({ type: 'price' as const, precision: decimals, minMove: Math.pow(10, -decimals) }),
    [decimals],
  );

  // TradingView data series converted from normalized rows
  const candleData = useMemo(() => barsToCandlestickData(rows), [rows]);
  const lineData = useMemo(() => barsToLineData(rows), [rows]);
  const volumeData = useMemo(() => barsToVolumeData(rows, ct.gain, ct.loss), [rows, ct.gain, ct.loss]);
  const tradeMarkers = useMemo(() => tradesToMarkers(trades, ct.gain, ct.loss), [trades, ct.gain, ct.loss]);

  // Update series data smoothly whenever candleData, lineData or volumeData changes
  useEffect(() => {
    if (candleSeriesRef.current && candleData.length > 0) {
      candleSeriesRef.current.applyOptions({ priceFormat });
      candleSeriesRef.current.setData(candleData);
    }
    if (areaSeriesRef.current && lineData.length > 0) {
      areaSeriesRef.current.applyOptions({ priceFormat });
      areaSeriesRef.current.setData(lineData);
    }
    if (volumeSeriesRef.current && volumeData.length > 0) {
      volumeSeriesRef.current.setData(volumeData);
    }
    const fitKey = `${symbol}|${timeframe}`;
    if (chartInstanceRef.current && candleData.length > 0 && lastFitKeyRef.current !== fitKey) {
      chartInstanceRef.current.timeScale().fitContent();
      lastFitKeyRef.current = fitKey;
    }
  }, [candleData, lineData, volumeData, priceFormat, symbol, timeframe]);

  // Toggle series visibility when chartType changes
  useEffect(() => {
    if (candleSeriesRef.current) {
      candleSeriesRef.current.applyOptions({ visible: chartType === 'candles' });
    }
    if (areaSeriesRef.current) {
      areaSeriesRef.current.applyOptions({ visible: chartType === 'line' });
    }
  }, [chartType]);

  // Default display values from the latest candle when not hovered
  const latestRow: ChartRow | undefined = rows[rows.length - 1];
  const activeLegend = useMemo(() => {
    if (hoverData) return hoverData;
    if (!latestRow) return null;
    const changePct = latestRow.o > 0 ? ((latestRow.c - latestRow.o) / latestRow.o) * 100 : 0;
    return {
      timeStr: latestRow.label,
      open: latestRow.o,
      high: latestRow.h,
      low: latestRow.l,
      close: latestRow.c,
      volume: latestRow.v,
      changePct,
    };
  }, [hoverData, latestRow]);

  const handleChartInit = (chart: IChartApi) => {
    chartInstanceRef.current = chart;

    // 1. Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      ...getCandlestickSeriesOptions(theme),
      visible: chartType === 'candles',
      priceScaleId: 'right',
      priceFormat,
    });
    candleSeriesRef.current = candleSeries;
    if (candleData.length > 0) {
      candleSeries.setData(candleData);
    }

    // 2. Area series (line mode)
    const areaSeries = chart.addSeries(AreaSeries, {
      ...getAreaSeriesOptions(theme),
      visible: chartType === 'line',
      priceScaleId: 'right',
      priceFormat,
    });
    areaSeriesRef.current = areaSeries;
    if (lineData.length > 0) {
      areaSeries.setData(lineData);
    }

    // 3. Volume histogram on bottom 20%
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volumeSeriesRef.current = volumeSeries;
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    if (volumeData.length > 0) {
      volumeSeries.setData(volumeData);
    }

    // 4. Trade markers if present
    if (tradeMarkers.length > 0) {
      createSeriesMarkers(candleSeries, tradeMarkers);
      createSeriesMarkers(areaSeries, tradeMarkers);
    }

    // 5. Fit content
    if (candleData.length > 0) {
      chart.timeScale().fitContent();
    }

    // 6. Crosshair move listener for interactive legend
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.point) {
        setHoverData(null);
        return;
      }
      const candle = param.seriesData.get(candleSeries) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      const vol = param.seriesData.get(volumeSeries) as { value: number } | undefined;

      if (candle) {
        const changePct = candle.open > 0 ? ((candle.close - candle.open) / candle.open) * 100 : 0;
        setHoverData({
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
          volume: vol?.value,
          changePct,
        });
      }
    });

    return () => {
      candleSeriesRef.current = null;
      areaSeriesRef.current = null;
      volumeSeriesRef.current = null;
      chartInstanceRef.current = null;
    };
  };

  const handleFitContent = () => {
    if (chartInstanceRef.current) {
      chartInstanceRef.current.timeScale().fitContent();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('market.timeframe')}>
        {showTimeframes &&
          tfButtons.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onTimeframeChange(tf)}
              aria-pressed={timeframe === tf}
              className={`fin min-h-[36px] rounded-md px-2.5 text-[13px] font-semibold ${
                timeframe === tf ? 'bg-brand text-white' : 'bg-bg text-mutedink hover:text-ink'
              }`}
            >
              {tf}
            </button>
          ))}
        {showTimeframes && (
          <span className="mx-1 hidden h-6 w-px bg-line sm:block" aria-hidden />
        )}
        <div className="ms-auto flex items-center gap-1" role="group" aria-label={t('market.chartType')}>
          {(['line', 'candles'] as ChartType[]).map((cty) => (
            <button
              key={cty}
              type="button"
              onClick={() => setChartType(cty)}
              aria-pressed={chartType === cty}
              className={`min-h-[36px] rounded-md px-3 text-[13px] font-semibold ${
                chartType === cty ? 'bg-brand text-white' : 'bg-bg text-mutedink hover:text-ink'
              }`}
            >
              {t(`market.chart.${cty}`)}
            </button>
          ))}
          <button
            type="button"
            onClick={handleFitContent}
            title="Fit content"
            aria-label="Fit content"
            className="min-h-[36px] rounded-md px-2.5 text-[12px] font-medium bg-bg text-mutedink hover:text-ink"
          >
            Auto
          </button>
        </div>
      </div>

      <div
        data-testid={testId}
        data-chart-state={chartState}
        data-symbol={symbol}
        data-interval={timeframe}
        data-point-count={rows.length}
        data-received-count={received}
        data-rejected-count={rejected}
        data-first-ts={firstTs ?? ''}
        data-last-ts={lastTs ?? ''}
        data-first-value={rows.length ? rows[0].c : ''}
        data-last-value={rows.length ? rows[rows.length - 1].c : ''}
        className="relative"
      >
        {loading ? (
          <Skeleton className="h-[360px] w-full" />
        ) : error ? (
          <ErrorState onRetry={onRetry} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('market.empty')} />
        ) : (
          <div className="relative h-[360px] w-full rounded-lg border border-line bg-card overflow-hidden">
            {/* TradingView interactive OHLCV overlay legend */}
            {activeLegend && (
              <div
                dir="ltr"
                className="pointer-events-none absolute start-3 top-2.5 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-mono text-mutedink bg-card/85 px-2 py-1 rounded backdrop-blur-sm border border-line/50"
              >
                {activeLegend.timeStr && <span>{activeLegend.timeStr}</span>}
                {activeLegend.open != null && (
                  <span>
                    O: <strong className="text-ink">{formatNumber(activeLegend.open, lang, decimals)}</strong>
                  </span>
                )}
                {activeLegend.high != null && (
                  <span>
                    H: <strong className="text-ink">{formatNumber(activeLegend.high, lang, decimals)}</strong>
                  </span>
                )}
                {activeLegend.low != null && (
                  <span>
                    L: <strong className="text-ink">{formatNumber(activeLegend.low, lang, decimals)}</strong>
                  </span>
                )}
                {activeLegend.close != null && (
                  <span>
                    C:{' '}
                    <strong
                      className={
                        activeLegend.changePct != null && activeLegend.changePct >= 0
                          ? 'text-gain'
                          : 'text-loss'
                      }
                    >
                      {formatNumber(activeLegend.close, lang, decimals)}
                    </strong>
                  </span>
                )}
                {activeLegend.changePct != null && (
                  <span
                    className={
                      activeLegend.changePct >= 0 ? 'text-gain font-semibold' : 'text-loss font-semibold'
                    }
                  >
                    ({activeLegend.changePct >= 0 ? '+' : ''}
                    {activeLegend.changePct.toFixed(2)}%)
                  </span>
                )}
                {activeLegend.volume != null && activeLegend.volume > 0 && (
                  <span>
                    Vol: <strong className="text-ink">{formatNumber(activeLegend.volume, lang, 0)}</strong>
                  </span>
                )}
              </div>
            )}

            <TradingViewChart
              height={360}
              isIntraday={isIntraday}
              onInit={handleChartInit}
              testId={`${testId}-canvas`}
            />
          </div>
        )}
      </div>
    </div>
  );
}
