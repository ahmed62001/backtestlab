import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Check, Sparkles } from 'lucide-react';
import { Badge, Card, Faq, RiskBanner } from '../components/ui';
import { FREE_DAILY_LIMIT, PRO_DAILY_LIMIT } from '../lib/constants';
import { formatCurrency } from '../lib/format';
import type { AppLang } from '../lib/format';

export function Pricing() {
  const { t, i18n } = useTranslation();
  const [cycle, setCycle] = useState<'monthly' | 'yearly'>('monthly');
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const faq = [1, 2, 3].map((n) => ({ q: t(`pricing.faq${n}q`), a: t(`pricing.faq${n}a`) }));

  return (
    <div className="mx-auto flex max-w-shell flex-col gap-10 px-4 py-12">
      <div className="text-center">
        <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-line bg-card/80 px-3 py-1 text-xs font-semibold text-mutedink shadow-sm">
          <Sparkles size={13} className="text-brand shrink-0" aria-hidden />
          <span>Institutional Grade Engine</span>
        </div>
        <h1 className="text-3xl font-black tracking-tight text-ink sm:text-4xl">{t('pricing.title')}</h1>
        <p className="mx-auto mt-2 max-w-lg text-sm text-mutedink sm:text-base">{t('pricing.sub')}</p>
        
        <div className="mt-6 inline-flex items-center gap-1 rounded-full border border-line bg-card p-1.5 shadow-bento" role="group" aria-label={t('pricing.title')}>
          {(['monthly', 'yearly'] as const).map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={cycle === c}
              onClick={() => setCycle(c)}
              className={`min-h-[42px] rounded-full px-5 text-sm font-semibold transition-all duration-200 ${
                cycle === c ? 'bg-brand text-white shadow-sm' : 'text-mutedink hover:text-ink'
              }`}
            >
              {c === 'monthly' ? t('pricing.monthly') : t('pricing.yearly')}
            </button>
          ))}
          {cycle === 'yearly' && (
            <Badge tone="gain" dot className="ms-1 me-2">
              {t('pricing.saveNote')}
            </Badge>
          )}
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Free Plan */}
        <Card interactive className="flex flex-col justify-between p-6">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-xl font-bold text-ink">{t('pricing.freeName')}</h2>
              <Badge tone="neutral">Free</Badge>
            </div>
            <p className="text-xs text-mutedink mb-4">Core backtesting tools for independent researchers and hobbyists.</p>
            <div className="mb-6 flex items-baseline gap-1.5">
              <bdi dir="ltr" className="tnum text-4xl font-black text-ink">
                {formatCurrency(0, lang, 'USD', 0)}
              </bdi>
              <span className="text-sm text-mutedink">
                {cycle === 'monthly' ? t('pricing.perMonth') : t('pricing.perYear')}
              </span>
            </div>
            <ul className="mb-8 flex flex-col gap-3 text-sm text-mutedink">
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>
                  {t('dashboard.usage')}: <bdi dir="ltr" className="tnum font-semibold text-ink">{FREE_DAILY_LIMIT}</bdi> / day
                </span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>{t('nav.templates')}</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>{t('results.exportCsv')}</span>
              </li>
            </ul>
          </div>
          <Link
            to="/register"
            className="inline-flex min-h-[46px] w-full items-center justify-center rounded-xl border border-line bg-surface/60 px-4 py-2.5 font-semibold text-ink transition-all duration-200 hover:-translate-y-0.5 hover:border-brand/45 hover:bg-surface active:scale-[0.98]"
          >
            {t('pricing.freeCta')}
          </Link>
        </Card>

        {/* Pro Plan */}
        <Card interactive className="relative flex flex-col justify-between border-brand/60 glow-brand-subtle p-6">
          <div className="absolute -top-3 end-6">
            <Badge tone="brand" dot className="shadow-sm">
              Pro Trader
            </Badge>
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-xl font-bold text-ink">{t('pricing.proName')}</h2>
            </div>
            <p className="text-xs text-mutedink mb-4">High-throughput institutional backtesting with multi-asset coverage.</p>
            <div className="mb-6 flex items-baseline gap-1.5">
              <bdi dir="ltr" className="tnum text-4xl font-black text-ink">
                {formatCurrency(cycle === 'monthly' ? 19 : 182, lang, 'USD', 0)}
              </bdi>
              <span className="text-sm text-mutedink">
                {cycle === 'monthly' ? t('pricing.perMonth') : t('pricing.perYear')}
              </span>
            </div>
            <ul className="mb-8 flex flex-col gap-3 text-sm text-mutedink">
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>
                  {t('dashboard.usage')}: <bdi dir="ltr" className="tnum font-semibold text-ink">{PRO_DAILY_LIMIT}</bdi> / day
                </span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>{t('nav.compare')} (Side-by-side strategy diffs)</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>{t('nav.templates')} (Institutional strategies)</span>
              </li>
              <li className="flex items-center gap-2.5">
                <Check size={16} aria-hidden className="shrink-0 text-gain" />
                <span>Extended historical multi-asset resolution</span>
              </li>
            </ul>
          </div>
          <Link
            to="/register"
            className="brand-gradient inline-flex min-h-[46px] w-full items-center justify-center rounded-xl px-4 py-2.5 font-semibold text-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-glow active:scale-[0.98]"
          >
            {t('pricing.proCta')}
          </Link>
        </Card>
      </div>

      <p role="note" className="rounded-xl2 border border-warn/40 bg-warn-bg p-3.5 text-center text-[13px] text-ink">
        {t('pricing.mockNote')}
      </p>

      <section aria-labelledby="pricing-faq" className="mt-2">
        <h2 id="pricing-faq" className="mb-4 text-2xl font-bold tracking-tight text-ink">{t('pricing.faqTitle')}</h2>
        <Faq items={faq} />
      </section>

      <RiskBanner compact />
    </div>
  );
}
