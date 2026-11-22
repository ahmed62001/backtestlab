import { useId, type ReactNode } from 'react';
import { Info } from 'lucide-react';

export function Tooltip({ label, children }: { label: string; children?: ReactNode }) {
  const id = useId();
  return (
    <span className="group relative inline-flex items-center gap-1">
      {children}
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="inline-flex size-6 items-center justify-center rounded-full text-mutedink hover:text-ink"
      >
        <Info size={14} aria-hidden />
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none absolute bottom-full z-20 mb-2 hidden w-56 rounded-lg border border-line bg-card p-2 text-[13px] text-ink shadow-lg group-hover:block group-focus-within:block"
      >
        {label}
      </span>
    </span>
  );
}
