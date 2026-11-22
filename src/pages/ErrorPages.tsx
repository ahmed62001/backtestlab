import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function NotFound() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex max-w-shell flex-col items-center gap-3 px-4 py-16 text-center">
      <p className="tnum text-5xl font-bold text-mutedink" dir="ltr">404</p>
      <h1 className="text-2xl font-bold">{t('errors.notFoundTitle')}</h1>
      <p className="max-w-md text-sm text-mutedink">{t('errors.notFoundBody')}</p>
      <Link to="/" className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-6 py-2 font-semibold text-white hover:bg-brand-hover">
        {t('errors.goHome')}
      </Link>
    </main>
  );
}

export function ErrorPage() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex max-w-shell flex-col items-center gap-3 px-4 py-16 text-center">
      <h1 className="text-2xl font-bold">{t('errors.genericTitle')}</h1>
      <p className="max-w-md text-sm text-mutedink">{t('errors.genericBody')}</p>
      <div className="flex gap-3">
        <Link to="/" className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-6 py-2 font-semibold text-white hover:bg-brand-hover">
          {t('errors.goHome')}
        </Link>
        <button
          type="button"
          onClick={() => window.history.back()}
          className="inline-flex min-h-[44px] items-center rounded-lg border border-line bg-card px-6 py-2 font-semibold text-ink hover:bg-bg"
        >
          {t('errors.goBack')}
        </button>
      </div>
    </main>
  );
}
