import type { SelectHTMLAttributes } from 'react';

interface Props extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  error?: string;
  options: { value: string; label: string }[];
}

export function Select({ label, error, options, id, className = '', ...rest }: Props) {
  const inputId = id ?? `sel-${label.replace(/\s+/g, '-').toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-xs font-semibold tracking-wide text-mutedink">
        {label}
      </label>
      <select
        id={inputId}
        aria-invalid={Boolean(error)}
        className={`min-h-[46px] rounded-xl border bg-surface/50 px-3.5 py-2.5 text-ink transition-all duration-150 focus:border-brand focus:bg-card focus:ring-2 focus:ring-brand/20 focus:outline-none ${error ? 'border-loss' : 'border-line'} ${className}`}
        {...rest}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="text-[13px] font-medium text-loss">
          {error}
        </p>
      )}
    </div>
  );
}
