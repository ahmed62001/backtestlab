import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { Badge, Button, Card, ErrorState, Modal, Skeleton, TableShell, Tabs, Tooltip, ValueDelta } from '../components/ui';
import { DrawdownChart, EquityChart } from '../components/charts/EquityChart';
import { MonthlyHeatmap } from '../components/charts/MonthlyHeatmap';
import { apiDeleteBacktest, apiGetBacktest, apiRunBacktest } from '../api';
import { prefillFromTemplate } from '../stores/draft';
import { mapApiError } from '../lib/authErrors';
import { downloadCsv, tradesToCsv } from '../lib/csv';
import { formatCurrency, formatDate, formatNumber, formatPercent } from '../lib/format';
import type { AppLang } from '../lib/format';
import type { BacktestResult } from '../types';

const PAGE = 10;

export function Results() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<BacktestResult | null>(null);
  const [error, setError] = useState(false);
  const [view, setView] = useState('chart');
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<'date' | 'pnl'>('date');
  const [del, setDel] = useState(false);
  const [delBusy, setDelBusy] = useState(false);
  const [delError, setDelError] = useState('');
  const [dupBusy, setDupBusy] = useState(false);
  const [dupError, setDupError] = useState('');
  const [msg, setMsg] = useState('');
  const dupInFlight = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => { abortRef.current?.abort(); }, []);
  const load = () => {
    if (!id) return;
    setError(false);
    apiGetBacktest(id)
      .then(setData)
      .catch(() => setError(true));
  };
  useEffect(load, [id]);

  // Deletion is only reported as successful after the backend confirms
  // `{ok:true}`. A failure keeps the current result on screen and lets the
  // user retry; the request is aborted if the page unmounts first.
  const confirmDelete = async () => {
    if (!data || delBusy) return;
    setDelBusy(true);
    setDelError('');
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await apiDeleteBacktest(data.id, ctrl.signal);
      if (res?.ok !== true) throw { code: 'request_failed' };
      setDel(false);
      navigate('/app/history');
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setDelError(mapApiError(e, t));
      setDelBusy(false);
    }
  };

  // Duplication re-submits the stored configuration through the normal
  // create endpoint: a new backtest with a new id/timestamps, no copied
  // result data or ownership fields, and the usual quota/validation rules.
  const duplicate = async () => {
    if (!data || dupInFlight.current) return;
    dupInFlight.current = true;
    setDupBusy(true);
    setDupError('');
    setMsg('');
    try {
      const created = await apiRunBacktest({ ...data.config });
      navigate(`/app/results/${created.id}`);
    } catch (e) {
      setDupError(mapApiError(e, t));
      setDupBusy(false);
      dupInFlight.current = false;
    }
  };

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('results.title')}</h1>
        <ErrorState onRetry={load} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('results.title')}</h1>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  const kpis: { label: string; explain: string; el: React.ReactNode }[] = [
    { label: t('results.totalReturn'), explain: t('results.explain.totalReturn'), el: <ValueDelta value={data.totalReturnPct} /> },
    { label: t('results.maxDrawdown'), explain: t('results.explain.maxDrawdown'), el: <ValueDelta value={data.maxDrawdownPct} /> },
    {
      label: t('results.sharpe'),
      explain: t('results.explain.sharpe'),
      el: (
        <span className="tnum font-bold" dir="ltr">
          <bdi>{formatNumber(data.sharpe, lang, 2)}</bdi>
        </span>
      ),
    },
    {
      label: t('results.winRate'),
      explain: t('results.explain.winRate'),
      el: (
        <span className="tnum font-bold" dir="ltr">
          <bdi>{formatPercent(data.winRatePct, lang, 1)}</bdi>
        </span>
      ),
    },
    {
      label: t('results.trades'),
      explain: t('results.explain.trades'),
      el: (
        <span className="tnum font-bold" dir="ltr">
          <bdi>{formatNumber(data.trades, lang, 0)}</bdi>
        </span>
      ),
    },
    { label: t('results.vsBuyHold'), explain: t('results.explain.vsBuyHold'), el: <ValueDelta value={data.vsBuyHoldPct} /> },
  ];
  const list = [...data.tradesList].sort((a, b) =>
    sort === 'pnl' ? (b.pnl ?? 0) - (a.pnl ?? 0) : +new Date(b.date) - +new Date(a.date),
  );
  const pages = Math.max(Math.ceil(list.length / PAGE), 1);
  const slice = list.slice(page * PAGE, page * PAGE + PAGE);
  const summaryText = [
    `${data.asset} / ${data.templateId}`,
    `${t('results.totalReturn')}: ${data.totalReturnPct}%`,
    `${t('results.maxDrawdown')}: ${data.maxDrawdownPct}%`,
    `Sharpe: ${data.sharpe}`,
    `${t('results.trades')}: ${data.trades}`,
    t('disclaimer.historical'),
  ].join('\n');
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t('results.title')}</h1>
        <Badge tone="neutral">
          <bdi dir="ltr">
            {data.asset} · {data.templateId}
          </bdi>
        </Badge>
      </div>
      {data.overfitting && (
        <p role="alert" className="flex items-start gap-2 rounded-xl2 border border-warn/40 bg-warn-bg p-3 text-sm text-ink">
          <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0 text-warn" />
          {t('results.overfitting')}
        </p>
      )}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        {kpis.map((k) => (
          <Card key={k.label}>
            <p className="mb-1 flex items-center gap-1 text-[13px] text-mutedink">
              {k.label} <Tooltip label={k.explain} />
            </p>
            <p className="text-xl font-bold">{k.el}</p>
          </Card>
        ))}
      </div>
      {(data.annualizedReturnPct !== undefined || data.profitFactor !== undefined) && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Card>
            <p className="text-[12px] text-mutedink">{t('results.cagr')}</p>
            <p className="mt-1 font-semibold tnum" dir="ltr">
              {data.annualizedReturnPct !== undefined ? `${data.annualizedReturnPct.toFixed(2)}%` : '—'}
            </p>
          </Card>
          <Card>
            <p className="text-[12px] text-mutedink">{t('results.volatility')}</p>
            <p className="mt-1 font-semibold tnum" dir="ltr">
              {data.volatilityPct !== undefined ? `${data.volatilityPct.toFixed(2)}%` : '—'}
            </p>
          </Card>
          <Card>
            <p className="text-[12px] text-mutedink">{t('results.sortino')}</p>
            <p className="mt-1 font-semibold tnum" dir="ltr">
              {data.sortino !== null && data.sortino !== undefined ? data.sortino.toFixed(2) : '—'}
            </p>
          </Card>
          <Card>
            <p className="text-[12px] text-mutedink">{t('results.profitFactor')}</p>
            <p className="mt-1 font-semibold tnum" dir="ltr">
              {data.profitFactor !== null && data.profitFactor !== undefined ? data.profitFactor.toFixed(2) : '—'}
            </p>
          </Card>
          <Card>
            <p className="text-[12px] text-mutedink">{t('results.expectancy')}</p>
            <p className="mt-1 font-semibold tnum" dir="ltr">
              {data.expectancy !== undefined ? data.expectancy.toFixed(2) : '—'}
            </p>
          </Card>
        </div>
      )}
      {data.validation && (
        <Card>
          <h2 className="mb-2 text-base font-semibold">
            {t('results.oosTitle')} ({data.validation.splitDate})
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-line p-3">
              <p className="text-xs font-medium text-mutedink">
                {t('results.inSample')} ({data.validation.inSampleBars} {t('results.bars')})
              </p>
              <p className="mt-1 text-sm tnum" dir="ltr">
                {t('results.return')}: {data.validation.inSample.totalReturnPct.toFixed(2)}% · Sharpe:{' '}
                {data.validation.inSample.sharpe.toFixed(2)} · {t('results.trades')}:{' '}
                {data.validation.inSample.trades}
              </p>
            </div>
            <div className="rounded-lg border border-line p-3">
              <p className="text-xs font-medium text-mutedink">
                {t('results.outOfSample')} ({data.validation.outOfSampleBars} {t('results.bars')})
              </p>
              <p className="mt-1 text-sm tnum" dir="ltr">
                {t('results.return')}: {data.validation.outOfSample.totalReturnPct.toFixed(2)}% · Sharpe:{' '}
                {data.validation.outOfSample.sharpe.toFixed(2)} · {t('results.trades')}:{' '}
                {data.validation.outOfSample.trades}
              </p>
            </div>
          </div>
        </Card>
      )}
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('results.equity')}</h2>
        <EquityChart data={data.equity} trades={data.tradesList} />
      </Card>
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('results.drawdownTitle')}</h2>
        <DrawdownChart data={data.equity} />
      </Card>
      <Card>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{t('results.monthly')}</h2>
          <Tabs
            tabs={[
              { id: 'chart', label: t('results.chartView') },
              { id: 'table', label: t('results.tableView') },
            ]}
            active={view}
            onChange={setView}
          />
        </div>
        {view === 'chart' ? (
          <MonthlyHeatmap cells={data.monthly} />
        ) : (
          <TableShell label={t('results.monthly')}>
            <table className="w-full min-w-[480px] border-collapse text-sm">
              <thead>
                <tr className="text-start text-[12px] uppercase text-mutedink">
                  <th scope="col" className="p-2 text-start">
                    year
                  </th>
                  <th scope="col" className="p-2 text-start">
                    month
                  </th>
                  <th scope="col" className="p-2 text-start">
                    %
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.monthly.map((c, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="tnum p-2" dir="ltr">
                      <bdi>{c.year}</bdi>
                    </td>
                    <td className="tnum p-2" dir="ltr">
                      <bdi>{c.month + 1}</bdi>
                    </td>
                    <td className="p-2">
                      <ValueDelta value={c.value} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        )}
      </Card>
      <Card>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{t('results.tradesTitle')}</h2>
          <span className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => setSort((s) => (s === 'date' ? 'pnl' : 'date'))}>
              {t('results.sortBy')}: {sort}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => downloadCsv(`trades-${data.id}.csv`, tradesToCsv(list))}>
              {t('results.exportCsv')}
            </Button>
          </span>
        </div>
        {list.length === 0 ? (
          <p className="text-sm text-mutedink">{t('results.noTrades')}</p>
        ) : (
          <>
            <TableShell label={t('results.tradesTitle')}>
              <table className="w-full min-w-[560px] border-collapse text-sm">
                <thead>
                  <tr className="text-start text-[12px] uppercase text-mutedink">
                    <th scope="col" className="p-2 text-start">
                      date
                    </th>
                    <th scope="col" className="p-2 text-start">
                      side
                    </th>
                    <th scope="col" className="p-2 text-start">
                      price
                    </th>
                    <th scope="col" className="p-2 text-start">
                      pnl
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {slice.map((tr) => (
                    <tr key={tr.id} className="border-t border-line">
                      <td className="tnum p-2" dir="ltr">
                        <bdi>{formatDate(tr.date, lang)}</bdi>
                      </td>
                      <td className="p-2">{tr.side}</td>
                      <td className="tnum p-2" dir="ltr">
                        <bdi>{formatCurrency(tr.price, lang, 'USD', 2)}</bdi>
                      </td>
                      <td className="p-2">
                        <ValueDelta value={tr.pnl} suffix="" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
            <p className="tnum mt-2 text-[13px] text-mutedink" dir="ltr">
              <bdi>
                {t('results.page')} {page + 1} {t('results.of')} {pages}
              </bdi>
            </p>
            <span className="mt-1 flex gap-2">
              <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage((p) => Math.max(p - 1, 0))}>
                ‹
              </Button>
              <Button size="sm" variant="secondary" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                ›
              </Button>
            </span>
          </>
        )}
      </Card>
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('results.provenanceTitle')}</h2>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-mutedink">{t('results.provenanceProvider')}</dt>
            <dd className="font-semibold" dir="ltr"><bdi>{data.provenance.provider}</bdi></dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('results.provenanceRetrieval')}</dt>
            <dd className="font-semibold" dir="ltr">
              <Badge tone={data.provenance.cache ? 'gain' : 'neutral'}>
                {data.provenance.cache ? t('results.retrievalStore') : t('results.retrievalLive')}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('results.provenanceDataHash')}</dt>
            <dd className="font-mono text-xs break-all" dir="ltr"><bdi>{data.provenance.dataHash}</bdi></dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('results.provenanceRows')}</dt>
            <dd className="tnum font-semibold" dir="ltr"><bdi>{data.provenance.rows}</bdi></dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('results.provenanceDateRange')}</dt>
            <dd className="tnum font-semibold" dir="ltr"><bdi>{data.provenance.start} → {data.provenance.end}</bdi></dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('results.provenanceWarnings')}</dt>
            <dd className="text-sm text-mutedink">
              {data.provenance.warnings && data.provenance.warnings.length > 0
                ? data.provenance.warnings.map((w: { code: string; message?: string }, i: number) => (
                    <div key={i} className="text-loss text-[12px]">{w.code}: {w.message}</div>
                  ))
                : t('results.noWarnings')}
            </dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('results.paramsTitle')}</h2>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-mutedink">{t('run.asset')}</dt>
            <dd className="font-semibold" dir="ltr">
              <bdi>{data.config.asset}</bdi>
            </dd>
          </div>
          <div>
            <dt className="text-mutedink">
              {t('run.from')} – {t('run.to')}
            </dt>
            <dd className="tnum font-semibold" dir="ltr">
              <bdi>
                {data.config.from} → {data.config.to}
              </bdi>
            </dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('run.params')}</dt>
            <dd className="tnum break-all" dir="ltr">
              <bdi>{JSON.stringify(data.config.params)}</bdi>
            </dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="mb-1 text-base font-semibold">{t('results.oosTitle')}</h2>
        <p className="text-sm text-mutedink">{t('run.oosHelp')}</p>
      </Card>
      <p role="note" className="rounded-xl2 border border-line bg-card p-3 text-[13px] text-mutedink">
        {t('disclaimer.historical')} {t('disclaimer.notAdvice')}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => {
            prefillFromTemplate(data.templateId, data.config.params);
            navigate(`/app/new?template=${data.templateId}`);
          }}
        >
          {t('results.rerun')}
        </Button>
        <Button variant="secondary" onClick={duplicate} loading={dupBusy} disabled={dupBusy}>
          {t('results.duplicate')}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(summaryText).catch(() => undefined);
            setMsg(t('results.copied'));
          }}
        >
          {t('results.copySummary')}
        </Button>
        <Button variant="destructive" onClick={() => setDel(true)}>
          {t('results.delete')}
        </Button>
      </div>
      {msg && (
        <p role="status" className="text-sm font-medium text-gain">
          {msg}
        </p>
      )}
      {dupError && (
        <p role="alert" className="rounded-xl2 border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
          {dupError}
        </p>
      )}
      <Modal open={del} onClose={() => setDel(false)} title={t('results.delete')}>
        <p className="mb-4 text-sm text-mutedink">{t('results.confirmDelete')}</p>
        {delError && (
          <p role="alert" className="mb-4 rounded-xl2 border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
            {delError}
          </p>
        )}
        <div className="flex gap-3">
          <Button variant="destructive" onClick={confirmDelete} loading={delBusy} disabled={delBusy}>
            {t('common.delete')}
          </Button>
          <Button variant="secondary" onClick={() => setDel(false)} disabled={delBusy}>
            {t('common.cancel')}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

