import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertCircle,
  CalendarRange,
  Check,
  Database,
  Info,
  LineChart,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Input,
  NumberField,
  RiskBanner,
  ShariahBadge,
  Skeleton,
} from '../components/ui';
import { apiGetAssets, apiGetDataProviders, apiGetTemplates, apiRunBacktest } from '../api';
import { apiCancelJob, apiGetJob } from '../api/client';
import { useDraft } from '../stores/draft';
import {
  formatCurrency,
  formatDate,
  formatNumber,
  type AppLang,
} from '../lib/format';
import { mapApiError } from '../lib/authErrors';
import {
  daysBetween,
  maxBacktestDate,
  MIN_BACKTEST_DATE,
  validateBacktestDates,
} from '../lib/backtestDates';
import type { Asset, BacktestInterval, DataProviderInfo, StrategyTemplate, TemplateId } from '../types';

const CATEGORY_ORDER = ['equities', 'crypto', 'fx', 'macro', 'local', 'synthetic', 'upload'];

/** Turn `fastPeriod` into `Fast period` when no translation is available. */
function humanize(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase());
}

function toFiniteNumber(value: number | string | undefined): number | undefined {
  if (value === undefined || value === '') return undefined;
  const next = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(next) ? next : undefined;
}

function SectionHeading({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div className="mb-4 flex items-start gap-3">
      <span
        aria-hidden
        className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {description && <p className="mt-1 text-[13px] text-mutedink">{description}</p>}
      </div>
    </div>
  );
}

function SummaryItem({
  label,
  children,
  className = '',
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-[13px] font-medium text-mutedink">{label}</dt>
      <dd className="mt-0.5 break-words font-semibold text-ink">{children}</dd>
    </div>
  );
}

export function NewBacktest() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const draft = useDraft((s) => s.config);
  const setDraft = useDraft((s) => s.set);
  const [templates, setTemplates] = useState<StrategyTemplate[] | null>(null);
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [providers, setProviders] = useState<DataProviderInfo[] | null>(null);
  const [error, setError] = useState(false);
  const [q, setQ] = useState('');
  const [job, setJob] = useState<'idle' | 'queued' | 'running' | 'done'>('idle');
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [jobError, setJobError] = useState('');
  const [jobErrorCode, setJobErrorCode] = useState('');
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const timers = useRef<number[]>([]);

  const load = () => {
    setError(false);
    Promise.all([apiGetTemplates(), apiGetAssets(), apiGetDataProviders()])
      .then(([tp, as, pr]) => {
        setTemplates(tp);
        setAssets(as);
        setProviders(pr.items);
        const selected = pr.items.find(
          (provider) => provider.id === draft.dataProvider && provider.enabled && provider.available,
        );
        const fallback =
          pr.items.find(
            (provider) =>
              provider.id === pr.default && provider.enabled && provider.available,
          ) ?? pr.items.find((provider) => provider.enabled && provider.available);
        if (!selected && fallback) setDraft({ dataProvider: fallback.id });
      })
      .catch(() => setError(true));
  };

  useEffect(() => {
    load();
    // The initial catalog resolves a missing/stale persisted provider once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const tpl = params.get('template') as TemplateId | null;
    if (tpl && templates?.some((x) => x.id === tpl)) {
      const spec = templates.find((x) => x.id === tpl)!;
      const merged: Record<string, number | string> = {};
      spec.paramSpecs.forEach((p) => {
        merged[p.key] = p.default;
      });
      setDraft({ templateId: tpl, params: merged, step: 1 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates]);

  useEffect(
    () => () => {
      timers.current.forEach((x) => window.clearTimeout(x));
    },
    [],
  );

  const step = draft.step ?? 0;
  const setStep = (n: number) => setDraft({ step: Math.min(Math.max(n, 0), 2) });
  const filtered = useMemo(
    () =>
      (assets ?? []).filter((a) =>
        (a.ticker + ' ' + t(a.nameKey) + ' ' + a.market).toLowerCase().includes(q.toLowerCase()),
      ),
    [assets, q, t],
  );
  const tplSpec = templates?.find((x) => x.id === draft.templateId);
  const maxDate = maxBacktestDate();

  const paramValues = useMemo(() => {
    const out: Record<string, number | undefined> = {};
    for (const p of tplSpec?.paramSpecs ?? []) {
      out[p.key] = toFiniteNumber(draft.params?.[p.key] ?? p.default);
    }
    return out;
  }, [tplSpec, draft.params]);

  const paramErrors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const p of tplSpec?.paramSpecs ?? []) {
      const value = paramValues[p.key];
      if (value === undefined) {
        out[p.key] = t('run.paramRequired');
        continue;
      }
      if (p.min !== undefined && value < p.min) {
        out[p.key] = t('run.paramRange', { min: p.min, max: p.max ?? p.min });
      } else if (p.max !== undefined && value > p.max) {
        out[p.key] = t('run.paramRange', { min: p.min ?? p.max, max: p.max });
      }
    }
    return out;
  }, [tplSpec, paramValues, t]);

  const dateErr = useMemo(() => {
    const key = validateBacktestDates(draft.from, draft.to);
    return key ? t(key) : '';
  }, [draft.from, draft.to, t]);

  const capErr =
    draft.initialCapital === undefined ||
    draft.initialCapital < 100 ||
    draft.initialCapital > 1000000
      ? t('run.badCapital')
      : '';
  const feeErr =
    draft.feePct === undefined || draft.feePct < 0 || draft.feePct > 5
      ? t('run.badFees')
      : '';
  const fromErr = !draft.from ? t('run.requiredField') : '';
  const toErr = !draft.to ? t('run.requiredField') : dateErr;
  const selectedProvider = providers?.find(
    (provider) =>
      provider.id === draft.dataProvider && provider.enabled && provider.available,
  );
  const selectedAsset = assets?.find((a) => a.ticker === draft.asset);
  const paramErrCount = Object.keys(paramErrors).length;
  const step2Valid =
    !!draft.templateId &&
    !dateErr &&
    !capErr &&
    !feeErr &&
    paramErrCount === 0 &&
    !!draft.asset &&
    !!selectedProvider;

  const providerGroups = useMemo(() => {
    const groups = new Map<string, DataProviderInfo[]>();
    for (const p of providers ?? []) {
      const category = p.category || 'equities';
      if (!groups.has(category)) groups.set(category, []);
      groups.get(category)!.push(p);
    }
    const known = CATEGORY_ORDER.filter((category) => groups.has(category));
    const extra = [...groups.keys()]
      .filter((category) => !CATEGORY_ORDER.includes(category))
      .sort();
    return [...known, ...extra].map((category) => ({
      category,
      items: groups.get(category)!,
    }));
  }, [providers]);

  if (error)
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('run.title')}</h1>
        <ErrorState onRetry={load} />
      </div>
    );
  if (!templates || !assets || !providers)
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('run.title')}</h1>
        <Skeleton className="h-12" />
        <div className="grid gap-4 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      </div>
    );

  const cancel = () => {
    timers.current.forEach((x) => window.clearTimeout(x));
    timers.current = [];
    if (activeJobId) {
      void apiCancelJob(activeJobId).catch(() => {});
      setActiveJobId(null);
      sessionStorage.removeItem('btlab_active_job');
    }
    setJob('idle');
    setProgress(0);
  };

  const pollJob = (jobId: string) => {
    setActiveJobId(jobId);
    sessionStorage.setItem('btlab_active_job', jobId);
    const tick = async () => {
      try {
        const st = await apiGetJob(jobId);
        if (st.status === 'done') {
          setActiveJobId(null);
          sessionStorage.removeItem('btlab_active_job');
          setJob('done');
          setProgress(100);
          timers.current.push(window.setTimeout(() => navigate(`/app/results/${st.backtestId}`), 300));
          return;
        }
        if (st.status === 'failed' || st.status === 'canceled') {
          setActiveJobId(null);
          sessionStorage.removeItem('btlab_active_job');
          setJob('idle');
          setProgress(0);
          if (st.status === 'failed') {
            setJobError(st.error || t('common.errorBody'));
          }
          return;
        }
        setJob(st.status === 'running' ? 'running' : 'queued');
        if (typeof st.progress === 'number' && st.progress > 0) {
          setProgress(st.progress);
        }
        timers.current.push(window.setTimeout(() => void tick(), 1000));
      } catch {
        setActiveJobId(null);
        sessionStorage.removeItem('btlab_active_job');
        setJob('idle');
        setProgress(0);
        setJobError(t('common.errorBody'));
      }
    };
    timers.current.push(window.setTimeout(() => void tick(), 800));
  };

  const run = async () => {
    if (!selectedProvider) return;
    setJobError('');
    setJobErrorCode('');
    setJob('queued');
    setProgress(0);
    try {
      const cfg = {
        templateId: draft.templateId!,
        asset: draft.asset!,
        from: draft.from!,
        to: draft.to!,
        interval: draft.interval ?? '1D',
        initialCapital: draft.initialCapital!,
        feePct: draft.feePct!,
        stopLoss: draft.stopLoss,
        takeProfit: draft.takeProfit,
        positionSizing: draft.positionSizing,
        validation: draft.validation,
        params: draft.params ?? {},
        dataProvider: selectedProvider.id,
      };
      const r = (await apiRunBacktest(cfg)) as unknown as {
        id?: string;
        jobId?: string;
        backtestId?: string;
        status?: string;
      };
      if (r.jobId && r.status !== 'done') {
        pollJob(r.jobId);
        return;
      }
      setJob('done');
      setProgress(100);
      const targetId = r.id ?? r.backtestId ?? '';
      timers.current.push(window.setTimeout(() => navigate(`/app/results/${targetId}`), 300));
    } catch (e) {
      const err = e as { code?: string; messageKey?: string; provider?: string };
      setJob('idle');
      setProgress(0);
      setJobError(err?.messageKey ? mapApiError(err, t) : t('common.errorBody'));
      setJobErrorCode(err?.code ?? '');
    }
  };

  const steps = [t('run.step1'), t('run.step2'), t('run.step3')];
  const jobLabel =
    job === 'queued' ? t('run.queued') : job === 'running' ? t('run.running') : t('run.done');
  const showLimitCta = jobErrorCode === 'limit' || jobErrorCode === 'limitReached';
  const paramHint = (key: string, min?: number, max?: number) => {
    const help = t(`run.paramHelp.${key}`, { defaultValue: '' });
    const range =
      min !== undefined && max !== undefined ? t('run.paramRange', { min, max }) : '';
    return [help, range].filter(Boolean).join(' ');
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">{t('run.title')}</h1>
        <p className="max-w-2xl text-sm text-mutedink">{t('run.subtitle')}</p>
      </div>

      <ol
        className="grid gap-1 rounded-xl2 border border-line bg-bg p-1 sm:grid-cols-3"
        aria-label={t('run.title')}
      >
        {steps.map((s, i) => {
          const isCurrent = i === step;
          const isDone = i < step;
          return (
            <li key={s} className="flex">
              <button
                type="button"
                onClick={() => i < step && setStep(i)}
                disabled={i > step}
                aria-current={isCurrent ? 'step' : undefined}
                className={`flex min-h-[44px] w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
                  isCurrent
                    ? 'bg-card text-ink shadow-sm'
                    : isDone
                      ? 'text-brand hover:bg-card'
                      : 'text-mutedink'
                }`}
              >
                <span
                  aria-hidden
                  className={`flex size-6 shrink-0 items-center justify-center rounded-full border text-[12px] ${
                    isCurrent
                      ? 'border-brand bg-brand text-white'
                      : isDone
                        ? 'border-gain/40 bg-gain-bg text-gain'
                        : 'border-line bg-card text-mutedink'
                  }`}
                >
                  {isDone ? <Check size={13} /> : i + 1}
                </span>
                <span className="truncate text-start">{s}</span>
              </button>
            </li>
          );
        })}
      </ol>

      {step === 0 && (
        <section aria-label={t('run.step1')} className="flex flex-col gap-4">
          <SectionHeading
            icon={<LineChart size={18} />}
            title={t('run.chooseStrategy')}
            description={t('run.strategyHelp')}
          />
          <div
            className="grid gap-4 sm:grid-cols-2"
            role="radiogroup"
            aria-label={t('run.template')}
          >
            {templates.map((tp) => {
              const selected = draft.templateId === tp.id;
              return (
                <button
                  key={tp.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => {
                    const merged: Record<string, number | string> = {};
                    tp.paramSpecs.forEach((p) => {
                      merged[p.key] = p.default;
                    });
                    setDraft({ templateId: tp.id, params: merged });
                  }}
                  className={`relative rounded-xl2 border p-4 text-start transition-colors ${
                    selected
                      ? 'border-brand bg-brand/5 shadow-sm'
                      : 'border-line bg-card hover:border-brand/40 hover:bg-bg'
                  }`}
                >
                  <span className="mb-1 flex items-center gap-2 pe-7 text-base font-semibold">
                    {t(`templates.${tp.id}.name`)}
                  </span>
                  <span className="block text-sm text-mutedink">
                    {t(`templates.${tp.id}.desc`)}
                  </span>
                  <span className="mt-3 flex flex-wrap gap-2">
                    <Badge tone="neutral">{t(`run.difficulty.${tp.difficulty}`)}</Badge>
                    <Badge
                      tone={
                        tp.riskLabel === 'lower'
                          ? 'gain'
                          : tp.riskLabel === 'higher'
                            ? 'loss'
                            : 'warn'
                      }
                    >
                      {t(`run.risk.${tp.riskLabel}`)}
                    </Badge>
                  </span>
                  {selected && (
                    <span
                      aria-hidden
                      className="absolute end-3 top-3 flex size-6 items-center justify-center rounded-full bg-brand text-white"
                    >
                      <Check size={14} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <Card className="opacity-70">
            <h2 className="mb-1 text-base font-semibold">{t('run.describeSoon')}</h2>
            <label htmlFor="nl-preview" className="sr-only">
              {t('run.describeSoon')}
            </label>
            <textarea
              id="nl-preview"
              disabled
              rows={2}
              placeholder={t('run.describeSoon')}
              className="w-full rounded-lg border border-line bg-bg p-3 text-sm text-mutedink"
            />
            <p className="mt-1 text-[13px] text-mutedink">{t('common.comingSoon')}</p>
          </Card>
          <div className="flex items-center gap-3">
            <Button disabled={!draft.templateId} onClick={() => setStep(1)}>
              {t('run.next')}
            </Button>
            <span className="text-[13px] text-mutedink" role="status">
              {draft.templateId
                ? t('run.stepCounter', { current: 1, total: 3 })
                : t('run.selectStrategyToContinue')}
            </span>
          </div>
        </section>
      )}

      {step === 1 && (
        <section aria-label={t('run.step2')} className="flex flex-col gap-4">
          <Card>
            <SectionHeading
              icon={<Search size={18} />}
              title={t('run.chooseAsset')}
              description={t('run.assetSectionHelp')}
            />
            <Input
              label={t('common.search')}
              id="asset-search"
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('run.searchAsset')}
            />
            <p className="mt-2 text-[12px] text-mutedink" role="status">
              {t('run.assetCount', { total: filtered.length })}
            </p>
            <ul
              className="mt-1 flex max-h-64 flex-col gap-1 overflow-y-auto rounded-lg border border-line bg-card p-1 pe-2"
              role="radiogroup"
              aria-label={t('run.asset')}
            >
              {filtered.map((a) => {
                const selected = draft.asset === a.ticker;
                return (
                  <li key={a.ticker}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setDraft({ asset: a.ticker })}
                      className={`flex min-h-[44px] w-full items-center gap-2 rounded-lg border px-3 py-2 text-start text-sm transition-colors ${
                        selected
                          ? 'border-brand/40 bg-brand/10 font-semibold text-brand'
                          : 'border-transparent hover:bg-bg'
                      }`}
                    >
                      <bdi dir="ltr" className="tnum font-bold">
                        {a.ticker}
                      </bdi>
                      <span className="min-w-0 flex-1 truncate text-mutedink">
                        {t(a.nameKey)} · {a.market}
                      </span>
                      {a.halalScreened && <ShariahBadge />}
                      {selected && <Check size={16} aria-hidden className="shrink-0" />}
                    </button>
                  </li>
                );
              })}
            </ul>
            {filtered.length === 0 && (
              <p className="mt-2 rounded-lg border border-dashed border-line bg-bg px-3 py-4 text-sm text-mutedink">
                {t('run.assetNoMatch', { query: q })}
              </p>
            )}
            {!draft.asset && (
              <p className="mt-2 text-[13px] text-mutedink">{t('run.noAsset')}</p>
            )}
          </Card>

          <Card>
            <SectionHeading
              icon={<Database size={18} />}
              title={t('dataProviders.title')}
              description={t('run.providerSectionHelp')}
            />
            {providerGroups.length === 0 ? (
              <p className="rounded-lg border border-dashed border-line bg-bg px-3 py-4 text-sm text-mutedink">
                {t('run.providersEmpty')}
              </p>
            ) : (
              <div className="space-y-5">
                {providerGroups.map(({ category, items }) => {
                  const categoryKey = `dataProviders.category${category.charAt(0).toUpperCase() + category.slice(1)}`;
                  return (
                    <div key={category} className="space-y-2">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-mutedink">
                        {t(categoryKey, { defaultValue: category })}
                      </h3>
                      <div className="grid gap-2 lg:grid-cols-2">
                        {items.map((p) => {
                          const selectable = p.enabled && p.available;
                          const selected = draft.dataProvider === p.id;
                          const description =
                            lang === 'ar'
                              ? p.descriptionAr || p.descriptionEn
                              : p.descriptionEn;
                          return (
                            // The whole card is the label text; the control is nested and the
                            // rule's depth heuristic cannot see the text spans.
                            // eslint-disable-next-line jsx-a11y/label-has-associated-control
                            <label
                              key={p.id}
                              htmlFor={`provider-${p.id}`}
                              className={`flex cursor-pointer flex-col gap-2 rounded-xl2 border p-3 transition-colors focus-within:ring-2 focus-within:ring-brand ${
                                selected
                                  ? 'border-brand bg-brand/5'
                                  : 'border-line bg-card'
                              } ${
                                selectable
                                  ? 'hover:border-brand/40 hover:bg-bg'
                                  : 'cursor-not-allowed opacity-70'
                              }`}
                            >
                              <input
                                id={`provider-${p.id}`}
                                type="radio"
                                name="dataProvider"
                                value={p.id}
                                checked={selected}
                                disabled={!selectable}
                                onChange={() => setDraft({ dataProvider: p.id })}
                                className="sr-only"
                              />
                              <span className="flex items-start gap-3">
                                <span className="min-w-0 flex-1">
                                  <span className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold text-ink">
                                      {lang === 'ar' ? p.nameAr : p.nameEn}
                                    </span>
                                    {p.requiresKey && (
                                      <Badge tone="warn">
                                        {t('dataProviders.badgeKeyRequired')}
                                      </Badge>
                                    )}
                                  </span>
                                  {description && (
                                    <span className="mt-1 line-clamp-2 block text-[13px] text-mutedink">
                                      {description}
                                    </span>
                                  )}
                                  <span className="mt-1 flex flex-wrap items-center gap-2 text-[12px]">
                                    {!p.available ? (
                                      <span className="inline-flex items-center gap-1 font-medium text-loss">
                                        <span aria-hidden>•</span>
                                        {t('dataProviders.badgeUnavailable', {
                                          reason: p.availableDetail || t('dataProviders.unavailable'),
                                        })}
                                      </span>
                                    ) : p.enabled ? (
                                      <span className="inline-flex items-center gap-1 font-medium text-gain">
                                        <Check size={13} aria-hidden />
                                        {t('dataProviders.available')}
                                      </span>
                                    ) : (
                                      <span className="inline-flex items-center gap-1 font-medium text-mutedink">
                                        {t('common.disabled')}
                                      </span>
                                    )}
                                    {p.available && p.category === 'local' && (
                                      <span className="text-mutedink">
                                        {t('dataProviders.badgeCached')}
                                      </span>
                                    )}
                                    {p.intervals.length > 0 && (
                                      <span className="ms-auto text-mutedink">
                                        {t('dataProviders.badgeTimeframes', {
                                          timeframes: p.intervals.join(', '),
                                        })}
                                      </span>
                                    )}
                                  </span>
                                </span>
                                <span
                                  aria-hidden
                                  className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border ${
                                    selected
                                      ? 'border-brand bg-brand'
                                      : 'border-[var(--input)] bg-card'
                                  }`}
                                >
                                  {selected && <span className="size-1.5 rounded-full bg-card" />}
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <p className="mt-3 text-[12px] text-mutedink">{t('dataProviders.choose')}</p>
          </Card>

          <Card>
            <SectionHeading
              icon={<CalendarRange size={18} />}
              title={t('run.periodSection')}
              description={t('run.periodSectionHelp')}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label={t('run.from')}
                id="run-from"
                type="date"
                dir="ltr"
                min={MIN_BACKTEST_DATE}
                max={maxDate}
                value={draft.from ?? ''}
                onChange={(e) => setDraft({ from: e.target.value })}
                error={fromErr || undefined}
              />
              <Input
                label={t('run.to')}
                id="run-to"
                type="date"
                dir="ltr"
                min={MIN_BACKTEST_DATE}
                max={maxDate}
                value={draft.to ?? ''}
                onChange={(e) => setDraft({ to: e.target.value })}
                error={toErr || undefined}
              />
              <NumberField
                label={t('run.capital')}
                id="run-cap"
                dir="ltr"
                min={100}
                max={1000000}
                step={100}
                value={draft.initialCapital}
                onValueChange={(value) => {
                  setTouched((s) => ({ ...s, capital: true }));
                  setDraft({ initialCapital: value });
                }}
                error={touched.capital ? capErr : ''}
                hint={t('run.capitalHint')}
              />
              <NumberField
                label={t('run.fees')}
                id="run-fee"
                dir="ltr"
                min={0}
                max={5}
                step={0.1}
                value={draft.feePct}
                onValueChange={(value) => {
                  setTouched((s) => ({ ...s, fee: true }));
                  setDraft({ feePct: value });
                }}
                error={touched.fee ? feeErr : ''}
                hint={t('run.feesHint')}
              />
            </div>
            <p className="mt-3 text-[13px] text-mutedink">
              {t('run.dateRangeHint', { min: MIN_BACKTEST_DATE, max: maxDate })}
            </p>
          </Card>

          <Card>
            <SectionHeading
              icon={<SlidersHorizontal size={18} />}
              title={t('run.riskControlsTitle')}
              description={t('run.riskControlsHelp')}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="run-interval"
                  className="mb-1 block text-xs font-medium text-mutedink"
                >
                  {t('run.interval')}
                </label>
                <select
                  id="run-interval"
                  value={draft.interval ?? '1D'}
                  onChange={(e) => setDraft({ interval: e.target.value as BacktestInterval })}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink"
                >
                  {(['1D', '1W', '1M', '1H', '4H', '30m', '15m', '5m', '1m'] as const).map(
                    (iv) => (
                      <option key={iv} value={iv}>
                        {iv}
                      </option>
                    ),
                  )}
                </select>
              </div>
              <div>
                <label
                  htmlFor="run-sizing-mode"
                  className="mb-1 block text-xs font-medium text-mutedink"
                >
                  {t('run.positionSizingMode')}
                </label>
                <select
                  id="run-sizing-mode"
                  value={draft.positionSizing?.mode ?? 'pct_equity'}
                  onChange={(e) => {
                    const mode = e.target.value as 'pct_equity' | 'fixed_amount' | 'risk_based';
                    setDraft({
                      positionSizing: {
                        mode,
                        value: mode === 'fixed_amount' ? 2500 : mode === 'risk_based' ? 1 : 100,
                        maxAllocationPct: draft.positionSizing?.maxAllocationPct ?? 100,
                      },
                      ...(mode === 'risk_based' && (!draft.stopLoss || draft.stopLoss.mode === 'none')
                        ? { stopLoss: { mode: 'risk_based', pct: 5 } }
                        : {}),
                    });
                  }}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink"
                >
                  <option value="pct_equity">{t('run.sizingPctEquity')}</option>
                  <option value="fixed_amount">{t('run.sizingFixedAmount')}</option>
                  <option value="risk_based">{t('run.sizingRiskBased')}</option>
                </select>
              </div>
              <NumberField
                label={
                  draft.positionSizing?.mode === 'fixed_amount'
                    ? t('run.sizingAmountLabel')
                    : draft.positionSizing?.mode === 'risk_based'
                      ? t('run.sizingRiskPctLabel')
                      : t('run.sizingEquityPctLabel')
                }
                id="run-sizing-val"
                dir="ltr"
                min={draft.positionSizing?.mode === 'risk_based' ? 0.1 : 1}
                max={draft.positionSizing?.mode === 'fixed_amount' ? 1000000 : draft.positionSizing?.mode === 'risk_based' ? 25 : 100}
                step={draft.positionSizing?.mode === 'fixed_amount' ? 100 : 1}
                value={draft.positionSizing?.value ?? 100}
                onValueChange={(value) =>
                  setDraft({
                    positionSizing: {
                      mode: draft.positionSizing?.mode ?? 'pct_equity',
                      value,
                      maxAllocationPct: draft.positionSizing?.maxAllocationPct ?? 100,
                    },
                  })
                }
              />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label
                    htmlFor="run-sl-mode"
                    className="mb-1 block text-xs font-medium text-mutedink"
                  >
                    {t('run.stopLoss')}
                  </label>
                  <select
                    id="run-sl-mode"
                    value={draft.stopLoss?.mode ?? 'none'}
                    onChange={(e) => {
                      const mode = e.target.value as 'none' | 'fixed_pct' | 'risk_based';
                      setDraft({
                        stopLoss: mode === 'none' ? { mode: 'none' } : { mode, pct: draft.stopLoss?.pct ?? 5 },
                      });
                    }}
                    className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink"
                  >
                    <option value="none">{t('run.disabled')}</option>
                    <option value="fixed_pct">{t('run.fixedPct')}</option>
                    <option value="risk_based">{t('run.riskBased')}</option>
                  </select>
                </div>
                {draft.stopLoss && draft.stopLoss.mode !== 'none' && (
                  <NumberField
                    label={t('run.stopLossPct')}
                    id="run-sl-pct"
                    dir="ltr"
                    min={0.5}
                    max={95}
                    step={0.5}
                    value={draft.stopLoss.pct ?? 5}
                    onValueChange={(pct) =>
                      setDraft({ stopLoss: { mode: draft.stopLoss!.mode, pct } })
                    }
                  />
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label
                    htmlFor="run-tp-mode"
                    className="mb-1 block text-xs font-medium text-mutedink"
                  >
                    {t('run.takeProfit')}
                  </label>
                  <select
                    id="run-tp-mode"
                    value={draft.takeProfit?.mode ?? 'none'}
                    onChange={(e) => {
                      const mode = e.target.value as 'none' | 'fixed_pct';
                      setDraft({
                        takeProfit: mode === 'none' ? { mode: 'none' } : { mode, pct: draft.takeProfit?.pct ?? 10 },
                      });
                    }}
                    className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink"
                  >
                    <option value="none">{t('run.disabled')}</option>
                    <option value="fixed_pct">{t('run.fixedPct')}</option>
                  </select>
                </div>
                {draft.takeProfit && draft.takeProfit.mode !== 'none' && (
                  <NumberField
                    label={t('run.takeProfitPct')}
                    id="run-tp-pct"
                    dir="ltr"
                    min={0.5}
                    max={1000}
                    step={0.5}
                    value={draft.takeProfit.pct ?? 10}
                    onValueChange={(pct) =>
                      setDraft({ takeProfit: { mode: 'fixed_pct', pct } })
                    }
                  />
                )}
              </div>
              <div className="flex items-center gap-3 pt-4">
                <input
                  id="run-oos-toggle"
                  type="checkbox"
                  checked={draft.validation?.mode === 'split'}
                  onChange={(e) =>
                    setDraft({
                      validation: e.target.checked
                        ? { mode: 'split', inSamplePct: 70 }
                        : { mode: 'none' },
                    })
                  }
                  className="h-4 w-4 rounded border-line"
                />
                <label htmlFor="run-oos-toggle" className="text-sm text-ink">
                  {t('run.oosValidationLabel')}
                </label>
              </div>
            </div>
          </Card>

          {tplSpec && tplSpec.paramSpecs.length > 0 && (
            <Card>
              <SectionHeading
                icon={<SlidersHorizontal size={18} />}
                title={t('run.parametersSection')}
                description={t('run.parametersSectionHelp')}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                {tplSpec.paramSpecs.map((p) => {
                  const label = t(`run.paramLabels.${p.key}`, {
                    defaultValue: humanize(p.key),
                  });
                  const help = t(`run.paramHelp.${p.key}`, { defaultValue: '' });
                  return (
                    <NumberField
                      key={p.key}
                      label={label}
                      id={`param-${p.key}`}
                      dir="ltr"
                      min={p.min}
                      max={p.max}
                      step={p.step ?? 1}
                      value={paramValues[p.key]}
                      onValueChange={(value) => {
                        setTouched((s) => ({ ...s, [`param:${p.key}`]: true }));
                        const next = { ...(draft.params ?? {}) };
                        if (value === undefined) {
                          next[p.key] = p.default;
                        } else {
                          next[p.key] = value;
                        }
                        setDraft({ params: next });
                      }}
                      error={touched[`param:${p.key}`] ? paramErrors[p.key] : ''}
                      hint={paramHint(p.key, p.min, p.max) || help || undefined}
                    />
                  );
                })}
              </div>
            </Card>
          )}

          <Card>
            <SectionHeading
              icon={<Info size={18} />}
              title={t('run.advancedSection')}
              description={t('run.advancedSectionHelp')}
            />
            <div className="rounded-xl2 border border-line bg-bg p-4">
              <div className="flex flex-wrap items-center gap-2">
                <label
                  htmlFor="oos"
                  className="flex cursor-pointer items-start gap-2 text-sm font-medium"
                >
                  <input
                    id="oos"
                    type="checkbox"
                    className="mt-1 size-5 accent-[var(--primary)]"
                    checked={(draft.oosPct ?? 0) > 0}
                    onChange={(e) => setDraft({ oosPct: e.target.checked ? 20 : 0 })}
                  />
                  <span>{t('run.oosTitle')}</span>
                </label>
                <Badge tone="neutral">{t('run.oosNotApplied')}</Badge>
              </div>
              <p className="mt-2 text-[13px] text-mutedink">{t('run.oosNotAppliedHelp')}</p>
              {(draft.oosPct ?? 0) > 0 && (
                <div className="mt-3 max-w-[12rem]">
                  <NumberField
                    label={t('run.oosPercent')}
                    id="oos-pct"
                    dir="ltr"
                    min={10}
                    max={40}
                    step={1}
                    value={draft.oosPct}
                    onValueChange={(value) => setDraft({ oosPct: value })}
                    hint={t('run.oosHelp')}
                  />
                </div>
              )}
            </div>
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={() => setStep(0)}>
              {t('run.back')}
            </Button>
            <Button disabled={!step2Valid} onClick={() => setStep(2)}>
              {t('run.next')}
            </Button>
            {!step2Valid && (
              <p className="text-[13px] text-mutedink" role="status" aria-live="polite">
                {!draft.asset
                  ? t('run.selectAssetToContinue')
                  : !selectedProvider
                    ? t('run.selectProviderToContinue')
                    : t('run.validationSummary')}
              </p>
            )}
          </div>
        </section>
      )}

      {step === 2 && (
        <section aria-label={t('run.step3')} className="flex flex-col gap-4">
          <Card>
            <SectionHeading
              icon={<Check size={18} />}
              title={t('run.review')}
              description={t('run.reviewHelp')}
            />
            <dl className="grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
              <SummaryItem label={t('run.template')}>
                {draft.templateId ? t(`templates.${draft.templateId}.name`) : t('run.notSet')}
              </SummaryItem>
              <SummaryItem label={t('run.asset')}>
                {draft.asset ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <bdi dir="ltr" className="tnum">
                      {draft.asset}
                    </bdi>
                    {selectedAsset && (
                      <span className="font-normal text-mutedink">{selectedAsset.market}</span>
                    )}
                    {selectedAsset?.halalScreened && <ShariahBadge />}
                  </span>
                ) : (
                  t('run.notSet')
                )}
              </SummaryItem>
              <SummaryItem label={t('dataProviders.title')}>
                {selectedProvider ? (
                  <span className="flex flex-wrap items-center gap-2">
                    {lang === 'ar' ? selectedProvider.nameAr : selectedProvider.nameEn}
                    {selectedProvider.requiresKey && (
                      <Badge tone="warn">{t('dataProviders.badgeKeyRequired')}</Badge>
                    )}
                  </span>
                ) : (
                  t('run.notSet')
                )}
              </SummaryItem>
              <SummaryItem label={`${t('run.from')} – ${t('run.to')}`}>
                {draft.from && draft.to ? (
                  <span className="flex flex-col gap-0.5">
                    <span className="tnum" dir="ltr">
                      <bdi>
                        {formatDate(draft.from, lang)} → {formatDate(draft.to, lang)}
                      </bdi>
                    </span>
                    <span className="text-[13px] font-normal text-mutedink">
                      {t('run.reviewDuration', {
                        days: formatNumber(daysBetween(draft.from, draft.to), lang, 0),
                      })}
                    </span>
                  </span>
                ) : (
                  t('run.notSet')
                )}
              </SummaryItem>
              <SummaryItem label={t('run.capital')}>
                <span className="tnum" dir="ltr">
                  <bdi>{formatCurrency(draft.initialCapital ?? 0, lang)}</bdi>
                </span>
              </SummaryItem>
              <SummaryItem label={t('run.fees')}>
                <span className="tnum" dir="ltr">
                  <bdi>{formatNumber(draft.feePct ?? 0, lang, 2)}%</bdi>
                </span>
              </SummaryItem>
              <SummaryItem label={t('run.params')} className="sm:col-span-2">
                {tplSpec && tplSpec.paramSpecs.length > 0 ? (
                  <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {tplSpec.paramSpecs.map((p) => (
                      <li key={p.key} className="flex items-baseline justify-between gap-3">
                        <span className="font-normal text-mutedink">
                          {t(`run.paramLabels.${p.key}`, { defaultValue: humanize(p.key) })}
                        </span>
                        <span className="tnum" dir="ltr">
                          <bdi>{paramValues[p.key] ?? '—'}</bdi>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="font-normal text-mutedink">{t('run.reviewNoParams')}</span>
                )}
              </SummaryItem>
              {(draft.oosPct ?? 0) > 0 && (
                <SummaryItem label={t('run.reviewAdvanced')} className="sm:col-span-2">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="tnum" dir="ltr">
                      <bdi>{draft.oosPct}%</bdi>
                    </span>
                    <Badge tone="neutral">{t('run.oosNotApplied')}</Badge>
                  </span>
                </SummaryItem>
              )}
            </dl>
          </Card>

          <RiskBanner />

          {job !== 'idle' && (
            <Card>
              <div aria-live="polite">
                <p className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold">
                  <span role="status">{jobLabel}</span>
                  <bdi dir="ltr" className="tnum text-mutedink">
                    {progress}%
                  </bdi>
                </p>
                <div
                  role="progressbar"
                  aria-label={jobLabel}
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="h-2.5 overflow-hidden rounded-full bg-bg"
                >
                  <div
                    className="h-full rounded-full bg-brand transition-[width] duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                {job !== 'done' && (
                  <p className="mt-2 text-[13px] text-mutedink">{t('run.runningHelp')}</p>
                )}
              </div>
              {job !== 'done' && (
                <div className="mt-3">
                  <Button variant="secondary" onClick={cancel}>
                    {t('run.cancelJob')}
                  </Button>
                </div>
              )}
            </Card>
          )}

          {jobError && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-xl2 border border-loss/30 bg-loss-bg p-4 text-sm text-loss"
            >
              <AlertCircle size={18} aria-hidden className="mt-0.5 shrink-0" />
              <div className="flex flex-col gap-1">
                <p className="font-semibold text-ink">{t('run.errorHeading')}</p>
                <p className="text-ink">
                  {jobError}{' '}
                  {showLimitCta && (
                    <Link to="/app/billing" className="font-semibold text-brand hover:underline">
                      {t('run.limitCta')}
                    </Link>
                  )}
                </p>
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={() => setStep(1)}>
              {t('run.back')}
            </Button>
            <Button
              onClick={run}
              loading={job !== 'idle'}
              disabled={job !== 'idle' || !selectedProvider || !step2Valid}
            >
              {t('run.runBtn')}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
