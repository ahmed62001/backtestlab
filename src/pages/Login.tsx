import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { Button, Card, Input, PasswordInput } from '../components/ui';
import { apiLogin } from '../api';
import { mapApiError } from '../lib/authErrors';
import { useAuth } from '../stores/auth';

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

function destOf(search: string): string {
  const q = new URLSearchParams(search);
  const next = q.get('next') ?? q.get('redirect') ?? q.get('from');
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/app';
}

export function Login() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { user, ready } = useAuth();
  const setSession = useAuth((s) => s.setSession);
  const [apiError, setApiError] = useState('');
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });
  if (ready && user) return <Navigate to={destOf(location.search)} replace />;
  const dest = destOf(location.search);
  return (
    <div className="mx-auto flex max-w-shell flex-col items-center px-4 py-14 sm:py-20">
      <Card className="glass-card w-full max-w-md rounded-xl3 p-7 sm:p-8 animate-fade-in-up">
        <div className="mb-6 flex flex-col gap-1.5">
          <span
            aria-hidden
            className="brand-gradient mb-2 flex size-10 items-center justify-center rounded-xl text-sm font-black text-white shadow-glow"
          >
            B
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight">{t('auth.loginTitle')}</h1>
          <p className="text-sm text-mutedink">{t('app.tagline')}</p>
        </div>
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={handleSubmit(async (v) => {
            setApiError('');
            try {
              const s = await apiLogin(v);
              setSession(s.token, s.user, s.refresh_token);
              navigate(dest, { replace: true });
            } catch (e) {
              setApiError(mapApiError(e, t));
            }
          })}
        >
          <Input
            label={t('auth.email')}
            type="email"
            autoComplete="email"
            dir="ltr"
            error={formState.errors.email ? t('auth.errors.invalidEmail') : undefined}
            {...register('email')}
          />
          <PasswordInput
            label={t('auth.password')}
            autoComplete="current-password"
            error={formState.errors.password ? t('auth.errors.weakPassword') : undefined}
            {...register('password')}
          />
          <div className="flex items-center justify-between">
            <Link to="/forgot" className="text-sm font-semibold text-brand hover:underline">
              {t('auth.forgot')}
            </Link>
          </div>
          {apiError && (
            <p role="alert" className="rounded-lg border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
              {apiError}
            </p>
          )}
          <Button type="submit" loading={formState.isSubmitting}>
            {t('auth.submitLogin')}
          </Button>
          <p className="text-sm text-mutedink">
            {t('auth.noAccount')}{' '}
            <Link to="/register" className="font-semibold text-brand hover:underline">
              {t('nav.register')}
            </Link>
          </p>
        </form>
      </Card>
    </div>
  );
}

