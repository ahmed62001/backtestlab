import { forwardRef, type InputHTMLAttributes } from 'react';

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, Props>(
  function Input({ label, error, hint, id, className = '', ...rest }, ref) {
    const inputId = id ?? `in-${label.replace(/\s+/g, '-').toLowerCase()}`;
    const errId = `${inputId}-err`;
    const hintId = `${inputId}-hint`;

    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor={inputId} className="text-xs font-semibold tracking-wide text-mutedink">
          {label}
        </label>
        <input
          ref={ref}
          {...rest}
          id={inputId}
          aria-invalid={Boolean(error)}
          aria-describedby={`${error ? errId : ''} ${hint ? hintId : ''}`.trim() || undefined}
          className={`min-h-[46px] rounded-xl border bg-surface/50 px-3.5 py-2.5 text-ink placeholder:text-mutedink/70 transition-all duration-150 focus:border-brand focus:bg-card focus:ring-2 focus:ring-brand/20 focus:outline-none ${error ? 'border-loss' : 'border-line'} ${className}`}
        />
        {hint && !error && (
          <p id={hintId} className="text-[13px] text-mutedink">{hint}</p>
        )}
        {error && (
          <p id={errId} role="alert" className="text-[13px] font-medium text-loss">
            {error}
          </p>
        )}
      </div>
    );
  },
);