import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'destructive' | 'ghost' | 'gold';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  children: ReactNode;
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading,
  children,
  className = '',
  disabled,
  ...rest
}: Props) {
  const base =
    'inline-flex items-center justify-center gap-2 font-semibold rounded-xl transition-all duration-200 ease-out min-h-[44px] focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none disabled:shadow-none';
  const variants: Record<string, string> = {
    primary:
      'brand-gradient text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]',
    secondary:
      'border border-line bg-card text-ink hover:bg-surface hover:border-brand/45 shadow-sm hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]',
    destructive:
      'bg-loss text-white shadow-sm hover:opacity-90 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]',
    ghost: 'text-ink hover:bg-surface hover:text-ink active:scale-[0.98]',
    gold: 'gold-gradient text-white shadow-sm hover:shadow-glow-gold hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]',
  };
  const sizes: Record<string, string> = {
    sm: 'px-3.5 py-1.5 text-sm min-h-[40px]',
    md: 'px-5 py-2.5 text-[14px]',
    lg: 'px-7 py-3.5 text-base',
  };
  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      )}
      {children}
    </button>
  );
}
