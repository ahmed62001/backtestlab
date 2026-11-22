import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Inbox } from 'lucide-react';
import { Button } from './Button';

export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`skeleton min-h-[1rem] ${className}`} />;
}

export function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <Skeleton className="h-8 w-1/3" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="bento-card flex flex-col items-center gap-3.5 rounded-xl2 border border-dashed border-line px-6 py-14 text-center">
      <span className="flex size-14 items-center justify-center rounded-2xl border border-line bg-surface text-brand">
        <Inbox size={24} aria-hidden />
      </span>
      <h3 className="text-base font-bold text-ink">{title}</h3>
      {body && <p className="max-w-md text-sm text-mutedink leading-relaxed">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ onRetry }: { onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center gap-3.5 rounded-xl2 border border-loss/35 bg-loss-bg/80 px-6 py-12 text-center backdrop-blur-sm"
      role="alert"
    >
      <h3 className="text-base font-bold text-loss">{t('common.errorTitle')}</h3>
      <p className="max-w-md text-sm text-ink leading-relaxed">{t('common.errorBody')}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}
