import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Card, Faq, Input } from '../components/ui';

export function Help() {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [body, setBody] = useState('');
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState('');
  const allFaq = [1, 2, 3, 4].map((n) => ({ q: t(`landing.faq${n}q`), a: t(`landing.faq${n}a`) }));
  const faq = allFaq.filter((f) => (f.q + ' ' + f.a).toLowerCase().includes(q.toLowerCase()));
  const glossary = ['backtest', 'drawdown', 'sharpe', 'overfit', 'winrate', 'spot'].map((g) => ({
    t: t(`help.g_${g}_t`),
    b: t(`help.g_${g}_b`),
  }));
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('help.title')}</h1>
      <section aria-labelledby="help-faq">
        <h2 id="help-faq" className="mb-2 text-lg font-bold">
          {t('help.faqTitle')}
        </h2>
        <div className="mb-3">
          <Input label={t('common.search')} id="help-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('help.searchPh')} />
        </div>
        {faq.length === 0 ? <p className="text-sm text-mutedink">{t('help.emptyFaq')}</p> : <Faq items={faq} />}
      </section>
      <section aria-labelledby="help-gloss">
        <h2 id="help-gloss" className="mb-2 text-lg font-bold">
          {t('help.glossaryTitle')}
        </h2>
        <dl className="grid gap-3 sm:grid-cols-2">
          {glossary.map((g) => (
            <Card key={g.t}>
              <dt className="mb-1 font-semibold">{g.t}</dt>
              <dd className="text-sm text-mutedink">{g.b}</dd>
            </Card>
          ))}
        </dl>
      </section>
      <section aria-labelledby="help-contact">
        <h2 id="help-contact" className="mb-2 text-lg font-bold">
          {t('help.contactTitle')}
        </h2>
        <Card>
          <p className="mb-3 rounded-xl2 border border-warn/40 bg-warn-bg p-3 text-sm text-ink">
            {t('help.contactDemoNote')}
          </p>
          {sent ? (
            <p role="status" className="rounded-xl2 border border-line bg-bg p-3 text-sm text-mutedink">
              {t('help.contactUnavailable')}
            </p>
          ) : (
            <form
              className="flex flex-col gap-4"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim().length < 2 || !email.includes('@') || body.trim().length < 10) {
                  setErr(t('help.contactErr'));
                  return;
                }
                setErr('');
                setSent(true);
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Input label={t('help.contactName')} id="help-name" value={name} onChange={(e) => setName(e.target.value)} />
                <Input label={t('help.contactEmail')} id="help-email" type="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="help-msg" className="text-sm font-medium">
                  {t('help.contactMsg')}
                </label>
                <textarea
                  id="help-msg"
                  rows={4}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  className="rounded-lg border border-line bg-card px-3 py-2 text-ink"
                />
              </div>
              {err && (
                <p role="alert" className="text-[13px] font-medium text-loss">
                  {err}
                </p>
              )}
              <div>
                <Button type="submit">{t('help.contactSend')}</Button>
              </div>
            </form>
          )}
        </Card>
      </section>
    </div>
  );
}
