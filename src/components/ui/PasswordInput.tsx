import { forwardRef, useState, type InputHTMLAttributes } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import { Input } from './Input';

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string;
  error?: string;
  hint?: string;
}

export const PasswordInput = forwardRef<HTMLInputElement, Props>(
  function PasswordInput({ label, error, hint, ...rest }, ref) {
    const { t } = useTranslation();
    const [show, setShow] = useState(false);

    return (
      <div className="relative">
        <Input
          {...rest}
          ref={ref}
          label={label}
          type={show ? 'text' : 'password'}
          error={error}
          hint={hint}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? t('auth.hidePassword') : t('auth.showPassword')}
          aria-pressed={show}
          className="absolute end-2 top-8 flex size-10 items-center justify-center rounded-xl text-mutedink transition-colors hover:bg-surface hover:text-ink"
        >
          {show ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}
        </button>
      </div>
    );
  },
);