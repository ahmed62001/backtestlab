import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/500.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import '@fontsource/ibm-plex-sans-arabic/700.css';
import './i18n';
import './styles/globals.css';
import { router } from './router';
import { useAuth } from './stores/auth';
import { usePrefs, applyThemeClass } from './stores/prefs';
import { ErrorBoundary } from './components/ui/ErrorBoundary';

function Boot() {
  const init = useAuth((s) => s.init);
  const theme = usePrefs((s) => s.theme);
  React.useEffect(() => {
    init();
    applyThemeClass(usePrefs.getState().theme);
  }, [init]);
  React.useEffect(() => {
    applyThemeClass(theme);
  }, [theme]);
  return <RouterProvider router={router} />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <Boot />
    </ErrorBoundary>
  </React.StrictMode>,
);
