import type { TFunction } from 'i18next';

/** Map mock API error codes to localized messages (Group A: clear server-error mapping). */
const CODE_TO_KEY: Record<string, string> = {
  invalid_email: 'auth.errors.invalidEmail',
  weak_password: 'auth.errors.weakPassword',
  invalid_name: 'auth.errors.invalidName',
  invalid_token: 'auth.errors.invalidToken',
  limit: 'run.errors.limitReached',
  // Provider error codes (Phase 1)
  upstream_blocked: 'run.errors.upstreamBlocked',
  upstream_unavailable: 'run.errors.upstreamUnavailable',
  upstream_bad_response: 'run.errors.upstreamBadResponse',
  unknown_symbol: 'run.errors.unknownSymbol',
  provider_not_configured: 'run.errors.providerNotConfigured',
  rate_limited: 'run.errors.rateLimited',
  bad_input: 'run.errors.badInput',
  empty_data: 'run.errors.emptyData',
  provider_down: 'run.errors.providerDown',
  provider_timeout: 'run.errors.providerTimeout',
  data_not_in_store: 'run.errors.dataNotInStore',
};

export function mapApiError(e: unknown, t: TFunction): string {
  const err = e as { code?: string; messageKey?: string; provider?: string } | null;
  if (err?.code && CODE_TO_KEY[err.code]) {
    const key = CODE_TO_KEY[err.code];
    return err.provider ? t(key, { provider: err.provider }) : t(key);
  }
  if (err?.messageKey) return t(err.messageKey);
  return t('auth.errors.unknown');
}

/** Simple client-side strength level for the Register hint. */
export function passwordStrength(pw: string): 'weak' | 'medium' | 'strong' {
  if (pw.length < 8) return 'weak';
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^a-zA-Z0-9]/].filter((re) => re.test(pw)).length;
  if (pw.length >= 12 && classes >= 3) return 'strong';
  if (pw.length >= 10 || classes >= 2) return 'medium';
  return 'weak';
}
