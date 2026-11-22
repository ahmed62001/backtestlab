import { useMemo, useState } from 'react';
import { LineSeries, LineStyle, type IChartApi } from 'lightweight-charts';
import { useTranslation } from 'react-i18next';
import { getChartTheme } from '../../lib/chartTheme';
import { formatDate, formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';
import { alignEquitySeries, type EquityPointLike } from '../../lib/chartData';
import { alignedToSeriesData } from '../../lib/tradingviewAdapters';
import { usePrefs } from '../../stores/prefs';
import { EmptyState } from '../ui';
import { TradingViewChart } from './tradingview/TradingViewChart';

/**
 * Full-period strategy comparison using TradingView Lightweight Charts.
 *
 * Both complete equity curves are aligned on the union of their timestamps and
 * plotted together. Where one run has no observation the value is a gap (WhitespaceData),
 * never forward-filled or interpolated.
 */
export function CompareEquityChart({
  a,
  b,
  labelA,
  labelB,
  testId = 'chart-compare-equity',
}: {
  a: readonly EquityPointLike[];
  b: readonly EquityPointLike[];
  labelA: string;
  labelB: string;
  testId?: string;
}) {
  const { t, i18n } = useTranslation();
  const { theme } = usePrefs();
  const ct = useMemo(() => getChartTheme(theme), [theme]);
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;

  const [hoveredData, setHoveredData] = useState<{
    dateStr?: string;
    valA?: number;
    valB?: number;
  } | null>(null);

  const aligned = useMemo(() => alignEquitySeries(a, b), [a, b]);

  const seriesDataA = useMemo(() => alignedToSeriesData(aligned.rows, 'a'), [aligned.rows]);
  const seriesDataB = useMemo(() => alignedToSeriesData(aligned.rows, 'b'), [aligned.rows]);

  const lastRow = aligned.rows[aligned.rows.length - 1];

  const handleInit = (chart: IChartApi) => {
    // 1. Series A (Solid Strategy Color)
    const seriesA = chart.addSeries(LineSeries, {
      color: ct.strategy,
      lineWidth: 2,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });
    if (seriesDataA.length > 0) {
      seriesA.setData(seriesDataA);
    }

    // 2. Series B (Dashed Benchmark Color)
    const seriesB = chart.addSeries(LineSeries, {
      color: ct.benchmark,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });
    if (seriesDataB.length > 0) {
      seriesB.setData(seriesDataB);
    }

    if (seriesDataA.length > 0 || seriesDataB.length > 0) {
      chart.timeScale().fitContent();
    }

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.point) {
        setHoveredData(null);
        return;
      }
      const dataA = param.seriesData.get(seriesA) as { value: number } | undefined;
      const dataB = param.seriesData.get(seriesB) as { value: number } | undefined;
      const timeVal = param.time;
      let dateLabel = '';
      if (typeof timeVal === 'number') {
        dateLabel = formatDate(new Date(timeVal * 1000).toISOString(), lang);
      }
      setHoveredData({
        dateStr: dateLabel,
        valA: dataA?.value,
        valB: dataB?.value,
      });
    });
  };

  if (aligned.rows.length === 0) {
    return (
      <div data-testid={testId} data-chart-state="empty">
        <EmptyState title={t('market.empty')} />
      </div>
    );
  }

  return (
    <div
      data-testid={testId}
      data-chart-state="ready"
      data-series-a-count={aligned.countA}
      data-series-b-count={aligned.countB}
      data-point-count={aligned.rows.length}
      data-first-ts={aligned.first ?? ''}
      data-last-ts={aligned.last ?? ''}
      className="relative"
    >
      <div className="relative h-[360px] w-full rounded-lg border border-line bg-card overflow-hidden">
        {/* Interactive Legend Overlay */}
        <div
          dir="ltr"
          className="pointer-events-none absolute start-3 top-2.5 z-10 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-mono bg-card/85 px-2.5 py-1 rounded backdrop-blur-sm border border-line/50"
        >
          <span>{hoveredData?.dateStr || (lastRow ? formatDate(lastRow.date, lang) : '')}</span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-brand inline-block" />
            <span className="text-mutedink">{labelA}:</span>
            <strong className="text-ink">
              {hoveredData?.valA != null
                ? formatNumber(hoveredData.valA, lang, 2)
                : lastRow?.a != null
                  ? formatNumber(lastRow.a, lang, 2)
                  : '—'}
            </strong>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-slate-400 inline-block" />
            <span className="text-mutedink">{labelB}:</span>
            <strong className="text-mutedink">
              {hoveredData?.valB != null
                ? formatNumber(hoveredData.valB, lang, 2)
                : lastRow?.b != null
                  ? formatNumber(lastRow.b, lang, 2)
                  : '—'}
            </strong>
          </span>
        </div>

        <TradingViewChart
          height={360}
          isIntraday={false}
          onInit={handleInit}
          testId={`${testId}-canvas`}
        />
      </div>
    </div>
  );
}
