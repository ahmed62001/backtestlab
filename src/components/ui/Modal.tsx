import { useEffect, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <button
        type="button"
        aria-label={t('common.cancel')}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-md transition-opacity"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="glass-card relative w-full max-w-md rounded-xl3 border border-line p-6 shadow-2xl animate-fade-in-up"
      >
        <div className="mb-5 flex items-start justify-between gap-4 border-b border-line/70 pb-3.5">
          <h2 className="text-lg font-bold tracking-tight text-ink">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.cancel')}
            className="flex size-9 items-center justify-center rounded-xl text-mutedink transition-colors hover:bg-surface hover:text-ink"
          >
            <X size={18} aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
