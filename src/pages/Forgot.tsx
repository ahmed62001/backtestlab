import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Link, Navigate } from 'react-router-dom';
import { useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Button, Card, Input } from '../components/ui';
import { apiForgot } from '../api';
import { mapApiError } from '../lib/authErrors';
import { useAuth } from '../stores/auth';

const schema = z.object({ email: z.string().email() });

export function Forgot() {
  const { t } = useTranslation();
  const { user, ready } = useAuth();
  const [apiError, setApiError] = useState('');
  const [done, setDone] = useState(false);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });
  if (ready && user) return <Navigate to="/app" replace />;
  return (
    <div className="mx-auto flex max-w-shell flex-col items-center px-4 py-14 sm:py-20">
      <Card className="glass-card w-full max-w-md rounded-xl3 p-7 sm:p-8 animate-fade-in-up">
        <h1 className="mb-1.5 text-2xl font-extrabold tracking-tight">{t('auth.forgotTitle')}</h1>
        <p className="mb-6 text-sm text-mutedink">{t('auth.forgotBody')}</p>
        {done ? (
          <div className="flex flex-col gap-4" role="status">
            <p className="flex items-start gap-2 rounded-lg border border-gain/30 bg-gain-bg p-3 text-sm font-medium text-gain">
              <CheckCircle2 size={18} aria-hidden className="mt-0.5 shrink-0" />
              {t('auth.forgotSuccess')}
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
                await apiForgot(v);
                setDone(true);
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
            {apiError && (
              <p role="alert" className="rounded-lg border border-loss/30 bg-loss-bg p-3 text-sm font-medium text-loss">
                {apiError}
              </p>
            )}
            <Button type="submit" loading={formState.isSubmitting}>
              {t('auth.forgotSubmit')}
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
