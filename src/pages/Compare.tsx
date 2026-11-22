import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Card, ErrorState, Skeleton, TableShell, ValueDelta } from '../components/ui';
import { CompareEquityChart } from '../components/charts/CompareEquityChart';
import { apiGetBacktest } from '../api';
import type { BacktestResult } from '../types';

export function Compare() {
  const { t } = useTranslation();
  const [sp] = useSearchParams();
  const a = sp.get('a');
  const b = sp.get('b');
  const [ra, setRa] = useState<BacktestResult | null>(null);
  const [rb, setRb] = useState<BacktestResult | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!a || !b) return;
    setError(false);
    Promise.all([apiGetBacktest(a), apiGetBacktest(b)])
      .then(([x, y]) => {
        setRa(x);
        setRb(y);
      })
      .catch(() => setError(true));
  }, [a, b]);
  if (!a || !b || a === b) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('compare.title')}</h1>
        <Card>
          <p className="mb-3 text-sm text-mutedink">{t('results.selectTwo')}</p>
          <Link
            to="/app/history"
            className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
          >
            {t('compare.goHistory')}
          </Link>
        </Card>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('compare.title')}</h1>
        <ErrorState onRetry={() => window.location.reload()} />
      </div>
    );
  }
  if (!ra || !rb) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('compare.title')}</h1>
        <Skeleton className="h-64" />
      </div>
    );
  }
  const rows: { k: string; av: number; bv: number; suffix: string }[] = [
    { k: t('results.totalReturn'), av: ra.totalReturnPct, bv: rb.totalReturnPct, suffix: '%' },
    { k: t('results.maxDrawdown'), av: ra.maxDrawdownPct, bv: rb.maxDrawdownPct, suffix: '%' },
    { k: t('results.sharpe'), av: ra.sharpe, bv: rb.sharpe, suffix: '' },
    { k: t('results.winRate'), av: ra.winRatePct, bv: rb.winRatePct, suffix: '%' },
    { k: t('results.trades'), av: ra.trades, bv: rb.trades, suffix: '' },
    { k: t('results.vsBuyHold'), av: ra.vsBuyHoldPct, bv: rb.vsBuyHoldPct, suffix: '%' },
  ];
  const metaDiff = ra.asset !== rb.asset || ra.config.from !== rb.config.from || ra.config.to !== rb.config.to;
  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-2xl font-bold">{t('compare.title')}</h1>
      {metaDiff && (
        <p role="note" className="rounded-xl2 border border-warn/40 bg-warn-bg p-3 text-sm text-ink">
          {t('results.differentMeta')}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-1 text-sm font-semibold text-mutedink">{t('compare.a')}</h2>
          <p className="font-bold" dir="ltr">
            <bdi>
              {ra.asset} / {ra.templateId}
            </bdi>
          </p>
        </Card>
        <Card>
          <h2 className="mb-1 text-sm font-semibold text-mutedink">{t('compare.b')}</h2>
          <p className="font-bold" dir="ltr">
            <bdi>
              {rb.asset} / {rb.templateId}
            </bdi>
          </p>
        </Card>
        <Card>
          <h2 className="mb-1 text-sm font-semibold text-mutedink">{t('compare.diff')}</h2>
          <ValueDelta value={ra.totalReturnPct - rb.totalReturnPct} />
        </Card>
      </div>
      <Card>
        <TableShell label={t('compare.title')}>
          <table className="w-full min-w-[520px] border-collapse text-sm">
            <thead>
              <tr className="text-start text-[12px] uppercase text-mutedink">
                <th scope="col" className="p-2 text-start" />
                <th scope="col" className="p-2 text-start">
                  {t('compare.a')}
                </th>
                <th scope="col" className="p-2 text-start">
                  {t('compare.b')}
                </th>
                <th scope="col" className="p-2 text-start">
                  {t('compare.diff')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.k} className="border-t border-line">
                  <th scope="row" className="p-2 text-start font-medium">
                    {r.k}
                  </th>
                  <td className="p-2">
                    <ValueDelta value={r.av} suffix={r.suffix} />
                  </td>
                  <td className="p-2">
                    <ValueDelta value={r.bv} suffix={r.suffix} />
                  </td>
                  <td className="p-2">
                    <ValueDelta value={r.av - r.bv} suffix={r.suffix} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableShell>
      </Card>
      <Card>
        <h2 className="mb-2 text-base font-semibold">
          {t('compare.title')} — {t('results.equity')}
        </h2>
        {/* Full period, both persisted curves, union alignment, true gaps. */}
        <CompareEquityChart
          a={ra.equity}
          b={rb.equity}
          labelA={`${t('compare.a')} · ${ra.id}`}
          labelB={`${t('compare.b')} · ${rb.id}`}
        />
        <p className="mt-2 text-[12px] text-mutedink">
          <bdi>
            {ra.id}: {ra.equity.length} pts · {rb.id}: {rb.equity.length} pts
          </bdi>
        </p>
      </Card>
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('results.paramsTitle')}</h2>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-mutedink">{t('compare.a')}</dt>
            <dd className="tnum break-all" dir="ltr">
              <bdi>{JSON.stringify(ra.config.params)}</bdi>
            </dd>
          </div>
          <div>
            <dt className="text-mutedink">{t('compare.b')}</dt>
            <dd className="tnum break-all" dir="ltr">
              <bdi>{JSON.stringify(rb.config.params)}</bdi>
            </dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
