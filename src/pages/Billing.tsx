import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, ErrorState, Skeleton } from '../components/ui';
import { apiGetInvoices, apiGetPlans, apiGetUsage } from '../api';
import { useAuth } from '../stores/auth';
import { formatCurrency, formatDate } from '../lib/format';
import type { AppLang } from '../lib/format';
import type { Invoice, Plan, Usage } from '../types';

export function Billing() {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const plan = useAuth((s) => s.user?.plan) ?? 'free';
  const [usage, setUsage] = useState<Usage | null>(null);
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState(false);
  const [msg, setMsg] = useState('');
  const load = () => {
    setError(false);
    Promise.all([apiGetUsage(), apiGetPlans(), apiGetInvoices()])
      .then(([u, p, inv]) => {
        setUsage(u);
        setPlans(p);
        setInvoices(inv);
      })
      .catch(() => setError(true));
  };
  useEffect(load, []);
  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('billing.title')}</h1>
        <ErrorState onRetry={load} />
      </div>
    );
  }
  if (!usage || !plans || !invoices) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold">{t('billing.title')}</h1>
        <Skeleton className="h-28" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  const pro = plans.find((p) => p.id === 'pro');
  const checkoutAvailable = pro?.available !== false;
  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-2xl font-bold">{t('billing.title')}</h1>
      {msg && (
        <p role="status" className="rounded-xl2 border border-gain/30 bg-gain-bg p-3 text-sm font-medium text-gain">
          {msg}
        </p>
      )}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">{t('billing.current')}</h2>
            <p className="mt-1 flex items-center gap-2">
              <Badge tone={plan === 'pro' ? 'brand' : 'neutral'}>{plan === 'pro' ? t('billing.planPro') : t('billing.planFree')}</Badge>
              <span className="tnum text-sm text-mutedink" dir="ltr">
                <bdi>
                  {usage.usedToday} / {usage.dailyLimit}
                </bdi>
              </span>
            </p>
          </div>
          <span className="flex gap-2">
            {plan === 'pro' ? (
              <Button variant="secondary" onClick={() => setMsg(t('billing.cancelMock'))}>
                {t('billing.downgrade')}
              </Button>
            ) : (
              <Button
                disabled={!checkoutAvailable}
                aria-disabled={!checkoutAvailable}
                title={!checkoutAvailable ? t('billing.notConfigured') : undefined}
                onClick={() => {
                  if (!checkoutAvailable) {
                    setMsg(t('billing.notConfigured'));
                    return;
                  }
                  setMsg(
                    `Pro · ${formatCurrency(pro?.monthlyPrice ?? 19, lang, 'USD', 0)} (${t('pricing.mockNote')})`,
                  );
                }}
              >
                {t('billing.upgrade')}
              </Button>
            )}
          </span>
        </div>
        <p className="mt-2 text-[13px] text-mutedink">{t('billing.usage')}</p>
      </Card>
      <p role="note" className="rounded-xl2 border border-warn/40 bg-warn-bg p-3 text-[13px] text-ink">
        {checkoutAvailable ? t('billing.mockNote') : t('billing.notConfigured')}
      </p>
      <Card>
        <h2 className="mb-2 text-base font-semibold">{t('billing.invoicesTitle')}</h2>
        <ul className="flex flex-col divide-y divide-line">
          {invoices.map((inv) => (
            <li key={inv.id} className="flex items-center gap-3 py-2.5">
              <span className="tnum font-semibold" dir="ltr">
                <bdi>{inv.id}</bdi>
              </span>
              <span className="tnum text-sm text-mutedink" dir="ltr">
                <bdi>{formatDate(inv.date, lang)}</bdi>
              </span>
              <span className="tnum text-sm font-semibold" dir="ltr">
                <bdi>{formatCurrency(inv.amount, lang, 'USD', 0)}</bdi>
              </span>
              <Badge tone={inv.status === 'paid' ? 'gain' : 'warn'}>{t(`billing.${inv.status}`)}</Badge>
              <button
                type="button"
                onClick={() => {
                  const blob = new Blob([`Invoice ${inv.id}\nAmount: ${inv.amount} USD\nStatus: ${inv.status}`], {
                    type: 'text/plain',
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `${inv.id}.txt`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                }}
                className="ms-auto min-h-[44px] rounded-lg px-3 text-sm font-semibold text-brand hover:underline"
              >
                {t('billing.download')}
              </button>
            </li>
          ))}
        </ul>
        <Link to="/pricing" className="mt-2 inline-block text-sm font-semibold text-brand hover:underline">
          {t('nav.pricing')}
        </Link>
      </Card>
    </div>
  );
}
