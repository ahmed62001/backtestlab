import React from 'react';
import { useTranslation } from 'react-i18next';

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(): void {
    // Intentionally silent: no logging backend in Step 1.5.
  }

  render(): React.ReactNode {
    if (!this.state.hasError) return this.props.children;
    return <ErrorFallback onReset={() => this.setState({ hasError: false })} />;
  }
}

function ErrorFallback({ onReset }: { onReset: () => void }) {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-bg px-6 text-center text-ink">
      <p className="text-2xl font-bold">{t('common.errorTitle')}</p>
      <p className="max-w-md text-sm text-mutedink">{t('common.errorBody')}</p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="min-h-[44px] rounded-lg bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
        >
          {t('common.retry')}
        </button>
        <button
          type="button"
          onClick={onReset}
          className="min-h-[44px] rounded-lg border border-line bg-card px-5 py-2 text-sm font-semibold text-ink hover:bg-bg"
        >
          {t('common.cancel')}
        </button>
      </div>
    </main>
  );
}
