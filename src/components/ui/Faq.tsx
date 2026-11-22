import { useState } from 'react';
import { ChevronDown } from 'lucide-react';

/** Accessible FAQ accordion (keyboard: buttons, aria-expanded). */
export function Faq({ items }: { items: { q: string; a: string }[] }) {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="flex flex-col gap-3">
      {items.map((it, i) => {
        const isOpen = open === i;
        return (
          <div
            key={i}
            className={`bento-card rounded-xl2 border transition-all duration-200 ${
              isOpen ? 'border-brand/45' : 'border-line/90 hover:border-brand/30'
            }`}
          >
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={`faq-panel-${i}`}
              id={`faq-btn-${i}`}
              onClick={() => setOpen(isOpen ? null : i)}
              className="flex min-h-[52px] w-full items-center justify-between gap-3 px-5 py-3.5 text-start text-[15px] font-bold text-ink"
            >
              {it.q}
              <ChevronDown
                size={18}
                aria-hidden
                className={`shrink-0 transition-transform duration-200 ${
                  isOpen ? 'rotate-180 text-brand' : 'text-mutedink'
                }`}
              />
            </button>
            {isOpen && (
              <p
                id={`faq-panel-${i}`}
                role="region"
                aria-labelledby={`faq-btn-${i}`}
                className="border-t border-line/60 px-5 py-4 text-sm leading-relaxed text-mutedink"
              >
                {it.a}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
