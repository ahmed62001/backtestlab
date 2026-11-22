import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { heatCellStyle } from '../../lib/chartTheme';
import { usePrefs } from '../../stores/prefs';
import type { MonthlyCell } from '../../types';

export function MonthlyHeatmap({ cells }: { cells: MonthlyCell[] }) {
  const { t } = useTranslation();
  const { theme } = usePrefs();
  const months = t('months', { returnObjects: true }) as unknown as string[];
  const years = useMemo(() => [...new Set(cells.map((c) => c.year))].sort(), [cells]);
  return (
    <div role="img" aria-label={t('results.monthly')} className="overflow-x-auto" dir="ltr">
      <table className="w-full min-w-[560px] border-collapse text-center text-[13px]">
        <thead>
          <tr>
            <th className="p-2 text-mutedink" scope="col" />
            {months.map((m) => (
              <th key={m} scope="col" className="p-2 font-medium text-mutedink">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <th scope="row" className="tnum p-2 text-mutedink">
                {y}
              </th>
              {months.map((_, mi) => {
                const cell = cells.find((c) => c.year === y && c.month === mi);
                const v = cell?.value ?? null;
                const style = heatCellStyle(theme, v);
                return (
                  <td key={mi} className="p-0.5">
                    <span
                      className="tnum block rounded-md px-1 py-2 font-semibold"
                      style={{ background: style.background, color: style.color }}
                      title={v === null ? '—' : `${v > 0 ? '+' : ''}${v}%`}
                    >
                      {v === null ? '—' : `${v > 0 ? '+' : ''}${v}`}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
