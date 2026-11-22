import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function RiskBanner({ compact }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div
      role="note"
      aria-label={t('disclaimer.historical')}
      className={`flex items-start gap-3.5 rounded-xl2 border border-warn/35 bg-warn-bg/75 backdrop-blur-sm text-ink ${compact ? 'p-3.5 text-[13px]' : 'p-5 text-sm'}`}
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-warn/15 text-warn">
        <AlertTriangle size={17} aria-hidden />
      </span>
      <div className="flex flex-col gap-1">
        <p className="font-bold">{t('disclaimer.historical')}</p>
        {!compact && <p className="text-mutedink leading-relaxed">{t('disclaimer.notAdvice')}</p>}
      </div>
    </div>
  );
}
