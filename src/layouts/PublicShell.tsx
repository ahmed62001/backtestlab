import { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Globe, Menu, Moon, Sun, X } from 'lucide-react';
import { APP_NAME } from '../lib/constants';
import { usePrefs } from '../stores/prefs';
import { setLanguage } from '../i18n';
import { BackToTop, ScrollProgress } from '../components/ui';

export function PublicShell() {
  const { t } = useTranslation();
  const { theme, toggleTheme, lang, setLang } = usePrefs();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const switchLang = () => {
    const next = lang === 'ar' ? 'en' : 'ar';
    setLang(next);
    setLanguage(next);
  };

  const navLinks = [
    { to: '/', label: t('nav.overview', 'Overview') },
    { to: '/pricing', label: t('nav.pricing') },
  ];

  return (
    <div className="min-h-screen text-ink flex flex-col">
      <ScrollProgress />
      <header className="sticky top-0 z-40 border-b border-line/70 glass-header transition-all duration-200">
        <div className="mx-auto flex h-[68px] max-w-shell items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="flex size-10 items-center justify-center rounded-xl hover:bg-surface md:hidden"
              onClick={() => setMobileMenuOpen(true)}
              aria-label={t('a11y.menu', 'Menu')}
            >
              <Menu size={20} aria-hidden />
            </button>
            <Link to="/" className="group flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
              <span
                aria-hidden
                className="brand-gradient flex size-8 items-center justify-center rounded-xl text-xs font-black text-white shadow-glow transition-transform duration-200 group-hover:scale-105"
              >
                B
              </span>
              <span>{APP_NAME}</span>
              <span className="hidden rounded-full border border-brand/30 bg-brand/10 px-2.5 py-0.5 text-[10px] font-bold tracking-widest uppercase text-brand sm:inline-block">
                Quant Engine
              </span>
            </Link>
          </div>

          <nav
            className="hidden items-center gap-1 rounded-full border border-line/80 bg-card/70 p-1 shadow-bento md:flex"
            aria-label="public"
          >
            {navLinks.map((link) => {
              const active = location.pathname === link.to;
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  className={`relative flex min-h-[36px] items-center rounded-full px-4 text-[13px] font-semibold transition-all duration-200 ${
                    active
                      ? 'bg-brand text-white shadow-sm'
                      : 'text-mutedink hover:text-ink hover:bg-surface/80'
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2">
            <button
              onClick={switchLang}
              className="flex min-h-[40px] items-center gap-1.5 rounded-xl border border-transparent px-3 text-sm font-semibold text-mutedink hover:border-line hover:bg-card/80 hover:text-ink transition-all"
              aria-label={t('a11y.language')}
            >
              <Globe size={17} aria-hidden />
              <span>{lang === 'ar' ? 'EN' : 'عربي'}</span>
            </button>
            <button
              onClick={toggleTheme}
              className="flex size-10 items-center justify-center rounded-xl border border-line/70 bg-card/70 text-mutedink hover:border-brand/40 hover:text-brand transition-all"
              aria-label={t('a11y.theme')}
            >
              {theme === 'dark' ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
            </button>
            <Link
              to="/login"
              className="hidden min-h-[40px] items-center rounded-xl px-3.5 py-2 text-sm font-semibold text-mutedink hover:bg-surface hover:text-ink sm:inline-flex transition-colors"
            >
              {t('nav.login')}
            </Link>
            <Link
              to="/register"
              className="brand-gradient inline-flex min-h-[40px] items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all"
            >
              <span>{t('nav.register')}</span>
              <ArrowRight size={15} aria-hidden className="rtl:rotate-180" />
            </Link>
          </div>
        </div>
      </header>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label={t('a11y.close', 'Close')}
            onClick={() => setMobileMenuOpen(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
          />
          <div
            className="absolute inset-y-0 start-0 w-72 overflow-y-auto border-e border-line bg-card p-4 shadow-2xl animate-fade-in-up"
            role="dialog"
            aria-modal="true"
            aria-label={t('a11y.menu', 'Menu')}
          >
            <div className="mb-6 flex items-center justify-between border-b border-line pb-4">
              <span className="flex items-center gap-2 font-bold text-lg">
                <span aria-hidden className="inline-block size-2.5 rounded-full bg-gold" />
                {APP_NAME}
              </span>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="flex size-10 items-center justify-center rounded-lg text-mutedink hover:bg-bg hover:text-ink"
                aria-label={t('a11y.close', 'Close')}
              >
                <X size={20} aria-hidden />
              </button>
            </div>
            <nav className="flex flex-col gap-1.5">
              {navLinks.map((link) => (
                <Link
                  key={link.to}
                  to={link.to}
                  onClick={() => setMobileMenuOpen(false)}
                  className="flex min-h-[44px] items-center rounded-lg px-3 text-sm font-semibold text-ink hover:bg-bg"
                >
                  {link.label}
                </Link>
              ))}
              <div className="my-2 border-t border-line" />
              <Link
                to="/login"
                onClick={() => setMobileMenuOpen(false)}
                className="flex min-h-[44px] items-center rounded-lg px-3 text-sm font-semibold text-mutedink hover:bg-bg hover:text-ink"
              >
                {t('nav.login')}
              </Link>
              <Link
                to="/register"
                onClick={() => setMobileMenuOpen(false)}
                className="flex min-h-[44px] items-center justify-center rounded-lg bg-brand px-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-hover"
              >
                {t('nav.register')}
              </Link>
            </nav>
          </div>
        </div>
      )}

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line/80 bg-card/70 backdrop-blur-md mt-auto">
        <div className="mx-auto max-w-shell px-4 sm:px-6 py-14">
          <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4 pb-10 border-b border-line/70">
            <div>
              <div className="flex items-center gap-2.5 font-extrabold text-base text-ink mb-3">
                <span
                  aria-hidden
                  className="brand-gradient flex size-7 items-center justify-center rounded-lg text-[11px] font-black text-white"
                >
                  B
                </span>
                {APP_NAME}
              </div>
              <p className="text-sm text-mutedink leading-relaxed">
                Institutional-grade quantitative backtesting, market data integrity, and portfolio risk telemetry.
              </p>
            </div>

            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-mutedink mb-3">
                {t('nav.backtesting', 'Platform')}
              </h4>
              <ul className="flex flex-col gap-2 text-sm text-mutedink">
                <li>
                  <Link to="/pricing" className="hover:text-ink transition-colors">
                    {t('nav.pricing')}
                  </Link>
                </li>
                <li>
                  <Link to="/login" className="hover:text-ink transition-colors">
                    {t('nav.login')}
                  </Link>
                </li>
                <li>
                  <Link to="/register" className="hover:text-ink transition-colors">
                    {t('nav.register')}
                  </Link>
                </li>
              </ul>
            </div>

            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-mutedink mb-3">
                Compliance &amp; Legal
              </h4>
              <ul className="flex flex-col gap-2 text-sm text-mutedink">
                <li>
                  <Link to="/terms" className="hover:text-ink transition-colors">
                    {t('common.footerTerms')}
                  </Link>
                </li>
                <li>
                  <Link to="/privacy" className="hover:text-ink transition-colors">
                    {t('common.footerPrivacy')}
                  </Link>
                </li>
                <li>
                  <Link to="/risk" className="hover:text-ink transition-colors">
                    {t('common.footerRisk')}
                  </Link>
                </li>
              </ul>
            </div>

            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-mutedink mb-3">
                Market Data Status
              </h4>
              <div className="flex items-center gap-2 text-xs text-gain font-semibold">
                <span className="size-2 rounded-full bg-gain animate-pulse" />
                <span>12 Asset Classes Operational</span>
              </div>
              <p className="text-xs text-mutedink mt-2">
                Real-time WebSocket tick overlay &amp; historical OHLCV pipeline.
              </p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 text-xs text-mutedink">
            <p>&copy; {new Date().getFullYear()} {APP_NAME}. All rights reserved.</p>
            <p className="text-center sm:text-end max-w-xl">{t('disclaimer.historical')}</p>
          </div>
        </div>
      </footer>

      <BackToTop />
    </div>
  );
}
