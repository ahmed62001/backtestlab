import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { Button, Card, Input, PasswordInput } from '../components/ui';
import { apiRegister } from '../api';
import { mapApiError, passwordStrength } from '../lib/authErrors';
import { useAuth } from '../stores/auth';

const schema = z
  .object({
    name: z.string().min(2),
    email: z.string().email(),
    password: z.string().min(8),
    terms: z.literal(true),
  })
  .strict();

export function Register() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, ready } = useAuth();
  const setSession = useAuth((s) => s.setSession);
  const [apiError, setApiError] = useState('');
  const { register, handleSubmit, watch, formState } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', email: '', password: '' },
  });
  const pw = watch('password') ?? '';
  const level = passwordStrength(pw);
  if (ready && user) return <Navigate to="/app" replace />;
  const hint =
    pw.length === 0
      ? undefined
      : level === 'strong'
        ? t('auth.strengthStrong')
        : level === 'medium'
          ? t('auth.strengthMedium')
          : t('auth.strengthWeak');
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
          <h1 className="text-2xl font-extrabold tracking-tight">{t('auth.registerTitle')}</h1>
          <p className="text-sm text-mutedink">{t('app.tagline')}</p>
        </div>
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={handleSubmit(async (v) => {
            setApiError('');
            try {
              const s = await apiRegister({ name: v.name, email: v.email, password: v.password });
              setSession(s.token, s.user, s.refresh_token);
              navigate('/app', { replace: true });
            } catch (e) {
              setApiError(mapApiError(e, t));
            }
          })}
        >
          <Input
            label={t('auth.name')}
            autoComplete="name"
            error={formState.errors.name ? t('auth.errors.invalidName') : undefined}
            {...register('name')}
          />
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
            autoComplete="new-password"
            hint={hint}
            error={formState.errors.password ? t('auth.errors.weakPassword') : undefined}
            {...register('password')}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="register-terms" className="flex cursor-pointer items-start gap-2 text-sm text-ink">
              <input
                id="register-terms"
                type="checkbox"
                className="mt-1 size-5 shrink-0 accent-[var(--primary)]"
                aria-invalid={Boolean(formState.errors.terms)}
                {...register('terms')}
              />
              <span>{t('auth.termsLabel')}</span>
            </label>
            {formState.errors.terms && (
              <p role="alert" className="text-[13px] font-medium text-loss">
                {t('auth.termsRequired')}
              </p>
            )}
          </div>
          {apiError && (
            <p role="alert" className="rounded-lg border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
              {apiError}
            </p>
          )}
          <Button type="submit" loading={formState.isSubmitting}>
            {t('auth.submitRegister')}
          </Button>
          <p className="text-sm text-mutedink">
            {t('auth.haveAccount')}{' '}
            <Link to="/login" className="font-semibold text-brand hover:underline">
              {t('nav.login')}
            </Link>
          </p>
        </form>
      </Card>
    </div>
  );
}

