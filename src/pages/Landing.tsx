import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  FlaskConical,
  GitCompareArrows,
  Languages,
  Layers,
  LineChart,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { Card, Faq, RiskBanner } from '../components/ui';
import { PublicMarketChart } from '../components/market/PublicMarketChart';
import { APP_NAME, USE_MOCK } from '../lib/constants';

export function Landing() {
  const { t } = useTranslation();

  const how = [
    {
      step: '01',
      t: t('landing.how1t'),
      b: t('landing.how1b'),
      icon: Layers,
    },
    {
      step: '02',
      t: t('landing.how2t'),
      b: t('landing.how2b'),
      icon: Cpu,
    },
    {
      step: '03',
      t: t('landing.how3t'),
      b: t('landing.how3b'),
      icon: LineChart,
    },
  ];

  const feats = [
    {
      icon: FlaskConical,
      t: t('landing.f1t'),
      b: t('landing.f1b'),
      tag: 'Zero Lookahead',
    },
    {
      icon: ShieldCheck,
      t: t('landing.f2t'),
      b: t('landing.f2b'),
      tag: 'Risk Telemetry',
    },
    {
      icon: GitCompareArrows,
      t: t('landing.f3t'),
      b: t('landing.f3b'),
      tag: 'Multi-Asset Routing',
    },
    {
      icon: Languages,
      t: t('landing.f4t'),
      b: t('landing.f4b'),
      tag: 'Bilingual RTL/LTR',
    },
  ];

  const telemetryBadges = [
    { label: '12 Asset Classes', detail: 'Crypto, Metals, FX, Equities, Energy' },
    { label: 'Deterministic Engine', detail: 'Zero lookahead bias guaranteed' },
    { label: 'Sub-ms Execution', detail: 'Optimized vector backtesting' },
    { label: 'Institutional Metrics', detail: 'Sharpe, Sortino, Calmar, HHI' },
  ];

  const faq = [1, 2, 3, 4].map((n) => ({ q: t(`landing.faq${n}q`), a: t(`landing.faq${n}a`) }));

  return (
    <div className="mx-auto flex max-w-shell flex-col gap-16 px-4 py-10 sm:py-20 sm:px-6">
      {/* Hero Section */}
      <section className="grid items-center gap-12 lg:grid-cols-12" aria-labelledby="landing-hero">
        <div className="flex min-w-0 flex-col items-start gap-6 lg:col-span-6 animate-fade-in-up">
          {/* Eyebrow Pill */}
          <div className="inline-flex items-center gap-2 rounded-full border border-brand/30 bg-card/85 px-4 py-1.5 text-xs font-semibold text-ink shadow-bento backdrop-blur-md">
            <span className="size-2 rounded-full bg-gain animate-pulse" />
            <span className="text-mutedink font-medium">Quantitative Terminal v2.4</span>
            <span className="text-line">|</span>
            <span className="text-brand font-bold">Live Market Pipeline</span>
          </div>

          <h1
            id="landing-hero"
            className="text-gradient-brand text-3xl font-black leading-[1.12] tracking-tight sm:text-5xl lg:text-[3.35rem]"
          >
            {t('landing.heroTitle')}
          </h1>

          <p className="max-w-xl text-base text-mutedink leading-relaxed sm:text-lg">
            {t('landing.heroSub')}
          </p>

          {/* Action Triggers */}
          <div className="flex flex-wrap items-center gap-3.5 pt-1">
            <Link
              to="/register"
              className="brand-gradient inline-flex min-h-[48px] items-center gap-2 rounded-xl px-7 py-3 text-base font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all"
            >
              <span>{t('landing.ctaStart')}</span>
              <ArrowRight size={17} aria-hidden className="rtl:rotate-180" />
            </Link>
            <Link
              to="/pricing"
              className="inline-flex min-h-[48px] items-center rounded-xl border border-line bg-card/90 px-6 py-3 text-base font-semibold text-ink hover:bg-surface hover:border-brand/45 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all shadow-bento"
            >
              {t('landing.ctaPricing')}
            </Link>
          </div>

          {/* Bento Telemetry Chips */}
          <div className="grid grid-cols-1 gap-3 pt-2 sm:grid-cols-2 w-full">
            {telemetryBadges.map((badge) => (
              <div
                key={badge.label}
                className="bento-card flex flex-col gap-0.5 rounded-xl2 border border-line/80 p-3.5 backdrop-blur-sm transition-colors hover:border-brand/40"
              >
                <span className="text-xs font-bold text-ink">{badge.label}</span>
                <span className="text-[11px] text-mutedink leading-snug">{badge.detail}</span>
              </div>
            ))}
          </div>

          <p className="text-xs text-mutedink" dir={USE_MOCK ? 'ltr' : undefined}>
            <bdi>{USE_MOCK ? t('landing.demoNote') : t('landing.prodNote')}</bdi>
          </p>
        </div>

        {/* Terminal Frame with Live Chart */}
        <div className="min-w-0 lg:col-span-6">
          <div className="hero-mesh-card accent-top-line overflow-hidden rounded-xl3 border border-brand/35 transition-all duration-300 hover:border-brand/60">
            {/* Terminal Window Header */}
            <div className="flex h-11 items-center justify-between border-b border-line/80 bg-surface/65 px-4 text-xs backdrop-blur-sm">
              <div className="flex items-center gap-2">
                <span className="size-2.5 rounded-full bg-loss/85" />
                <span className="size-2.5 rounded-full bg-warn/85" />
                <span className="size-2.5 rounded-full bg-gain/85" />
                <span className="ms-2 font-mono text-[11px] text-mutedink">
                  {APP_NAME.toLowerCase()}-telemetry ~ public-stream
                </span>
              </div>
              <div className="flex items-center gap-2 rounded-full border border-gain/30 bg-gain-bg px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-gain">
                <span className="size-1.5 rounded-full bg-gain animate-ping" />
                <span>CONNECTED</span>
              </div>
            </div>

            <div className="p-3.5 sm:p-5">
              <PublicMarketChart />
            </div>
          </div>
        </div>
      </section>

      {/* Staged Quantitative Workflow */}
      <section aria-labelledby="landing-how" className="pt-6">
        <div className="mb-8 flex flex-col items-start gap-2">
          <span className="text-xs font-bold tracking-wider uppercase text-brand">System Architecture</span>
          <h2 id="landing-how" className="text-2xl font-bold tracking-tight sm:text-3xl text-ink">
            {t('landing.howTitle')}
          </h2>
        </div>

        <ol className="grid gap-6 md:grid-cols-3">
          {how.map((h) => (
            <li key={h.t}>
              <Card interactive className="relative h-full flex flex-col justify-between">
                <div>
                  <div className="mb-4 flex items-center justify-between">
                    <div className="flex size-10 items-center justify-center rounded-lg bg-brand/10 text-brand">
                      <h.icon size={20} aria-hidden />
                    </div>
                    <span className="fin font-mono text-xl font-bold text-mutedink/60">{h.step}</span>
                  </div>
                  <h3 className="mb-2 text-base font-bold text-ink">{h.t}</h3>
                  <p className="text-sm text-mutedink leading-relaxed">{h.b}</p>
                </div>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      {/* Engine Capabilities */}
      <section aria-labelledby="landing-feat" className="pt-4">
        <div className="mb-8 flex flex-col items-start gap-2">
          <span className="text-xs font-bold tracking-wider uppercase text-brand">Quant Capabilities</span>
          <h2 id="landing-feat" className="text-2xl font-bold tracking-tight sm:text-3xl text-ink">
            {t('landing.featuresTitle')}
          </h2>
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          {feats.map((f) => (
            <Card key={f.t} interactive className="flex flex-col justify-between">
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex size-10 items-center justify-center rounded-lg bg-brand/10 text-brand">
                    <f.icon size={20} aria-hidden />
                  </div>
                  <span className="rounded-full border border-line bg-bg px-2.5 py-0.5 text-[11px] font-semibold text-mutedink">
                    {f.tag}
                  </span>
                </div>
                <h3 className="mb-2 text-lg font-bold text-ink">{f.t}</h3>
                <p className="text-sm text-mutedink leading-relaxed">{f.b}</p>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Target Audience Contrast (Who It's Built For) */}
      <section aria-labelledby="landing-for" className="pt-4">
        <div className="mb-8 flex flex-col items-start gap-2">
          <span className="text-xs font-bold tracking-wider uppercase text-brand">Trader Alignment</span>
          <h2 id="landing-for" className="text-2xl font-bold tracking-tight sm:text-3xl text-ink">
            {t('landing.forTitle')}
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Card className="border-gain/40 bg-gain-bg/20">
            <div className="mb-4 flex items-center gap-2.5">
              <CheckCircle2 size={22} className="text-gain shrink-0" aria-hidden />
              <h3 className="text-lg font-bold text-gain">{t('landing.forYesT')}</h3>
            </div>
            <ul className="flex flex-col gap-3 text-sm text-ink/90 leading-relaxed">
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-gain mt-2 shrink-0" />
                <span>{t('landing.forYes1')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-gain mt-2 shrink-0" />
                <span>{t('landing.forYes2')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-gain mt-2 shrink-0" />
                <span>{t('landing.forYes3')}</span>
              </li>
            </ul>
          </Card>

          <Card className="border-loss/40 bg-loss-bg/20">
            <div className="mb-4 flex items-center gap-2.5">
              <XCircle size={22} className="text-loss shrink-0" aria-hidden />
              <h3 className="text-lg font-bold text-loss">{t('landing.forNoT')}</h3>
            </div>
            <ul className="flex flex-col gap-3 text-sm text-ink/90 leading-relaxed">
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-loss mt-2 shrink-0" />
                <span>{t('landing.forNo1')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-loss mt-2 shrink-0" />
                <span>{t('landing.forNo2')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="size-1.5 rounded-full bg-loss mt-2 shrink-0" />
                <span>{t('landing.forNo3')}</span>
              </li>
            </ul>
          </Card>
        </div>
      </section>

      {/* FAQ Section */}
      <section aria-labelledby="landing-faq" className="pt-4">
        <div className="mb-8 flex flex-col items-start gap-2">
          <span className="text-xs font-bold tracking-wider uppercase text-brand">Common Inquiries</span>
          <h2 id="landing-faq" className="text-2xl font-bold tracking-tight sm:text-3xl text-ink">
            {t('landing.faqTitle')}
          </h2>
        </div>
        <Faq items={faq} />
      </section>

      {/* Risk Transparency Notice */}
      <RiskBanner />

      {/* Final Call to Action */}
      <section
        aria-labelledby="landing-final"
        className="hero-mesh-card relative overflow-hidden rounded-xl3 border border-brand/35 p-8 sm:p-16 text-center"
      >
        <div className="relative z-10 mx-auto max-w-2xl flex flex-col items-center gap-5">
          <span className="rounded-full border border-brand/30 bg-brand/10 px-4 py-1 text-xs font-bold uppercase tracking-widest text-brand">
            Ready to Validate
          </span>
          <h2 id="landing-final" className="text-3xl font-extrabold tracking-tight sm:text-4xl text-ink">
            {t('landing.finalTitle')}
          </h2>
          <p className="text-base text-mutedink max-w-lg leading-relaxed">
            {t('landing.finalSub')}
          </p>
          <div className="pt-2">
            <Link
              to="/register"
              className="brand-gradient inline-flex min-h-[50px] items-center gap-2 rounded-xl px-8 py-3.5 text-base font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] transition-all"
            >
              <span>{t('landing.finalCta')}</span>
              <ArrowRight size={18} aria-hidden className="rtl:rotate-180" />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
