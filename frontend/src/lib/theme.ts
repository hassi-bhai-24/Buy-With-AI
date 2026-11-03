/**
 * Light/dark theme state.
 *
 * The theme lives on `data-theme` on <html> (see index.css for the
 * token values, design system 03 §2.1). Dark is the default. The
 * choice persists in localStorage under "buywithai-theme"; on a first
 * visit with no stored value, the OS `prefers-color-scheme` is
 * honoured. Applied synchronously from main.tsx before first render
 * so the page does not flash the wrong theme.
 */

export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'buywithai-theme';

export function resolveInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // Storage unavailable (private mode, blocked): fall through.
  }
  if (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: light)').matches
  ) {
    return 'light';
  }
  return 'dark';
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage unavailable: the theme still applies for this visit.
  }
}

/** Resolve + apply the theme before first render; returns the theme. */
export function initTheme(): Theme {
  const theme = resolveInitialTheme();
  applyTheme(theme);
  return theme;
}

export function getCurrentTheme(): Theme {
  return document.documentElement.dataset.theme === 'light'
    ? 'light'
    : 'dark';
}

export function toggleThemeValue(theme: Theme): Theme {
  return theme === 'light' ? 'dark' : 'light';
}
