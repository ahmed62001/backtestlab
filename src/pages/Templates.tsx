import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Badge, Card, ErrorState, Skeleton } from '../components/ui';
import { apiGetTemplates } from '../api';
import { prefillFromTemplate } from '../stores/draft';
import type { StrategyTemplate } from '../types';

const HOW: Record<string, string> = {
  'ma-crossover': 'how-ma', 'rsi': 'how-rsi', 'breakout': 'how-bo', 'mean-reversion': 'how-mr', 'buy-hold': 'how-bh',
};

export function Templates() {
  const { t, i18n } = useTranslation();
  const [items, setItems] = useState<StrategyTemplate[] | null>(null);
  const [error, setError] = useState(false);
  const load = () => { setError(false); apiGetTemplates().then(setItems).catch(() => setError(true)); };
  useEffect(load, []);
  if (error) return <div className="flex flex-col gap-4"><h1 className="text-2xl font-bold">{t('templatesLib.title')}</h1><ErrorState onRetry={load} /></div>;
  if (!items) return <div className="flex flex-col gap-4"><h1 className="text-2xl font-bold">{t('templatesLib.title')}</h1><div className="grid gap-4 sm:grid-cols-2">{[0,1,2,3].map((i)=><Skeleton key={i} className="h-40"/>)}</div></div>;
  const howText = (id: string): string => {
    const en: Record<string,string> = {'how-ma':'Two averages: buy when the fast crosses above the slow, exit on cross down. Calm in trends, choppy sideways.','how-rsi':'RSI momentum 0-100: buy low readings, exit high ones. Simple mean-reversion on momentum.','how-bo':'Buys a close above the recent highest range plus a buffer. Catches momentum, whipsaws in ranges.','how-mr':'Bets stretched prices snap back to average using z-scores. Needs calm ranges.','how-bh':'Buys once and holds. The baseline every strategy is measured against.'};
    const ar: Record<string,string> = {'how-ma':'متوسطان: اشترِ عندما يتجاوز السريع البطيء واخرج عند التقاطع العكسي. هادئ في الاتجاهات ومتقلب عرضيًا.','how-rsi':'زخم RSI من 0-100: اشترِ القراءات المنخفضة واخرج عند المرتفعة. ارتداد متوسط بسيط على الزخم.','how-bo':'يشتري إغلاقًا فوق أعلى نطاق سابق زائد هامش. يلتقط الزخم ويتذبذب في النطاقات.','how-mr':'يراهن أن الأسعار الممتدة تعود للمتوسط باستخدام z-scores. يحتاج نطاقات هادئة.','how-bh':'يشتري مرة ويحتفظ. الأساس الذي تُقاس عليه كل استراتيجية.'};
    return (i18n.language === 'ar' ? ar : en)[HOW[id]] ?? '';
  };
  return (
    <div className="flex flex-col gap-5">
      <div className="bento-card rounded-xl2 border border-line/80 px-5 py-4">
        <h1 className="text-2xl font-extrabold tracking-tight">{t('templatesLib.title')}</h1>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {items.map((tp) => (
          <Card key={tp.id} interactive className="flex flex-col justify-between">
            <div>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold">{t(`templates.${tp.id}.name`)}</h2>
              </div>
              <p className="text-sm text-mutedink">{t(`templates.${tp.id}.desc`)}</p>
              <p className="mt-2.5 text-sm text-ink"><span className="font-semibold">{t('templatesLib.how')}: </span>{howText(tp.id)}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone="neutral">{t('templatesLib.difficulty')}: {t(`templatesLib.${tp.difficulty}`)}</Badge>
                <Badge tone={tp.riskLabel === 'lower' ? 'gain' : tp.riskLabel === 'higher' ? 'loss' : 'warn'}>{t('templatesLib.risk')}: {t(`templatesLib.${tp.riskLabel}`)}</Badge>
              </div>
            </div>
            <Link to={`/app/new?template=${tp.id}`} onClick={() => { const m: Record<string,number|string> = {}; tp.paramSpecs.forEach((p)=>{m[p.key]=p.default;}); prefillFromTemplate(tp.id, m); }}
              className="brand-gradient mt-4 inline-flex min-h-[42px] w-fit items-center rounded-xl px-5 py-2 text-sm font-semibold text-white shadow-sm hover:shadow-glow hover:-translate-y-0.5 transition-all">{t('templatesLib.use')}</Link>
          </Card>
        ))}
      </div>
    </div>
  );
}
