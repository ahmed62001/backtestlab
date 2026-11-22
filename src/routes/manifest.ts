/**
 * Single source of truth for the app's route list.
 *
 * Every page/route is defined here as (path + title + access level) and is consumed by:
 *   - src/router.tsx             (page titles, sync guard)
 *   - scripts/print-routes.mjs   (start.sh "print routes" table + test accounts)
 *   - docs/ROUTES.md             (generated from this manifest)
 *
 * To add a page: append a route def here, then rebuild/restart. The router and
 * start.sh both derive from this list, so it never goes stale.
 */

export type RouteAccess = 'public' | 'auth' | 'app' | 'legal' | '404';

export interface RouteDef {
  /** URL path (without the dev server origin). */
  path: string;
  /** Human-readable page title. */
  title: string;
  /** Access tier for the route table. */
  access: RouteAccess;
}

export interface DemoCredentials {
  email: string;
  password: string;
}

/**
 * The mock limit-reached account.
 *
 * No account is pre-seeded, so this remains null. The free daily limit (3
 * backtests) is enforced per-browser via the localStorage key `bl_usage`, so any
 * fresh free account hits it after 3 successful backtests. The mock throws
 * `{ code: 'limit', messageKey: 'run.errors.limitReached' }` at that point.
 */
export interface LimitReachedAccount {
  exists: false;
  note: string;
}

export interface MockUserAccounts {
  demo: DemoCredentials;
  limitReached: LimitReachedAccount | null;
}

/** Pages / routes. */
export const ROUTES: RouteDef[] = [
  // ── public ───────────────────────────────────────────────────────────────
  { path: '/', title: 'Dashboard', access: 'public' },
  { path: '/pricing', title: 'Pricing', access: 'public' },

  // ── auth ─────────────────────────────────────────────────────────────────
  { path: '/login', title: 'Log in', access: 'auth' },
  { path: '/register', title: 'Sign up', access: 'auth' },
  { path: '/forgot', title: 'Forgot password', access: 'auth' },
  { path: '/reset', title: 'Reset password', access: 'auth' },

  // ── app (auth-guarded) ───────────────────────────────────────────────────
  { path: '/app', title: 'Dashboard', access: 'app' },
  { path: '/app/markets', title: 'Markets', access: 'app' },
  { path: '/app/macro', title: 'Macro Explorer', access: 'app' },
  { path: '/app/asset/:symbol', title: 'Asset details', access: 'app' },
  { path: '/app/new', title: 'New backtest', access: 'app' },
  { path: '/app/results/:id', title: 'Backtest results', access: 'app' },
  { path: '/app/history', title: 'History', access: 'app' },
  { path: '/app/compare', title: 'Compare', access: 'app' },
  { path: '/app/templates', title: 'Templates', access: 'app' },
  { path: '/app/settings', title: 'Settings', access: 'app' },
  { path: '/app/billing', title: 'Billing', access: 'app' },
  { path: '/app/help', title: 'Help', access: 'app' },

  // ── legal ────────────────────────────────────────────────────────────────
  { path: '/terms', title: 'Terms of Service', access: 'legal' },
  { path: '/privacy', title: 'Privacy Policy', access: 'legal' },
  { path: '/risk', title: 'Risk Disclosure', access: 'legal' },

  // ── 404 ──────────────────────────────────────────────────────────────────
  { path: '*', title: '404 — Not Found', access: '404' },
];

/** Single source of truth for the app name (kept in sync with src/lib/constants). */
export const APP_NAME = 'BacktestLab';

/** Demo login for the mock user. Works with the in-browser mock API. */
export const DEMO_CREDENTIALS: DemoCredentials = {
  email: 'demo@backtestlab.app',
  password: 'demo-pass-1234',
};

/** Mock limit-reached account (not pre-seeded — see LimitReachedAccount). */
export const LIMIT_REACHED_ACCOUNT: MockUserAccounts['limitReached'] = null;
