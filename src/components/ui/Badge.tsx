import type { ReactNode } from 'react';

export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className = '',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'gain' | 'loss' | 'warn' | 'brand' | 'gold';
  dot?: boolean;
  className?: string;
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-surface/80 text-mutedink border-line',
    gain: 'bg-gain-bg text-gain border-gain/30',
    loss: 'bg-loss-bg text-loss border-loss/30',
    warn: 'bg-warn-bg text-warn border-warn/30',
    brand: 'bg-brand/12 text-brand border-brand/30',
    gold: 'bg-gold-bg text-gold border-gold/35',
  };
  const dotTones: Record<string, string> = {
    neutral: 'bg-mutedink',
    gain: 'bg-gain',
    loss: 'bg-loss',
    warn: 'bg-warn',
    brand: 'bg-brand',
    gold: 'bg-gold',
  };
  return (
    <span
      className={`inline-flex min-h-[26px] items-center gap-1.5 rounded-full border px-3 py-0.5 text-[12px] font-semibold tracking-wide ${tones[tone]} ${className}`}
    >
      {dot && <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${dotTones[tone]}`} />}
      {children}
    </span>
  );
}
