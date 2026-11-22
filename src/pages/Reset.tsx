import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Button, Card, Input, PasswordInput } from '../components/ui';
import { apiReset } from '../api';
import { mapApiError } from '../lib/authErrors';
import { useAuth } from '../stores/auth';

const schema = z
  .object({
    token: z.string().min(6),
    password: z.string().min(8),
    confirm: z.string().min(8),
  })
  .refine((v) => v.password === v.confirm, { path: ['confirm'] });

export function Reset() {
  const { t } = useTranslation();
  const { user, ready } = useAuth();
  const [params] = useSearchParams();
  const [apiError, setApiError] = useState('');
  const [done, setDone] = useState(false);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { token: params.get('token') ?? '' },
  });
  if (ready && user) return <Navigate to="/app" replace />;
  return (
    <div className="mx-auto flex max-w-shell flex-col items-center px-4 py-14 sm:py-20">
      <Card className="glass-card w-full max-w-md rounded-xl3 p-7 sm:p-8 animate-fade-in-up">
        <h1 className="mb-6 text-2xl font-extrabold tracking-tight">{t('auth.resetTitle')}</h1>
        {done ? (
          <div className="flex flex-col gap-4" role="status">
            <p className="flex items-start gap-2 rounded-lg border border-gain/30 bg-gain-bg p-3 text-sm font-medium text-gain">
              <CheckCircle2 size={18} aria-hidden className="mt-0.5 shrink-0" />
              {t('auth.resetSuccess')}
            </p>
            <Link to="/login" className="text-sm font-semibold text-brand hover:underline">
              {t('auth.backToLogin')}
            </Link>
          </div>
        ) : (
          <form
            className="flex flex-col gap-4"
            noValidate
            onSubmit={handleSubmit(async (v) => {
              setApiError('');
              try {
                await apiReset({ token: v.token.trim(), password: v.password });
                setDone(true);
              } catch (e) {
                setApiError(mapApiError(e, t));
              }
            })}
          >
            <Input
              label={t('auth.resetTokenLabel')}
              dir="ltr"
              autoComplete="one-time-code"
              error={formState.errors.token ? t('auth.resetTokenInvalid') : undefined}
              {...register('token')}
            />
            <PasswordInput
              label={t('auth.newPassword')}
              autoComplete="new-password"
              error={formState.errors.password ? t('auth.errors.weakPassword') : undefined}
              {...register('password')}
            />
            <PasswordInput
              label={t('auth.confirmPassword')}
              autoComplete="new-password"
              error={formState.errors.confirm ? t('auth.passwordsMismatch') : undefined}
              {...register('confirm')}
            />
            {apiError && (
              <p role="alert" className="rounded-lg border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
                {apiError}
              </p>
            )}
            <Button type="submit" loading={formState.isSubmitting}>
              {t('auth.resetSubmit')}
            </Button>
            <Link to="/login" className="text-sm font-semibold text-brand hover:underline">
              {t('auth.backToLogin')}
            </Link>
          </form>
        )}
      </Card>
    </div>
  );
}
