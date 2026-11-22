import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AreaSeries, type IChartApi } from 'lightweight-charts';
import { apiGetMacroSeries, type MacroSeriesResponse } from '../api/client';
import { Badge, Button, Card, Input } from '../components/ui';
import { TradingViewChart } from '../components/charts/tradingview/TradingViewChart';
import { macroToLineData } from '../lib/tradingviewAdapters';
import { getAreaSeriesOptions, getChartTheme } from '../lib/chartTheme';
import { formatDate, formatNumber, type AppLang } from '../lib/format';
import { usePrefs } from '../stores/prefs';

const CURATED_SERIES = [
  { id: 'FEDFUNDS', labelEn: 'Federal Funds Rate', labelAr: 'سعر الفائدة الفيدرالي' },
  { id: 'CPIAUCSL', labelEn: 'US CPI (Inflation)', labelAr: 'مؤشر أسعار المستهلك الأمريكي' },
  { id: 'UNRATE', labelEn: 'US Unemployment Rate', labelAr: 'معدل البطالة الأمريكي' },
  { id: 'DGS10', labelEn: '10Y Treasury Yield', labelAr: 'عائد سندات الخزانة 10 سنوات' },
  { id: 'T10Y2Y', labelEn: '10Y-2Y Yield Spread', labelAr: 'فارق عائد 10 سنوات - سنتان' },
  { id: 'GDP', labelEn: 'US Nominal GDP', labelAr: 'الناتج المحلي الإجمالي الأمريكي' },
];

export default function MacroExplorer() {
  const { t, i18n } = useTranslation();
  const isAr = i18n.language === 'ar';
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const { theme } = usePrefs();
  const ct = useMemo(() => getChartTheme(theme), [theme]);

  const [seriesInput, setSeriesInput] = useState('FEDFUNDS');
  const [activeId, setActiveId] = useState('FEDFUNDS');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [data, setData] = useState<MacroSeriesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [hoveredPoint, setHoveredPoint] = useState<{
    dateStr?: string;
    val?: number;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGetMacroSeries(activeId, start, end, 240)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: { messageKey?: string; code?: string }) => {
        if (!cancelled) {
          setData(null);
          setError(err?.messageKey ? t(err.messageKey) : t('macro.errorLoad'));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, start, end, t]);

  const validObs = useMemo(
    () => (data?.observations ?? []).filter((o) => o.value !== null && Number.isFinite(o.value)),
    [data],
  );
  const latest = validObs.length > 0 ? validObs[validObs.length - 1] : null;
  const first = validObs.length > 0 ? validObs[0] : null;

  const macroSeriesData = useMemo(() => macroToLineData(validObs), [validObs]);

  const handleInit = (chart: IChartApi) => {
    const series = chart.addSeries(AreaSeries, {
      ...getAreaSeriesOptions(theme, ct.teal),
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    if (macroSeriesData.length > 0) {
      series.setData(macroSeriesData);
      chart.timeScale().fitContent();
    }

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.point) {
        setHoveredPoint(null);
        return;
      }
      const pt = param.seriesData.get(series) as { value: number } | undefined;
      const timeVal = param.time;
      let dateLabel = '';
      if (typeof timeVal === 'number') {
        dateLabel = formatDate(new Date(timeVal * 1000).toISOString(), lang);
      }
      setHoveredPoint({
        dateStr: dateLabel,
        val: pt?.value,
      });
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink">
            {t('macro.title')}
          </h1>
          <p className="text-sm text-mutedink">{t('macro.subtitle')}</p>
        </div>
        <Badge tone="neutral">{t('macro.referenceOnly')}</Badge>
      </div>

      <Card className="p-4 space-y-4">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-4 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            const clean = seriesInput.trim().toUpperCase();
            if (clean) setActiveId(clean);
          }}
        >
          <Input
            label={t('macro.seriesId')}
            value={seriesInput}
            onChange={(e) => setSeriesInput(e.target.value)}
            placeholder="FEDFUNDS"
          />
          <Input
            label={t('macro.from')}
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <Input
            label={t('macro.to')}
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
          <Button type="submit" disabled={loading}>
            {t('macro.load')}
          </Button>
        </form>

        <div className="flex flex-wrap gap-2">
          {CURATED_SERIES.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setSeriesInput(s.id);
                setActiveId(s.id);
              }}
              className={`rounded-full px-3 py-1 text-xs font-medium border transition ${
                activeId === s.id
                  ? 'bg-brand text-white border-brand'
                  : 'border-line text-mutedink hover:bg-card hover:text-ink'
              }`}
            >
              {s.id} · {isAr ? s.labelAr : s.labelEn}
            </button>
          ))}
        </div>
      </Card>

      {error && (
        <div role="alert" className="rounded-xl2 border border-danger/40 bg-danger-bg p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {loading && (
        <Card className="p-8 text-center text-sm text-mutedink">{t('common.loading')}</Card>
      )}

      {!loading && !error && data && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <div className="text-xs text-mutedink">{t('macro.seriesName')}</div>
              <div className="mt-1 font-semibold text-ink">
                {data.title || data.series_id}
              </div>
              <div className="mt-1 text-xs text-mutedink">{data.series_id}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-mutedink">{t('macro.latestObservation')}</div>
              <div className="mt-1 text-xl font-bold text-gain">
                {latest ? `${latest.value}` : '—'}
              </div>
              <div className="mt-1 text-xs text-mutedink">
                {latest ? `${t('macro.period')}: ${latest.date}` : t('macro.noData')}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-mutedink">{t('macro.unitsFrequency')}</div>
              <div className="mt-1 font-semibold text-ink">
                {data.units || '—'}
              </div>
              <div className="mt-1 text-xs text-mutedink">{data.frequency || '—'}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-mutedink">{t('macro.observationRange')}</div>
              <div className="mt-1 font-semibold text-ink">
                {first && latest ? `${first.date} → ${latest.date}` : '—'}
              </div>
              <div className="mt-1 text-xs text-mutedink">
                {t('macro.source')}: {data.source || 'FRED'}
              </div>
            </Card>
          </div>

          <Card className="p-4">
            {validObs.length === 0 ? (
              <div className="py-12 text-center text-sm text-mutedink">{t('macro.noData')}</div>
            ) : (
              <div className="relative h-80 w-full rounded-lg border border-line bg-card overflow-hidden">
                {/* Interactive Legend Overlay */}
                <div
                  dir="ltr"
                  className="pointer-events-none absolute start-3 top-2.5 z-10 flex items-center gap-3 text-xs font-mono bg-card/85 px-2.5 py-1 rounded backdrop-blur-sm border border-line/50"
                >
                  <span>{hoveredPoint?.dateStr || (latest ? formatDate(latest.date, lang) : '')}</span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-gain inline-block" />
                    <span className="text-mutedink">{data.title || data.series_id}:</span>
                    <strong className="text-ink">
                      {hoveredPoint?.val != null
                        ? formatNumber(hoveredPoint.val, lang, 2)
                        : latest?.value != null
                          ? formatNumber(latest.value, lang, 2)
                          : '—'}
                    </strong>
                    {data.units && <span className="text-mutedink">({data.units})</span>}
                  </span>
                </div>

                <TradingViewChart
                  height={320}
                  isIntraday={false}
                  onInit={handleInit}
                  testId="chart-macro-canvas"
                />
              </div>
            )}
            <p className="mt-3 text-xs text-mutedink">
              {t('macro.releaseNote')}
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
