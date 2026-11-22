import { TrendingDown, TrendingUp, Minus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../lib/format';
import type { AppLang } from '../../lib/format';

/**
 * THE only way to render gain/loss values (Binding Rule 1).
 * Always: sign (+/−) + icon (▲/▼/—) + token color. Never color alone.
 */
interface Props {
  value: number | null | undefined;
  suffix?: string;
  decimals?: number;
  className?: string;
  showZeroAsNeutral?: boolean;
}

export function ValueDelta({ value, suffix = '%', decimals = 2, className = '', showZeroAsNeutral = true }: Props) {
  const { i18n } = useTranslation();
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <span className={`inline-flex items-center gap-1 text-mutedink ${className}`}>
        <Minus size={14} aria-hidden />
        <span aria-label="no value">—</span>
      </span>
    );
  }
  const isZero = Math.abs(value) < 10 ** -decimals;
  const positive = value > 0;
  const neutral = showZeroAsNeutral && isZero;
  const color = neutral ? 'text-mutedink' : positive ? 'text-gain' : 'text-loss';
  const Icon = neutral ? Minus : positive ? TrendingUp : TrendingDown;
  const sign = neutral ? '' : positive ? '+' : '−';
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const abs = formatNumber(Math.abs(value), lang, decimals);
  const label = `${neutral ? '0' : sign + abs + suffix}`;
  return (
    <span
      className={`ltr-isolate inline-flex items-center gap-1 font-semibold tnum ${color} ${className}`}
      aria-label={label}
      dir="ltr"
    >
      <Icon size={14} aria-hidden />
      <bdi>
        {neutral ? '0' + suffix : `${sign}${abs}${suffix}`}
        <span className="sr-only">
          {positive
            ? ` (${i18n.language === 'ar' ? 'موجب' : 'positive'})`
            : neutral
              ? ''
              : ` (${i18n.language === 'ar' ? 'سالب' : 'negative'})`}
        </span>
      </bdi>
    </span>
  );
}
