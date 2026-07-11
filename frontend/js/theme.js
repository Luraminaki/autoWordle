// Applies/cycles the manual color theme override (light/dark/auto), stacked
// on top of style.css's `@media (prefers-color-scheme: dark)` fallback.

import { ThemePreference, getThemePreference, setThemePreference } from './storage.js';

const CYCLE = [ThemePreference.AUTO, ThemePreference.LIGHT, ThemePreference.DARK];

export function applyTheme(preference) {
  if (preference === ThemePreference.AUTO) {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = preference;
  }
}

export function themeLabel(preference) {
  return `Theme: ${preference[0].toUpperCase()}${preference.slice(1)}`;
}

export function cycleTheme() {
  const next = CYCLE[(CYCLE.indexOf(getThemePreference()) + 1) % CYCLE.length];
  setThemePreference(next);
  applyTheme(next);
  return next;
}
