/**
 * Authoritative backtest date constraints for the wizard.
 *
 * This module is the single source of truth shared by both date inputs, the
 * client-side validation and the review-step summary. It deliberately mirrors
 * the backend validator in `backend/app/main.py::_validate_backtest_input`:
 *
 *   _MIN_DATE = date(2015, 1, 1)
 *   to_dt >= today (UTC)  -> rejected, so the latest selectable end date is
 *                           yesterday in UTC.
 *   (to_dt - from_dt).days < 180 -> rejected.
 *
 * The backend remains the source of truth at run time; this mirror only keeps
 * the UI from advertising a range the server would reject. There is no
 * asset/provider-specific coverage exposed by the backend, so none is invented
 * here. If the backend later exposes coverage metadata, replace this mirror
 * with that API.
 */

/** Earliest selectable start date (matches backend `_MIN_DATE`). */
export const MIN_BACKTEST_DATE = '2015-01-01';

/** Minimum number of days between start and end (matches backend rule). */
export const MIN_BACKTEST_RANGE_DAYS = 180;

/** Format a Date as a UTC `YYYY-MM-DD` string. */
export function utcDateString(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/**
 * Latest selectable end date: yesterday in UTC. The backend rejects
 * `to >= today` (UTC), so the maximum inclusive date is `today - 1 day`.
 * Using UTC (not the browser timezone) keeps the client and server aligned.
 */
export function maxBacktestDate(now: Date = new Date()): string {
  const d = new Date(now.getTime());
  d.setUTCDate(d.getUTCDate() - 1);
  return utcDateString(d);
}

/** True for a real calendar date in `YYYY-MM-DD` form. */
export function isValidIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && utcDateString(d) === value;
}

/** Whole days between two `YYYY-MM-DD` strings (negative when reversed). */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/**
 * Validate a requested backtest range with the same rules as the backend.
 * Returns a translation key (`run.badDates`) for display, or `''` when valid.
 */
export function validateBacktestDates(
  from: string | undefined,
  to: string | undefined,
  now: Date = new Date(),
): '' | 'run.badDates' {
  if (!from || !to) return 'run.badDates';
  if (!isValidIsoDate(from) || !isValidIsoDate(to)) return 'run.badDates';
  if (from < MIN_BACKTEST_DATE) return 'run.badDates';
  if (to > maxBacktestDate(now)) return 'run.badDates';
  if (from >= to) return 'run.badDates';
  if (daysBetween(from, to) < MIN_BACKTEST_RANGE_DAYS) return 'run.badDates';
  return '';
}
