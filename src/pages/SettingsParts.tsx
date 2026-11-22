import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Card, Input, Select } from '../components/ui';
import { setLanguage } from '../i18n';
import { apiChangePassword } from '../api';
import { usePrefs } from '../stores/prefs';

export function SetPrefs() {
  const { t } = useTranslation();
  const { theme, toggleTheme, lang, setLang } = usePrefs();
  return (
    <Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label={t('settings.language')}
          id="set-lang"
          value={lang}
          onChange={(e) => {
            const v = e.target.value as 'ar' | 'en';
            setLang(v);
            setLanguage(v);
          }}
          options={[
            { value: 'ar', label: 'العربية' },
            { value: 'en', label: 'English' },
          ]}
        />
        <Select
          label={t('settings.theme')}
          id="set-theme"
          value={theme}
          onChange={() => toggleTheme()}
          options={[
            { value: 'light', label: t('settings.light') },
            { value: 'dark', label: t('settings.dark') },
          ]}
        />
      </div>
    </Card>
  );
}

export function SetPw({ onDone, onErr }: { onDone: (m: string) => void; onErr: (m: string) => void }) {
  const { t } = useTranslation();
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  return (
    <Card>
      <h2 className="mb-3 text-base font-semibold">{t('settings.password')}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
          label={t('settings.currentPw')}
          id="set-cur"
          type="password"
          value={cur}
          onChange={(e) => setCur(e.target.value)}
          autoComplete="current-password"
        />
        <Input
          label={t('settings.newPw')}
          id="set-next"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
        />
      </div>
      <div className="mt-3">
        <Button
          variant="secondary"
          onClick={async () => {
            if (cur.length < 8 || next.length < 8) {
              onErr(t('auth.errors.weakPassword'));
              return;
            }
            onErr('');
            try {
              await apiChangePassword(cur, next);
              setCur('');
              setNext('');
              onDone(t('settings.saved'));
            } catch {
              onErr(t('auth.errors.unknown'));
            }
          }}
        >
          {t('common.save')}
        </Button>
      </div>
    </Card>
  );
}
