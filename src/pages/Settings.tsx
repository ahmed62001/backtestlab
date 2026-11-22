import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button, Card, ErrorState, Input, Modal } from '../components/ui';
import { SetPrefs, SetPw } from './SettingsParts';
import { apiDeleteAccount, apiUpdateMe } from '../api';
import { mapApiError } from '../lib/authErrors';
import { useAuth } from '../stores/auth';

export function Settings() {
  const { t } = useTranslation();
  const user = useAuth((s) => s.user);
  const updateUser = useAuth((s) => s.updateUser);
  const logout = useAuth((s) => s.logout);
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [showDel, setShowDel] = useState(false);
  const [phrase, setPhrase] = useState('');
  const [delBusy, setDelBusy] = useState(false);
  useEffect(() => {
    if (user) setName(user.name);
  }, [user]);
  if (!user) return <ErrorState />;
  const need = t('settings.deleteConfirm');
  // Account deletion is a real `DELETE /api/v1/auth/me` call. The session is
  // cleared only after the server confirms `{ok:true}`; a failure keeps the
  // user signed in and shows the error so they can retry.
  const confirmDeleteAccount = async () => {
    if (phrase.trim() !== need || delBusy) return;
    setDelBusy(true);
    setErr('');
    try {
      const res = await apiDeleteAccount();
      if (res?.ok !== true) throw { code: 'request_failed' };
      setShowDel(false);
      logout();
      navigate('/register');
    } catch (e) {
      setErr(mapApiError(e, t));
      setDelBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-2xl font-bold">{t('settings.title')}</h1>
      {msg && (
        <p role="status" className="rounded-xl2 border border-gain/30 bg-gain-bg p-3 text-sm font-medium text-gain">
          {msg}
        </p>
      )}
      {err && (
        <p role="alert" className="rounded-xl2 border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
          {err}
        </p>
      )}
      <Card>
        <h2 className="mb-3 text-base font-semibold">{t('settings.profile')}</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t('settings.name')} id="set-name" value={name} onChange={(e) => setName(e.target.value)} />
          <Input label={t('settings.email')} id="set-email" value={user.email} disabled dir="ltr" />
        </div>
        <div className="mt-3">
          <Button
            onClick={async () => {
              if (name.trim().length < 2) {
                setErr(t('auth.errors.invalidName'));
                return;
              }
              setErr('');
              try {
                // Persist server-side; never overwrite the session token.
                const updated = await apiUpdateMe(name.trim());
                updateUser(updated);
                setMsg(t('settings.saved'));
              } catch {
                setErr(t('auth.errors.unknown'));
              }
            }}
          >
            {t('settings.save')}
          </Button>
        </div>
      </Card>
      <SetPrefs />
      <SetPw onDone={(m) => setMsg(m)} onErr={(m) => setErr(m)} />
      <Card>
        <h2 className="mb-3 text-base font-semibold">{t('settings.exportData')}</h2>
        <Button
          variant="secondary"
          onClick={() => {
            const blob = new Blob([JSON.stringify({ user, exportedAt: new Date().toISOString() }, null, 2)], {
              type: 'application/json',
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'backtestlab-data.json';
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            setMsg(t('settings.exported'));
          }}
        >
          {t('settings.exportData')}
        </Button>
      </Card>
      <Card>
        <h2 className="mb-1 text-base font-semibold text-loss">{t('settings.deleteAccount')}</h2>
        <p className="mb-3 text-sm text-mutedink">{t('settings.deleteWarn')}</p>
        <Button variant="destructive" onClick={() => setShowDel(true)}>
          {t('settings.deleteAccount')}
        </Button>
      </Card>
      <Modal open={showDel} onClose={() => setShowDel(false)} title={t('settings.deleteAccount')}>
        <p className="mb-2 text-sm text-mutedink">{t('settings.deleteWarn')}</p>
        <label htmlFor="del-phrase" className="mb-1 block text-sm font-medium">
          {t('settings.deletePhrase')}
        </label>
        <input
          id="del-phrase"
          dir="ltr"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          placeholder={need}
          className="mb-4 min-h-[44px] w-full rounded-lg border border-line bg-card px-3 py-2"
        />
        <div className="flex gap-3">
          <Button
            variant="destructive"
            disabled={phrase.trim() !== need || delBusy}
            loading={delBusy}
            onClick={confirmDeleteAccount}
          >
            {t('common.confirm')}
          </Button>
          <Button variant="secondary" onClick={() => setShowDel(false)} disabled={delBusy}>
            {t('common.cancel')}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
