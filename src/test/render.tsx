import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { ReactElement } from 'react';

// React 18 act() environment flag for tests.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Minimal render helper (no @testing-library dependency). */
export function render(element: ReactElement) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(element);
  });
  return {
    container,
    text: () => container.textContent ?? '',
    rerender: (next: ReactElement) => {
      act(() => {
        root.render(next);
      });
    },
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}
