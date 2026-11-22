import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Button, Card, EmptyState, ErrorState, Input, Modal, Select, Skeleton, TableShell, ValueDelta } from '../components/ui';
import { apiDeleteBacktest, apiListBacktests } from '../api';
import { mapApiError } from '../lib/authErrors';
import type { BacktestSummary } from '../types';
import { formatDate } from '../lib/format';
import type { AppLang } from '../lib/format';

const PAGE = 10;

export function History() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const navigate = useNavigate();
  const [items, setItems] = useState<BacktestSummary[] | null>(null);
  const [error, setError] = useState(false);
  const [q, setQ] = useState('');
  const [tpl, setTpl] = useState('all');
  const [sort, setSort] = useState('date');
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState<string[]>([]);
  const [del, setDel] = useState<BacktestSummary | null>(null);
  const [delBusy, setDelBusy] = useState(false);
  const [delError, setDelError] = useState('');
  const load = () => { setError(false); apiListBacktests().then(setItems).catch(() => setError(true)); };
  useEffect(load, []);
  const rows = useMemo(() => {
    let r = (items ?? []).filter((x) => (x.asset + ' ' + x.name).toLowerCase().includes(q.toLowerCase()));
    if (tpl !== 'all') r = r.filter((x) => x.templateId === tpl);
    if (sort === 'ret') r = [...r].sort((a, b) => b.totalReturnPct - a.totalReturnPct);
    else if (sort === 'dd') r = [...r].sort((a, b) => b.maxDrawdownPct - a.maxDrawdownPct);
    else r = [...r].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt));
    return r;
  }, [items, q, tpl, sort]);
  const pages = Math.max(Math.ceil(rows.length / PAGE), 1);
  const view = rows.slice(page * PAGE, page * PAGE + PAGE);
  // Keep the page index valid after a deletion or filter change empties it.
  useEffect(() => {
    if (page >= pages) setPage(pages - 1);
  }, [page, pages]);
  // The row is removed from local state only after the backend confirms
  // `{ok:true}`. On failure the row stays and the error is shown in the modal.
  const confirmDelete = async () => {
    if (!del || delBusy) return;
    setDelBusy(true);
    setDelError('');
    try {
      const res = await apiDeleteBacktest(del.id);
      if (res?.ok !== true) throw { code: 'request_failed' };
      setItems((xs) => (xs ?? []).filter((x) => x.id !== del.id));
      setSel((s) => s.filter((x) => x !== del.id));
      setDel(null);
    } catch (e) {
      setDelError(mapApiError(e, t));
    } finally {
      setDelBusy(false);
    }
  };
  if (error) return <div className="flex flex-col gap-4"><h1 className="text-2xl font-bold">{t('history.title')}</h1><ErrorState onRetry={load} /></div>;
  if (!items) return <div className="flex flex-col gap-4"><h1 className="text-2xl font-bold">{t('history.title')}</h1><Skeleton className="h-12" /><Skeleton className="h-64" /></div>;
  const toggleSel = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 2 ? [s[1], id] : [...s, id]));
  return (
    <div className="flex flex-col gap-5">
      <div className="bento-card flex flex-wrap items-center justify-between gap-3 rounded-xl2 border border-line/80 px-5 py-4">
        <h1 className="text-2xl font-extrabold tracking-tight">{t('history.title')}</h1>
        <Link to="/app/new" className="brand-gradient inline-flex min-h-[42px] items-center rounded-xl px-5 py-2 text-sm font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 transition-all">{t('history.newCta')}</Link>
      </div>
      <Card>
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label={t('common.search')} id="hist-q" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder={t('history.searchPh')} />
          <Select label={t('results.filterTemplate')} id="hist-tpl" value={tpl} onChange={(e) => { setTpl(e.target.value); setPage(0); }} options={[{ value: 'all', label: t('results.all') }, { value: 'ma-crossover', label: 'MA' }, { value: 'rsi', label: 'RSI' }, { value: 'breakout', label: 'Breakout' }, { value: 'mean-reversion', label: 'MR' }, { value: 'buy-hold', label: 'BH' }]} />
          <Select label={t('results.sortBy')} id="hist-sort" value={sort} onChange={(e) => setSort(e.target.value)} options={[{ value: 'date', label: t('common.save') }, { value: 'ret', label: t('results.totalReturn') }, { value: 'dd', label: t('results.maxDrawdown') }]} />
        </div>
      </Card>
      {sel.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl2 border border-brand/40 bg-brand/5 p-3">
          <span className="tnum text-sm font-semibold" dir="ltr"><bdi>{sel.length} / 2</bdi></span>
          <span className="text-sm text-mutedink">{t('results.selectTwo')}</span>
          <Button size="sm" disabled={sel.length !== 2} onClick={() => navigate(`/app/compare?a=${sel[0]}&b=${sel[1]}`)}>{t('results.compareCta')}</Button>
        </div>
      )}
      {rows.length === 0 ? (
        <EmptyState title={t('history.empty')} action={<Link to="/app/new" className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover">{t('history.newCta')}</Link>} />
      ) : (<>
        <div className="hidden md:block">
          <TableShell label={t('history.title')}>
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead><tr className="bg-bg text-start text-[12px] uppercase text-mutedink">
              <th scope="col" className="p-3 text-start"><span className="sr-only">select</span></th>
              <th scope="col" className="p-3 text-start">{t('run.asset')}</th>
              <th scope="col" className="p-3 text-start">{t('run.template')}</th>
              <th scope="col" className="p-3 text-start">{t('results.totalReturn')}</th>
              <th scope="col" className="p-3 text-start">{t('results.trades')}</th>
              <th scope="col" className="p-3 text-start">date</th>
              <th scope="col" className="p-3 text-start">{t('results.actions')}</th>
            </tr></thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.id} className="border-t border-line hover:bg-bg">
                  <td className="p-3"><input type="checkbox" aria-label={r.id} checked={sel.includes(r.id)} onChange={() => toggleSel(r.id)} className="size-5 accent-[var(--primary)]" /></td>
                  <td className="p-3 font-semibold" dir="ltr"><bdi>{r.asset}</bdi></td>
                  <td className="p-3 text-mutedink">{t(`templates.${r.templateId}.name`)}</td>
                  <td className="p-3"><ValueDelta value={r.totalReturnPct} /></td>
                  <td className="tnum p-3" dir="ltr"><bdi>{r.trades}</bdi></td>
                  <td className="tnum p-3" dir="ltr"><bdi>{formatDate(r.createdAt, lang)}</bdi></td>
                  <td className="p-3"><span className="flex gap-2"><Link to={`/app/results/${r.id}`} className="font-semibold text-brand hover:underline">{t('dashboard.viewResults')}</Link><button type="button" onClick={() => setDel(r)} disabled={delBusy} aria-busy={delBusy} className="font-semibold text-loss hover:underline disabled:cursor-not-allowed disabled:opacity-50">{t('results.delete')}</button></span></td>
                </tr>
              ))}
            </tbody>
          </table>
          </TableShell>
        </div>
        <div className="grid gap-3 md:hidden">
          {view.map((r) => (
            <Card key={r.id}>
              <div className="flex items-center justify-between gap-2">
                <p className="font-bold" dir="ltr"><bdi>{r.asset}</bdi></p>
                <ValueDelta value={r.totalReturnPct} />
              </div>
              <p className="text-sm text-mutedink">{t(`templates.${r.templateId}.name`)} · <bdi dir="ltr" className="tnum">{formatDate(r.createdAt, lang)}</bdi></p>
              <div className="mt-2 flex items-center gap-3">
                <input type="checkbox" aria-label={r.id} checked={sel.includes(r.id)} onChange={() => toggleSel(r.id)} className="size-5 accent-[var(--primary)]" />
                <Link to={`/app/results/${r.id}`} className="text-sm font-semibold text-brand hover:underline">{t('dashboard.viewResults')}</Link>
                <button type="button" onClick={() => setDel(r)} disabled={delBusy} aria-busy={delBusy} className="text-sm font-semibold text-loss hover:underline disabled:cursor-not-allowed disabled:opacity-50">{t('results.delete')}</button>
              </div>
            </Card>
          ))}
        </div>
        <div className="flex items-center justify-between text-sm text-mutedink">
          <span className="tnum" dir="ltr"><bdi>{t('results.page')} {page + 1} {t('results.of')} {pages}</bdi></span>
          <span className="flex gap-2">
            <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage((p) => Math.max(p - 1, 0))}>‹</Button>
            <Button size="sm" variant="secondary" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>›</Button>
          </span>
        </div>
      </>)}
      <Modal open={!!del} onClose={() => setDel(null)} title={t('results.delete')}>
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
          <Button variant="secondary" onClick={() => setDel(null)} disabled={delBusy}>
            {t('common.cancel')}
          </Button>
        </div>
      </Modal>
      {sel.length === 2 && <Badge tone="brand"><bdi dir="ltr" className="tnum">{sel[0]} vs {sel[1]}</bdi></Badge>}
    </div>
  );
}
