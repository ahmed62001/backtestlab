import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AreaSeries,
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
} from 'lightweight-charts';
import {
  getAreaSeriesOptions,
  getBenchmarkSeriesOptions,
  getDrawdownSeriesOptions,
  getChartTheme,
} from '../../lib/chartTheme';
import { formatDate, formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { equityToLineData, tradesToMarkers } from '../../lib/tradingviewAdapters';
import { usePrefs } from '../../stores/prefs';
import type { EquityPoint, Trade } from '../../types';
import { TradingViewChart } from './tradingview/TradingViewChart';

/** Time-series wrapper: axis stays LTR even on RTL pages (Binding Rule 3). */
/* rtl-ok: chart axes stay LTR by design inside an RTL page */
export function TimeSeriesBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title}>
      <div dir="ltr">{children}</div>
    </section>
  );
}

export function EquityChart({
  data,
  trades,
}: {
  data: EquityPoint[];
  trades?: Trade[];
}) {
  const { t, i18n } = useTranslation();
  const { theme } = usePrefs();
  const ct = useMemo(() => getChartTheme(theme), [theme]);
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;

  const [hoveredPoint, setHoveredPoint] = useState<{
    dateStr?: string;
    strategy?: number;
    benchmark?: number;
  } | null>(null);

  const strategyData = useMemo(() => equityToLineData(data, 'strategy'), [data]);
  const benchmarkData = useMemo(() => equityToLineData(data, 'benchmark'), [data]);
  const tradeMarkers = useMemo(() => tradesToMarkers(trades, ct.gain, ct.loss), [trades, ct.gain, ct.loss]);

  const summary = useMemo(() => {
    if (!data.length) return '';
    const first = data[0].strategy;
    const last = data[data.length - 1].strategy;
    return `${data.length} points, ${first} → ${last}`;
  }, [data]);

  const latest = data[data.length - 1];

  const handleInit = (chart: IChartApi) => {
    // 1. Strategy Equity Area Series
    const strategySeries = chart.addSeries(AreaSeries, {
      ...getAreaSeriesOptions(theme),
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });
    if (strategyData.length > 0) {
      strategySeries.setData(strategyData);
    }

    // 2. Benchmark Line Series (Dashed)
    const benchmarkSeries = chart.addSeries(LineSeries, {
      ...getBenchmarkSeriesOptions(theme),
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });
    if (benchmarkData.length > 0) {
      benchmarkSeries.setData(benchmarkData);
    }

    // 3. Trade Entry/Exit Markers
    if (tradeMarkers.length > 0) {
      createSeriesMarkers(strategySeries, tradeMarkers);
    }

    if (strategyData.length > 0) {
      chart.timeScale().fitContent();
    }

    // Interactive tooltip / legend tracking
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.point) {
        setHoveredPoint(null);
        return;
      }
      const strat = param.seriesData.get(strategySeries) as { value: number } | undefined;
      const bench = param.seriesData.get(benchmarkSeries) as { value: number } | undefined;

      const timeVal = param.time;
      let dateLabel = '';
      if (typeof timeVal === 'number') {
        dateLabel = formatDate(new Date(timeVal * 1000).toISOString(), lang);
      }

      setHoveredPoint({
        dateStr: dateLabel,
        strategy: strat?.value,
        benchmark: bench?.value,
      });
    });
  };

  return (
    <TimeSeriesBox title={t('results.equity')}>
      <div
        role="img"
        aria-label={`${t('results.equity')}. ${summary}`}
        className="relative h-64 w-full sm:h-80 rounded-lg border border-line bg-card overflow-hidden"
        data-testid="chart-results-equity"
        data-chart-state={data.length ? 'ready' : 'empty'}
        data-point-count={data.length}
        data-first-ts={data[0]?.date ?? ''}
        data-last-ts={data[data.length - 1]?.date ?? ''}
      >
        {/* Interactive hover legend */}
        <div
          dir="ltr"
          className="pointer-events-none absolute start-3 top-2.5 z-10 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-mono bg-card/85 px-2.5 py-1 rounded backdrop-blur-sm border border-line/50"
        >
          <span>{hoveredPoint?.dateStr || (latest ? formatDate(latest.date, lang) : '')}</span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-brand inline-block" />
            <span className="text-mutedink">{t('results.equity')}:</span>
            <strong className="text-ink">
              {formatNumber(hoveredPoint?.strategy ?? latest?.strategy ?? 0, lang, 2)}
            </strong>
          </span>
          {(hoveredPoint?.benchmark != null || latest?.benchmark != null) && (
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-slate-400 inline-block" />
              <span className="text-mutedink">Benchmark:</span>
              <strong className="text-mutedink">
                {formatNumber(hoveredPoint?.benchmark ?? latest?.benchmark ?? 0, lang, 2)}
              </strong>
            </span>
          )}
        </div>

        <TradingViewChart
          height={320}
          isIntraday={false}
          onInit={handleInit}
          testId="chart-results-equity-canvas"
        />
      </div>
      <p className="sr-only">{summary}</p>
    </TimeSeriesBox>
  );
}

export function DrawdownChart({ data }: { data: EquityPoint[] }) {
  const { t, i18n } = useTranslation();
  const { theme } = usePrefs();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;

  const [hoveredDd, setHoveredDd] = useState<{
    dateStr?: string;
    drawdown?: number;
  } | null>(null);

  const drawdownData = useMemo(() => equityToLineData(data, 'drawdown'), [data]);
  const latest = data[data.length - 1];

  const handleInit = (chart: IChartApi) => {
    const ddSeries = chart.addSeries(AreaSeries, {
      ...getDrawdownSeriesOptions(theme),
      priceFormat: {
        type: 'percent',
        precision: 2,
        minMove: 0.01,
      },
    });

    if (drawdownData.length > 0) {
      ddSeries.setData(drawdownData);
      chart.timeScale().fitContent();
    }

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.point) {
        setHoveredDd(null);
        return;
      }
      const dd = param.seriesData.get(ddSeries) as { value: number } | undefined;
      const timeVal = param.time;
      let dateLabel = '';
      if (typeof timeVal === 'number') {
        dateLabel = formatDate(new Date(timeVal * 1000).toISOString(), lang);
      }
      setHoveredDd({
        dateStr: dateLabel,
        drawdown: dd?.value,
      });
    });
  };

  return (
    <TimeSeriesBox title={t('results.drawdownTitle')}>
      <div
        role="img"
        aria-label={t('results.drawdownTitle')}
        className="relative h-44 w-full rounded-lg border border-line bg-card overflow-hidden"
      >
        <div
          dir="ltr"
          className="pointer-events-none absolute start-3 top-2 z-10 flex items-center gap-3 text-xs font-mono bg-card/85 px-2 py-0.5 rounded backdrop-blur-sm border border-line/50"
        >
          <span>{hoveredDd?.dateStr || (latest ? formatDate(latest.date, lang) : '')}</span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-danger inline-block" />
            <span className="text-mutedink">{t('results.drawdownTitle')}:</span>
            <strong className="text-loss">
              {formatNumber(hoveredDd?.drawdown ?? latest?.drawdown ?? 0, lang, 2)}%
            </strong>
          </span>
        </div>

        <TradingViewChart
          height={176}
          isIntraday={false}
          onInit={handleInit}
          testId="chart-results-drawdown-canvas"
        />
      </div>
    </TimeSeriesBox>
  );
}
