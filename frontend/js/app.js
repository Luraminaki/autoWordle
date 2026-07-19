// Entry point: resume-vs-setup routing, mounts whichever screen applies.

import { mountSetup, refreshSetup } from './setup.js';
import { mountGame, showGame } from './game.js';
import { mountSolve, showSolve } from './solve.js';
import { getGameSessionStats, ApiError } from './api.js';
import { GameMode } from './statics.js';
import { loadSession, clearSession, getThemePreference } from './storage.js';
import { showToast } from './toast.js';
import { applyTheme, themeLabel, cycleTheme } from './theme.js';
import { initHelp } from './help.js';

const screens = {
  setup: document.getElementById('screen-setup'),
  game: document.getElementById('screen-game'),
  solve: document.getElementById('screen-solve'),
};

const themeToggle = document.getElementById('theme-toggle');

function initTheme() {
  const preference = getThemePreference();
  applyTheme(preference);
  themeToggle.textContent = themeLabel(preference);

  themeToggle.addEventListener('click', () => {
    themeToggle.textContent = themeLabel(cycleTheme());
  });
}

function showScreen(name) {
  for (const [key, el] of Object.entries(screens)) {
    el.hidden = key !== name;
  }
}

async function goToSetup() {
  showScreen('setup');
  await refreshSetup();
}

async function enterGame() {
  const stored = loadSession();
  if (!stored) {
    await goToSetup();
    return;
  }

  let response;
  try {
    response = await getGameSessionStats(stored.session_uuid);
  } catch (err) {
    if (err instanceof ApiError) {
      // The backend was reached and it says this session is gone (expired,
      // garbage-collected, deleted elsewhere) - the stored pointer is truly
      // stale, so discard it.
      clearSession();
    } else {
      // Network/timeout/HTTP failure: the session might still be perfectly
      // valid server-side, it's just unreachable right now. Don't destroy
      // the only reference to it - fall back to setup, but a reload can
      // still resume it once connectivity is back.
      showToast(`Could not reach the server (${err.message}). Reload to retry resuming your game.`);
    }
    await goToSetup();
    return;
  }

  const stats = response.session_stats;
  if (stats.game_mode === GameMode.SOLVE) {
    showScreen('solve');
    showSolve(stored, stats);
  } else {
    showScreen('game');
    await showGame(stored, stats);
  }
}

initTheme();
initHelp();

mountSetup(enterGame);
mountGame({ onExit: goToSetup });
mountSolve({ onExit: goToSetup });

enterGame();
