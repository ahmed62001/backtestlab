import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Bell,
  ChevronDown,
  CreditCard,
  FlaskConical,
  GitCompareArrows,
  Globe,
  History,
  LayoutDashboard,
  LayoutTemplate,
  LifeBuoy,
  LineChart,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings,
  Sun,
  X,
} from 'lucide-react';
import { APP_NAME } from '../lib/constants';
import { useAuth } from '../stores/auth';
import { usePrefs } from '../stores/prefs';
import { setLanguage } from '../i18n';
import { apiGetNotifications } from '../api';
import { TickerTape } from '../components/market/TickerTape';
import { BackToTop, CommandPalette } from '../components/ui';
import type { AppNotification } from '../types';

interface NavItem {
  to: string;
  icon: typeof LayoutDashboard;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

/**
 * App shell: modern sidebar quant workspace + top utility bar & ticker tape.
 * 100% RTL/LTR logical styling, quick command switcher (⌘K),
 * notification drawer, and mobile ergonomics.
 */
export function AppShell() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme, lang, setLang } = usePrefs();
  const [drawer, setDrawer] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [showNotif, setShowNotif] = useState(false);
  const [notifs, setNotifs] = useState<AppNotification[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    apiGetNotifications()
      .then(setNotifs)
      .catch(() => setNotifs([]));
  }, []);

  const unread = notifs.filter((n) => !n.read).length;

  const primary: NavItem[] = [
    { to: '/app', icon: LayoutDashboard, label: t('nav.overview') },
    { to: '/app/markets', icon: LineChart, label: t('nav.markets') },
    { to: '/app/macro', icon: Globe, label: t('nav.macro') },
  ];
  const groups: NavGroup[] = [
    {
      label: t('nav.backtesting'),
      items: [
        { to: '/app/new', icon: FlaskConical, label: t('nav.newBacktest') },
        { to: '/app/templates', icon: LayoutTemplate, label: t('nav.strategies') },
        { to: '/app/compare', icon: GitCompareArrows, label: t('nav.compare') },
      ],
    },
  ];
  const resultsItem: NavItem = { to: '/app/history', icon: History, label: t('nav.results') };
  const accountItems: NavItem[] = [
    { to: '/app/settings', icon: Settings, label: t('nav.settings') },
    { to: '/app/billing', icon: CreditCard, label: t('nav.billing') },
    { to: '/app/help', icon: LifeBuoy, label: t('nav.help') },
  ];

  const switchLang = () => {
    const next = lang === 'ar' ? 'en' : 'ar';
    setLang(next);
    setLanguage(next);
  };

  const renderItem = (l: NavItem, onClick?: () => void) => (
    <NavLink
      key={l.to}
      to={l.to}
      end={l.to === '/app'}
      onClick={onClick}
      className={({ isActive }) =>
        'group flex min-h-[42px] items-center gap-3 rounded-xl px-3.5 text-[14px] font-medium transition-all duration-150 ' +
        (isActive
          ? 'brand-gradient text-white font-semibold shadow-sm'
          : 'text-mutedink hover:bg-surface/90 hover:text-ink')
      }
    >
      <l.icon size={17} aria-hidden className="shrink-0" />
      <span className="truncate">{l.label}</span>
    </NavLink>
  );

  return (
    <div className="min-h-screen text-ink flex">
      <a href="#main" className="skip-link">
        {t('common.learnMore')}
      </a>

      {/* Desktop Left/Start Sidebar Navigation */}
      <aside
        className="hidden lg:flex lg:w-64 lg:shrink-0 lg:flex-col border-e border-line/80 bg-card/85 backdrop-blur-xl sticky top-0 h-screen"
        aria-label={t('a11y.sidebar')}
      >
        {/* Brand Header */}
        <div className="flex h-16 items-center gap-3 border-b border-line/70 px-5">
          <Link to="/app" className="group flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
            <span
              aria-hidden
              className="brand-gradient flex size-9 items-center justify-center rounded-xl text-sm font-black text-white shadow-glow transition-transform duration-200 group-hover:scale-105"
            >
              B
            </span>
            <div className="flex flex-col leading-none">
              <span>{APP_NAME}</span>
              <span className="mt-0.5 text-[10px] font-bold uppercase tracking-widest text-brand">
                Quant Desk
              </span>
            </div>
          </Link>
        </div>

        {/* Sidebar Quick Search */}
        <div className="px-3.5 pt-4 pb-2">
          <button
            type="button"
            onClick={() => setCmdOpen(true)}
            className="flex w-full items-center justify-between gap-2 rounded-xl border border-line/80 bg-surface/60 px-3 py-2 text-xs text-mutedink transition-all hover:border-brand/50 hover:bg-surface hover:text-ink"
            aria-label={t('common.quickSearch')}
          >
            <span className="flex items-center gap-2 truncate">
              <Search size={14} aria-hidden className="shrink-0 text-brand" />
              <span className="truncate">{t('common.quickSearch')}</span>
            </span>
            <kbd className="rounded-md border border-line bg-card px-1.5 py-0.5 text-[10px] font-mono text-mutedink">
              ⌘K
            </kbd>
          </button>
        </div>

        {/* Navigation Links */}
        <nav className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-1" aria-label={t('a11y.sidebar')}>
          {primary.map((l) => renderItem(l))}
          {groups.map((g) => (
            <div key={g.label} className="mt-3">
              <p className="px-3.5 pb-1.5 text-[11px] font-bold uppercase tracking-widest text-mutedink/80">
                {g.label}
              </p>
              <div className="flex flex-col gap-1">{g.items.map((l) => renderItem(l))}</div>
            </div>
          ))}
          <div className="mt-2">{renderItem(resultsItem)}</div>
          <div className="mt-3">
            <p className="px-3.5 pb-1.5 text-[11px] font-bold uppercase tracking-widest text-mutedink/80">
              {t('nav.account')}
            </p>
            <div className="flex flex-col gap-1">{accountItems.map((l) => renderItem(l))}</div>
          </div>
        </nav>

        {/* Sidebar User Footer */}
        <div className="border-t border-line/70 p-3">
          <div className="flex items-center justify-between gap-2 rounded-xl border border-line/70 bg-surface/50 p-2.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold text-white">
                {user?.name ? user.name[0].toUpperCase() : 'U'}
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs font-bold text-ink">{user?.name}</p>
                <p className="truncate text-[11px] text-mutedink">{user?.email}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                logout();
                navigate('/login');
              }}
              className="flex size-8 shrink-0 items-center justify-center rounded-lg text-mutedink transition-colors hover:bg-loss-bg hover:text-loss"
              title={t('nav.logout')}
              aria-label={t('nav.logout')}
            >
              <LogOut size={15} aria-hidden />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Column: Top Utility Bar + Ticker Tape + Workspace */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 overflow-x-clip border-b border-line/70 glass-header transition-all duration-200">
          <div className="mx-auto flex h-16 max-w-shell items-center gap-2 px-4 sm:px-6">
            <button
              className="flex size-10 items-center justify-center rounded-xl hover:bg-surface text-mutedink hover:text-ink lg:hidden"
              onClick={() => setDrawer(true)}
              aria-label={t('a11y.menu')}
            >
              <Menu size={22} aria-hidden />
            </button>
            <Link to="/app" className="flex items-center gap-2.5 text-lg font-extrabold tracking-tight lg:hidden">
              <span
                aria-hidden
                className="brand-gradient flex size-8 items-center justify-center rounded-xl text-xs font-black text-white shadow-glow"
              >
                B
              </span>
              <span>{APP_NAME}</span>
            </Link>

            {/* Quick CTA on Desktop Topbar */}
            <div className="hidden items-center gap-2 lg:flex">
              <Link
                to="/app/new"
                className="brand-gradient inline-flex min-h-[38px] items-center gap-1.5 rounded-xl px-4 py-1.5 text-xs font-bold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 transition-all"
              >
                <FlaskConical size={14} aria-hidden />
                <span>{t('nav.newBacktest')}</span>
              </Link>
            </div>

            {/* Utility Controls */}
            <div className="ms-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCmdOpen(true)}
                className="flex size-10 items-center justify-center rounded-xl text-mutedink hover:bg-surface hover:text-ink lg:hidden"
                aria-label={t('common.quickSearch')}
              >
                <Search size={18} aria-hidden />
              </button>

              {/* Language Toggle */}
              <button
                onClick={switchLang}
                className="flex min-h-[38px] items-center gap-1.5 rounded-xl border border-line/70 bg-card/70 px-3 text-xs font-bold text-mutedink hover:border-brand/45 hover:text-ink transition-all"
                aria-label={t('a11y.language')}
              >
                <Globe size={15} aria-hidden className="text-brand" />
                <span>{lang === 'ar' ? 'EN' : 'عربي'}</span>
              </button>

              {/* Theme Toggle */}
              <button
                onClick={toggleTheme}
                className="flex size-10 items-center justify-center rounded-xl border border-line/70 bg-card/70 text-mutedink hover:border-brand/45 hover:text-brand transition-all"
                aria-label={t('a11y.theme')}
              >
                {theme === 'dark' ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
              </button>

              {/* Notifications */}
              <div className="relative">
                <button
                  onClick={() => setShowNotif((v) => !v)}
                  onKeyDown={(e) => e.key === 'Escape' && setShowNotif(false)}
                  className="flex size-10 items-center justify-center rounded-xl border border-line/70 bg-card/70 text-mutedink hover:border-brand/45 hover:text-ink transition-all"
                  aria-label={t('notif.open')}
                  aria-expanded={showNotif}
                  aria-haspopup="menu"
                >
                  <Bell size={18} aria-hidden />
                  {unread > 0 && (
                    <span className="absolute end-1.5 top-1.5 flex size-4 items-center justify-center rounded-full bg-loss text-[10px] font-bold text-white shadow-sm">
                      {unread}
                    </span>
                  )}
                </button>
                {showNotif && (
                  <div
                    role="menu"
                    aria-label={t('notif.title')}
                    className="glass-card absolute end-0 top-12 max-h-96 w-80 overflow-y-auto rounded-xl2 border border-line p-2.5 shadow-2xl animate-fade-in-up"
                  >
                    <div className="flex items-center justify-between px-2 py-1.5 border-b border-line mb-1">
                      <p className="text-sm font-bold">{t('notif.title')}</p>
                      {unread > 0 && (
                        <button
                          type="button"
                          onClick={() => setNotifs((ns) => ns.map((n) => ({ ...n, read: true })))}
                          className="rounded-lg px-2 py-1 text-[12px] font-semibold text-brand hover:underline"
                        >
                          {t('notif.markRead')}
                        </button>
                      )}
                    </div>
                    {notifs.length === 0 ? (
                      <p className="px-2 py-6 text-center text-sm text-mutedink">{t('notif.empty')}</p>
                    ) : (
                      notifs.map((n) => (
                        <button
                          key={n.id}
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setNotifs((ns) => ns.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
                            setShowNotif(false);
                          }}
                          className={`block w-full rounded-xl p-2.5 text-start transition-colors hover:bg-surface ${
                            n.read ? '' : 'bg-brand/10'
                          }`}
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold">
                            {!n.read && <span aria-hidden className="size-2 shrink-0 rounded-full bg-brand" />}
                            {t(n.titleKey)}
                          </span>
                          <span className="block text-xs text-mutedink mt-0.5">{t(n.bodyKey)}</span>
                        </button>
                      ))
                    )}
                    <button
                      type="button"
                      onClick={() => setShowNotif(false)}
                      className="mt-1 min-h-[36px] w-full rounded-xl text-xs font-semibold text-mutedink hover:bg-surface"
                    >
                      {t('notif.close')}
                    </button>
                  </div>
                )}
              </div>

              {/* Account Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowAccount((v) => !v)}
                  onKeyDown={(e) => e.key === 'Escape' && setShowAccount(false)}
                  aria-expanded={showAccount}
                  aria-haspopup="menu"
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-line/80 bg-card/80 px-2.5 py-1 text-sm font-semibold hover:border-brand/45 hover:bg-card transition-all"
                >
                  <div className="brand-gradient flex size-6 items-center justify-center rounded-lg text-white text-xs font-bold">
                    {user?.name ? user.name[0].toUpperCase() : 'U'}
                  </div>
                  <span className="hidden max-w-[120px] truncate text-xs font-semibold sm:inline">{user?.name}</span>
                  <ChevronDown size={14} aria-hidden className="text-mutedink" />
                </button>
                {showAccount && (
                  <div
                    role="menu"
                    className="glass-card absolute end-0 top-12 z-40 w-56 rounded-xl2 border border-line p-2 shadow-2xl animate-fade-in-up"
                  >
                    <div className="px-3 py-2 border-b border-line mb-1">
                      <p className="text-xs font-bold text-ink truncate">{user?.name}</p>
                      <p className="text-[11px] text-mutedink truncate">{user?.email}</p>
                    </div>
                    {accountItems.map((l) => renderItem(l, () => setShowAccount(false)))}
                    <div className="my-1 border-t border-line" />
                    <button
                      type="button"
                      onClick={() => {
                        logout();
                        navigate('/login');
                      }}
                      className="flex min-h-[40px] w-full items-center gap-2.5 rounded-xl px-3 text-xs font-semibold text-loss hover:bg-loss-bg transition-colors"
                    >
                      <LogOut size={16} aria-hidden />
                      <span>{t('nav.logout')}</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Secondary Ticker Tape Asset Bar */}
          <TickerTape />
        </header>

        {/* Main Content Area */}
        <div className="mx-auto max-w-shell px-4 sm:px-6 py-6 flex-1 w-full">
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- skip-link target must be focusable */}
          <main id="main" className="min-w-0" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>

      {/* Mobile Drawer */}
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label={t('a11y.close')}
            onClick={() => setDrawer(false)}
            className="absolute inset-0 cursor-default bg-black/65 backdrop-blur-md transition-opacity"
          />
          <div
            className="glass-card absolute inset-y-0 start-0 w-72 overflow-y-auto border-e border-line p-4 shadow-2xl animate-fade-in-up"
            role="dialog"
            aria-modal="true"
            aria-label={t('a11y.menu')}
          >
            <div className="mb-4 flex items-center justify-between border-b border-line pb-3">
              <span className="flex items-center gap-2.5 font-extrabold text-base">
                <span
                  aria-hidden
                  className="brand-gradient flex size-8 items-center justify-center rounded-xl text-xs font-black text-white"
                >
                  B
                </span>
                {APP_NAME}
              </span>
              <button
                onClick={() => setDrawer(false)}
                className="flex size-10 items-center justify-center rounded-xl text-mutedink hover:bg-surface hover:text-ink"
                aria-label={t('a11y.close')}
              >
                <X size={20} aria-hidden />
              </button>
            </div>
            <nav className="flex flex-col gap-1">
              <button
                type="button"
                onClick={() => {
                  setDrawer(false);
                  setCmdOpen(true);
                }}
                className="flex min-h-[44px] items-center gap-3 rounded-xl border border-line bg-surface/70 px-3 text-sm text-mutedink hover:text-ink mb-2"
              >
                <Search size={16} aria-hidden className="text-brand" />
                <span>{t('common.quickSearch')}</span>
              </button>

              {primary.map((l) => renderItem(l, () => setDrawer(false)))}
              {groups.map((g) => (
                <div key={g.label}>
                  <p className="px-3 pb-1 pt-3 text-[11px] font-bold uppercase tracking-wider text-mutedink">
                    {g.label}
                  </p>
                  {g.items.map((l) => renderItem(l, () => setDrawer(false)))}
                </div>
              ))}
              {renderItem(resultsItem, () => setDrawer(false))}
              <p className="px-3 pb-1 pt-3 text-[11px] font-bold uppercase tracking-wider text-mutedink">
                {t('nav.account')}
              </p>
              {accountItems.map((l) => renderItem(l, () => setDrawer(false)))}
              <div className="my-2 border-t border-line" />
              <button
                type="button"
                onClick={() => {
                  logout();
                  navigate('/login');
                }}
                className="flex min-h-[44px] w-full items-center gap-3 rounded-xl px-3 text-[14px] font-semibold text-loss hover:bg-loss-bg transition-colors"
              >
                <LogOut size={18} aria-hidden />
                <span>{t('nav.logout')}</span>
              </button>
            </nav>
          </div>
        </div>
      )}

      {/* Global Quick Search Modal */}
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />

      {/* Floating Back To Top */}
      <BackToTop />
    </div>
  );
}
