import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { Card } from '../components/ui';
import { formatDate } from '../lib/format';
import type { AppLang } from '../lib/format';

function LegalShell({ titleKey, sectionKey }: { titleKey: string; sectionKey: 'terms' | 'privacy' | 'riskDoc' }) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const ids = [1, 2, 3, 4, 5].map((n) => `legal-${sectionKey}-${n}`);
  return (
    <div className="mx-auto flex max-w-shell flex-col gap-5 px-4 py-10">
      <h1 className="text-3xl font-bold">{t(titleKey)}</h1>
      <p className="text-sm text-mutedink">
        <bdi dir="ltr" className="tnum">{t('legal.updated', { date: formatDate('2026-10-01', lang) })}</bdi>
      </p>
      <p role="note" className="flex items-start gap-2 rounded-xl2 border border-warn/40 bg-warn-bg p-3 text-[13px] text-ink">
        <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0 text-warn" />
        {t('legal.lawyerNote')}
      </p>
      <nav aria-label={t('legal.toc')} className="rounded-xl2 border border-line bg-card p-4">
        <h2 className="mb-2 text-sm font-semibold text-mutedink">{t('legal.toc')}</h2>
        <ol className="flex list-decimal flex-col gap-1 ps-5 text-sm">
          {[1, 2, 3, 4, 5].map((n, i) => (
            <li key={n}>
              <a href={`#${ids[i]}`} className="font-medium text-brand hover:underline">{t(`legal.${sectionKey}.s${n}t`)}</a>
            </li>
          ))}
        </ol>
      </nav>
      {[1, 2, 3, 4, 5].map((n, i) => (
        <Card key={n}>
          <h2 id={ids[i]} className="mb-1 text-lg font-semibold" tabIndex={-1}>
            {t(`legal.${sectionKey}.s${n}t`)}
          </h2>
          <p className="text-sm text-mutedink">{t(`legal.${sectionKey}.s${n}b`)}</p>
        </Card>
      ))}
      <Link to="/" className="text-sm font-semibold text-brand hover:underline">
        {t('legal.backHome')}
      </Link>
    </div>
  );
}

export function Terms() {
  return <LegalShell titleKey="legal.termsTitle" sectionKey="terms" />;
}

export function Privacy() {
  return <LegalShell titleKey="legal.privacyTitle" sectionKey="privacy" />;
}

export function Risk() {
  return <LegalShell titleKey="legal.riskTitle" sectionKey="riskDoc" />;
}
