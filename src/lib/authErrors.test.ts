import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { mapApiError, passwordStrength } from './authErrors';

const t: TFunction = ((key: string) => key) as unknown as TFunction;

describe('mapApiError', () => {
  it('maps known error codes to localized keys', () => {
    expect(mapApiError({ code: 'invalid_email' }, t)).toBe('auth.errors.invalidEmail');
    expect(mapApiError({ code: 'weak_password' }, t)).toBe('auth.errors.weakPassword');
    expect(mapApiError({ code: 'invalid_name' }, t)).toBe('auth.errors.invalidName');
    expect(mapApiError({ code: 'invalid_token' }, t)).toBe('auth.errors.invalidToken');
    expect(mapApiError({ code: 'limit' }, t)).toBe('run.errors.limitReached');
  });

  it('falls back to unknown for missing code or null input', () => {
    expect(mapApiError({ code: 'nope' }, t)).toBe('auth.errors.unknown');
    expect(mapApiError(null, t)).toBe('auth.errors.unknown');
    expect(mapApiError(undefined, t)).toBe('auth.errors.unknown');
    expect(mapApiError({}, t)).toBe('auth.errors.unknown');
  });

  it('prefers messageKey when code is not mapped', () => {
    expect(
      mapApiError({ code: 'unknown_code', messageKey: 'auth.errors.custom' }, t),
    ).toBe('auth.errors.custom');
  });
});

describe('passwordStrength', () => {
  it('weak: too short', () => {
    expect(passwordStrength('abc')).toBe('weak');
  });

  it('weak: 8 chars but only one character class', () => {
    expect(passwordStrength('abcdefgh')).toBe('weak');
  });

  it('medium: 8+ chars with multiple classes', () => {
    expect(passwordStrength('Abc12345')).toBe('medium');
    expect(passwordStrength('Password1')).toBe('medium');
  });

  it('strong: 12+ chars with 3+ classes', () => {
    expect(passwordStrength('Str0ng!Passw0rd')).toBe('strong');
    expect(passwordStrength('Longer12345!')).toBe('strong');
  });
});