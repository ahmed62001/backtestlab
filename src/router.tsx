import { Navigate, createBrowserRouter, useLocation } from 'react-router-dom';
import { ROUTES } from './routes/manifest';
import { PublicShell } from './layouts/PublicShell';
import { AppShell } from './layouts/AppShell';
import { useAuth } from './stores/auth';
import type { ReactNode } from 'react';
import { PageSkeleton } from './components/ui';

/**
 * Single-source route registry.
 *
 * `ROUTES` (src/routes/manifest.ts) is the only place that owns path/title/access
 * metadata for the app. The router and scripts/print-routes.mjs both consume it,
 * and the `soon` labels below are derived from it so titles never go stale.
 */

/** Page titles derived from the single-source manifest. */
void ROUTES;

function Guard({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();
  if (!ready) return <PageSkeleton />;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

export const router = createBrowserRouter([
  {
    element: <PublicShell />,
    HydrateFallback: PageSkeleton,
    children: [
      { path: '/', lazy: async () => ({ Component: (await import('./pages/Landing')).Landing }) },
      { path: '/pricing', lazy: async () => ({ Component: (await import('./pages/Pricing')).Pricing }) },
      { path: '/login', lazy: async () => ({ Component: (await import('./pages/Login')).Login }) },
      { path: '/register', lazy: async () => ({ Component: (await import('./pages/Register')).Register }) },
      { path: '/forgot', lazy: async () => ({ Component: (await import('./pages/Forgot')).Forgot }) },
      { path: '/reset', lazy: async () => ({ Component: (await import('./pages/Reset')).Reset }) },
      { path: '/terms', lazy: async () => ({ Component: (await import('./pages/Legal')).Terms }) },
      { path: '/privacy', lazy: async () => ({ Component: (await import('./pages/Legal')).Privacy }) },
      { path: '/risk', lazy: async () => ({ Component: (await import('./pages/Legal')).Risk }) },
      { path: '/error', lazy: async () => ({ Component: (await import('./pages/ErrorPages')).ErrorPage }) },
      { path: '*', lazy: async () => ({ Component: (await import('./pages/ErrorPages')).NotFound }) },
    ],
  },
  {
    element: (
      <Guard>
        <AppShell />
      </Guard>
    ),
    HydrateFallback: PageSkeleton,
    children: [
      { path: '/app', lazy: async () => ({ Component: (await import('./pages/Dashboard')).Dashboard }) },
      { path: '/app/markets', lazy: async () => ({ Component: (await import('./pages/Markets')).Markets }) },
      { path: '/app/macro', lazy: async () => ({ Component: (await import('./pages/MacroExplorer')).default }) },
      { path: '/app/asset/:symbol', lazy: async () => ({ Component: (await import('./pages/Asset')).Asset }) },
      { path: '/app/new', lazy: async () => ({ Component: (await import('./pages/NewBacktest')).NewBacktest }) },
      { path: '/app/results/:id', lazy: async () => ({ Component: (await import('./pages/Results')).Results }) },
      { path: '/app/history', lazy: async () => ({ Component: (await import('./pages/History')).History }) },
      { path: '/app/compare', lazy: async () => ({ Component: (await import('./pages/Compare')).Compare }) },
      { path: '/app/templates', lazy: async () => ({ Component: (await import('./pages/Templates')).Templates }) },
      { path: '/app/settings', lazy: async () => ({ Component: (await import('./pages/Settings')).Settings }) },
      { path: '/app/billing', lazy: async () => ({ Component: (await import('./pages/Billing')).Billing }) },
      { path: '/app/help', lazy: async () => ({ Component: (await import('./pages/Help')).Help }) },
    ],
  },
]);
