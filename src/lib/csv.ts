import type { Trade } from '../types';

/** Client-side CSV export for the trades table (Group E). */
export function tradesToCsv(trades: Trade[]): string {
  const head = 'id,date,side,price,qty,pnl,returnPct';
  const esc = (v: string | number | null): string => {
    if (v === null) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = trades.map((t) => [t.id, t.date, t.side, t.price, t.qty, t.pnl, t.returnPct].map(esc).join(','));
  return [head, ...rows].join('\n');
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
