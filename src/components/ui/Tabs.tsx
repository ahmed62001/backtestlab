import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div role="tablist" aria-label={t('run.title')} className="flex gap-1.5 rounded-2xl border border-line/80 bg-surface/70 p-1.5">
      {tabs.map((tab, i) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={active === tab.id}
          tabIndex={active === tab.id ? 0 : -1}
          onKeyDown={(e) => {
            const idx = tabs.findIndex((x) => x.id === active);
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              const dir = document.documentElement.dir === 'rtl' ? -1 : 1;
              const step = e.key === 'ArrowRight' ? dir : -dir;
              const next = tabs[(idx + step + tabs.length) % tabs.length];
              onChange(next.id);
              document.getElementById(`tab-${next.id}`)?.focus();
            }
            void i;
          }}
          id={`tab-${tab.id}`}
          onClick={() => onChange(tab.id)}
          className={`min-h-[42px] flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition-all duration-200 ${
            active === tab.id
              ? 'bg-card text-brand shadow-bento ring-1 ring-line/80'
              : 'text-mutedink hover:text-ink hover:bg-card/40'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function TableShell({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div
      className="bento-card overflow-x-auto rounded-xl2 border border-line/90 [contain:paint]"
      role="region"
      aria-label={label}
      // A scrollable region must be keyboard focusable (WCAG 2.1.1); this is
      // the documented exception to no-noninteractive-tabindex.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
    >
      {children}
    </div>
  );
}
