import {
  forwardRef,
  useEffect,
  useId,
  useState,
  type InputHTMLAttributes,
} from 'react';

interface Props
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> {
  label: string;
  /** Numeric value or undefined while the field is empty. */
  value: number | undefined;
  /** Emits a finite number, or undefined when the field is cleared. */
  onValueChange: (value: number | undefined) => void;
  error?: string;
  hint?: string;
}

/**
 * Controlled numeric input that keeps the user's raw keystrokes in local
 * state and only reports finite numbers upward.
 *
 * A plain `type="number"` bound to a number produces two classic defects:
 * clearing the field yields `Number('') === 0`, and typing a decimal point
 * ("0.") is immediately normalized away. This component preserves the text
 * while focused, then normalizes it on blur, without changing the numeric
 * value that callers send to the API.
 */
export const NumberField = forwardRef<HTMLInputElement, Props>(function NumberField(
  { label, value, onValueChange, error, hint, id, className = '', onBlur, ...rest },
  ref,
) {
  const generated = useId();
  const inputId = id ?? `num-${generated}`;
  const errId = `${inputId}-err`;
  const hintId = `${inputId}-hint`;
  const [text, setText] = useState(value === undefined ? '' : String(value));
  const [focused, setFocused] = useState(false);

  // Adopt external changes (including defaults loaded from the draft) while
  // the user is not actively typing.
  useEffect(() => {
    if (!focused) setText(value === undefined ? '' : String(value));
  }, [value, focused]);

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-xs font-semibold tracking-wide text-mutedink">
        {label}
      </label>
      <input
        ref={ref}
        {...rest}
        id={inputId}
        type="number"
        inputMode="decimal"
        value={text}
        onFocus={(e) => {
          setFocused(true);
          rest.onFocus?.(e);
        }}
        onChange={(e) => {
          const raw = e.target.value;
          setText(raw);
          if (raw.trim() === '') {
            onValueChange(undefined);
            return;
          }
          const next = Number(raw);
          if (Number.isFinite(next)) onValueChange(next);
        }}
        onBlur={(e) => {
          setFocused(false);
          setText(value === undefined ? '' : String(value));
          onBlur?.(e);
        }}
        aria-invalid={Boolean(error)}
        aria-describedby={`${error ? errId : ''} ${hint ? hintId : ''}`.trim() || undefined}
        className={`min-h-[46px] rounded-xl border bg-surface/50 px-3.5 py-2.5 text-ink tabular-nums placeholder:text-mutedink/70 transition-all duration-150 focus:border-brand focus:bg-card focus:ring-2 focus:ring-brand/20 focus:outline-none disabled:opacity-60 ${error ? 'border-loss' : 'border-line'} ${className}`}
      />
      {hint && !error && (
        <p id={hintId} className="text-[13px] text-mutedink">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} role="alert" className="text-[13px] font-medium text-loss">
          {error}
        </p>
      )}
    </div>
  );
});
