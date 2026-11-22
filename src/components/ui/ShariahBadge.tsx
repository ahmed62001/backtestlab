import { useTranslation } from 'react-i18next';
import { Badge } from './Badge';
import { Tooltip } from './Tooltip';

/** Compliant Shariah-screening label: indicative only, never certified/guaranteed. */
export function ShariahBadge() {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1">
      <Badge tone="neutral">
        <bdi>{t('shariah.label')}</bdi>
      </Badge>
      <Tooltip label={t('shariah.tooltip')} />
    </span>
  );
}
