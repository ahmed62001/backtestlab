import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  CreditCard,
  FlaskConical,
  GitCompareArrows,
  Globe,
  History,
  LayoutDashboard,
  LayoutTemplate,
  LineChart,
  Search,
  Settings,
  X,
} from 'lucide-react';
import { useMarketUniverse } from '../../hooks/useMarket';
import { instrumentLabel } from '../../lib/market';
import type { AppLang } from '../../lib/format';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language === 'ar' ? 'ar' : 'en') as AppLang;
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const universe = useMarketUniverse();

  useEffect(() => {
    if (open) {
      const timer = setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (open) onClose();
        else setQuery('');
      } else if (e.key === 'Escape' && open) {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const quickPages = useMemo(
    () => [
      { label: t('nav.overview'), to: '/app', icon: LayoutDashboard, category: 'Pages' },
      { label: t('nav.markets'), to: '/app/markets', icon: LineChart, category: 'Pages' },
      { label: t('nav.macro'), to: '/app/macro', icon: Globe, category: 'Pages' },
      { label: t('nav.newBacktest'), to: '/app/new', icon: FlaskConical, category: 'Pages' },
      { label: t('nav.strategies'), to: '/app/templates', icon: LayoutTemplate, category: 'Pages' },
      { label: t('nav.compare'), to: '/app/compare', icon: GitCompareArrows, category: 'Pages' },
      { label: t('nav.results'), to: '/app/history', icon: History, category: 'Pages' },
      { label: t('nav.settings'), to: '/app/settings', icon: Settings, category: 'Pages' },
      { label: t('nav.billing'), to: '/app/billing', icon: CreditCard, category: 'Pages' },
    ],
    [t],
  );

  const filteredAssets = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return universe.items.slice(0, 6);
    return universe.items
      .filter((item) => {
        const sym = item.symbol.toLowerCase();
        const display = item.display.toLowerCase();
        const label = instrumentLabel(item.symbol, lang).toLowerCase();
        return sym.includes(q) || display.includes(q) || label.includes(q);
      })
      .slice(0, 8);
  }, [query, universe.items, lang]);

  const filteredPages = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return quickPages.slice(0, 4);
    return quickPages.filter((p) => p.label.toLowerCase().includes(q));
  }, [query, quickPages]);

  const allItems = useMemo(() => {
    const list: Array<{ type: 'page' | 'asset'; id: string; label: string; sub?: string; to: string }> = [];
    filteredPages.forEach((p) => {
      list.push({ type: 'page', id: p.to, label: p.label, to: p.to });
    });
    filteredAssets.forEach((a) => {
      list.push({
        type: 'asset',
        id: a.symbol,
        label: a.symbol,
        sub: instrumentLabel(a.symbol, lang),
        to: `/app/asset/${encodeURIComponent(a.symbol)}`,
      });
    });
    return list;
  }, [filteredPages, filteredAssets, lang]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleSelect = (to: string) => {
    onClose();
    navigate(to);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((idx) => (idx + 1) % Math.max(1, allItems.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((idx) => (idx - 1 + allItems.length) % Math.max(1, allItems.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (allItems[selectedIndex]) {
        handleSelect(allItems[selectedIndex].to);
      }
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16 sm:pt-24">
      <button
        type="button"
        aria-label={t('common.cancel')}
        onClick={onClose}
        className="absolute inset-0 bg-black/65 backdrop-blur-md transition-opacity"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('common.quickSearch')}
        className="glass-card relative flex w-full max-w-xl flex-col overflow-hidden rounded-xl3 border border-line shadow-2xl animate-fade-in-up"
      >
        <div className="flex items-center gap-3 border-b border-line/80 px-5 py-3.5">
          <Search size={19} className="shrink-0 text-brand" aria-hidden />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('common.searchAssetsOrPages')}
            className="w-full bg-transparent text-base text-ink placeholder:text-mutedink focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-xl text-mutedink transition-colors hover:bg-surface hover:text-ink"
            aria-label={t('common.cancel')}
          >
            <X size={18} aria-hidden />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-2">
          {filteredPages.length > 0 && (
            <div className="mb-2">
              <p className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-mutedink">
                {t('nav.overview')} &amp; {t('nav.backtesting')}
              </p>
              <div className="flex flex-col gap-0.5">
                {filteredPages.map((page) => {
                  const itemIndex = allItems.findIndex((it) => it.id === page.to);
                  const isSelected = itemIndex === selectedIndex;
                  return (
                    <button
                      key={page.to}
                      type="button"
                      onClick={() => handleSelect(page.to)}
                      className={`flex min-h-[44px] w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition-colors ${
                        isSelected ? 'bg-brand/10 text-brand font-semibold' : 'text-ink hover:bg-bg'
                      }`}
                    >
                      <page.icon size={18} className="shrink-0 text-mutedink" aria-hidden />
                      <span>{page.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {filteredAssets.length > 0 && (
            <div>
              <p className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-mutedink">
                {t('nav.markets')} ({universe.items.length})
              </p>
              <div className="flex flex-col gap-0.5">
                {filteredAssets.map((asset) => {
                  const itemIndex = allItems.findIndex((it) => it.id === asset.symbol);
                  const isSelected = itemIndex === selectedIndex;
                  return (
                    <button
                      key={asset.symbol}
                      type="button"
                      onClick={() => handleSelect(`/app/asset/${encodeURIComponent(asset.symbol)}`)}
                      className={`flex min-h-[44px] w-full items-center justify-between rounded-lg px-3 py-2 text-start text-sm transition-colors ${
                        isSelected ? 'bg-brand/10 text-brand font-semibold' : 'text-ink hover:bg-bg'
                      }`}
                    >
                      <div className="flex items-center gap-2.5">
                        <LineChart size={16} className="shrink-0 text-mutedink" aria-hidden />
                        <span className="fin font-semibold">{asset.symbol}</span>
                        <span className="text-xs text-mutedink">{instrumentLabel(asset.symbol, lang)}</span>
                      </div>
                      <span className="rounded bg-bg px-1.5 py-0.5 text-[11px] uppercase tracking-wider text-mutedink">
                        {asset.assetClass}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {allItems.length === 0 && (
            <div className="py-8 text-center text-sm text-mutedink">
              {t('common.empty', 'No matching results')}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-line bg-bg/50 px-4 py-2 text-xs text-mutedink">
          <div className="flex items-center gap-2">
            <span>↑↓ {t('common.navigate', 'Navigate')}</span>
            <span>↵ {t('common.select', 'Select')}</span>
            <span>ESC {t('common.close', 'Close')}</span>
          </div>
          <span className="fin text-[11px]">{APP_NAME} Quick Finder</span>
        </div>
      </div>
    </div>
  );
}
const APP_NAME = 'BacktestLab';
