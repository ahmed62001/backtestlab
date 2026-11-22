import type { ReactNode } from 'react';

export function Card({
  children,
  className = '',
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={`bento-card rounded-xl2 border border-line/90 p-5 transition-all duration-300 ease-out sm:p-6 ${
        interactive
          ? 'bento-card-interactive hover:-translate-y-1 hover:border-brand/50'
          : ''
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <h3 className={`text-base font-bold tracking-tight text-ink ${className}`}>{children}</h3>;
}
