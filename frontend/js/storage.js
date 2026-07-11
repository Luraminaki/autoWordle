// localStorage wrapper for the one active session's identity and small
// standalone UI preferences.

import { KeyboardLayout } from './keyboard.js';

const KEY = 'autowordle.session';
const LAYOUT_KEY = 'autowordle.keyboardLayout';
const THEME_KEY = 'autowordle.theme';

export const ThemePreference = { AUTO: 'auto', LIGHT: 'light', DARK: 'dark' };

export function loadSession() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// localStorage can throw (private-browsing quirks, quota exceeded, storage
// disabled by policy/extension) - none of that should crash whatever flow
// triggered the write, it just means the preference/session won't persist.
function trySet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // best-effort - persistence is a nice-to-have, not a requirement to function
  }
}

export function saveSession(session) {
  trySet(KEY, JSON.stringify(session));
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // best-effort, see trySet
  }
}

export function getKeyboardLayout() {
  try {
    const stored = localStorage.getItem(LAYOUT_KEY);
    return Object.values(KeyboardLayout).includes(stored) ? stored : KeyboardLayout.QWERTY;
  } catch {
    return KeyboardLayout.QWERTY;
  }
}

export function setKeyboardLayout(layout) {
  trySet(LAYOUT_KEY, layout);
}

export function getThemePreference() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return Object.values(ThemePreference).includes(stored) ? stored : ThemePreference.AUTO;
  } catch {
    return ThemePreference.AUTO;
  }
}

export function setThemePreference(preference) {
  trySet(THEME_KEY, preference);
}
