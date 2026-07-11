// Setup/lobby screen: language/length/mode pickers, precompute gating,
// session creation.

import { getVersion, getActiveGames, getAppSources, createGameSession, getGameSessionStats, ApiError } from './api.js';
import { runPrecompute } from './precompute.js';
import { GameMode, formatModeLabel } from './statics.js';
import { saveSession } from './storage.js';

const DEFAULT_MAX_TRIES = 6;

const el = {
  version: document.getElementById('meta-version'),
  activeGames: document.getElementById('meta-active-games'),
  lang: document.getElementById('setup-lang'),
  length: document.getElementById('setup-length'),
  mode: document.getElementById('setup-mode'),
  tries: document.getElementById('setup-tries'),
  start: document.getElementById('setup-start'),
  error: document.getElementById('setup-error'),
  precomputePanel: document.getElementById('precompute-panel'),
  precomputeStart: document.getElementById('precompute-start'),
  progressBar: document.getElementById('precompute-progress-bar'),
  progressFill: document.getElementById('precompute-progress-fill'),
  precomputeStatus: document.getElementById('precompute-status'),
  resumeUuid: document.getElementById('resume-uuid'),
  resumeStart: document.getElementById('resume-start'),
  resumeError: document.getElementById('resume-error'),
};

let appSources = null;
let onSessionCreated = null;

function availableLengths(lang) {
  const source = appSources.langs[lang];
  const lengths = new Set(appSources.config.default_word_lengths);
  for (const key of Object.keys(source.pre_computed)) lengths.add(Number(key));
  return [...lengths].sort((a, b) => a - b);
}

function isExhaustiveDataAvailable(lang, length) {
  return Boolean(appSources.langs[lang]?.pre_computed?.[String(length)]?.has_exhaustive_data);
}

function populateLangs() {
  el.lang.innerHTML = '';
  for (const lang of Object.keys(appSources.langs)) {
    const opt = document.createElement('option');
    opt.value = lang;
    opt.textContent = lang;
    el.lang.appendChild(opt);
  }
}

function populateLengths() {
  const lang = el.lang.value;
  const current = el.length.value;
  el.length.innerHTML = '';
  for (const length of availableLengths(lang)) {
    const opt = document.createElement('option');
    opt.value = String(length);
    opt.textContent = String(length);
    el.length.appendChild(opt);
  }
  if ([...el.length.options].some((o) => o.value === current)) el.length.value = current;
}

function populateModes() {
  el.mode.innerHTML = '';
  for (const value of Object.values(appSources.game_modes)) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = formatModeLabel(value);
    el.mode.appendChild(opt);
  }
}

function currentSelection() {
  return { lang: el.lang.value, length: el.length.value, mode: el.mode.value };
}

// Repopulating the selects (populateLangs/populateLengths/populateModes)
// always resets each one to its first option - without restoring the
// previous choice, finishing a precompute build silently swaps the user
// back to a different lang/length/mode than the one they just built data
// for, right as the availability gate re-evaluates.
function applySelection(selection) {
  if (!selection) return;

  if ([...el.lang.options].some((o) => o.value === selection.lang)) el.lang.value = selection.lang;
  populateLengths();
  if ([...el.length.options].some((o) => o.value === selection.length)) el.length.value = selection.length;
  if ([...el.mode.options].some((o) => o.value === selection.mode)) el.mode.value = selection.mode;
}

function updateAvailabilityGate() {
  const lang = el.lang.value;
  const length = Number(el.length.value);
  const mode = el.mode.value;

  el.error.hidden = true;
  resetPrecomputeUI();

  const needsExhaustiveData = mode !== GameMode.PLAY;
  const available = !needsExhaustiveData || isExhaustiveDataAvailable(lang, length);

  el.start.disabled = !available;
  el.precomputePanel.hidden = available;
}

function resetPrecomputeUI() {
  el.progressBar.hidden = true;
  el.progressFill.style.width = '0%';
  el.precomputeStatus.textContent = '';
}

async function refreshMeta() {
  try {
    const [version, activeGames] = await Promise.all([getVersion(), getActiveGames()]);
    el.version.textContent = version.version ? `v${version.version}` : '';
    el.activeGames.textContent = `${activeGames.active_games} active game(s)`;
  } catch {
    el.version.textContent = '';
    el.activeGames.textContent = '';
  }
}

export async function refreshSetup(preferredSelection) {
  el.error.hidden = true;

  // Deliberately not resetPrecomputeUI() here: updateAvailabilityGate() below
  // already calls it once this finishes. Doing it here too used to wipe a
  // just-finished build's "Done" status in the same synchronous tick it was
  // set (onDone -> refreshSetup happen back-to-back with no yield to the
  // event loop in between), so the message never had a chance to be seen.

  await refreshMeta();

  let response;
  try {
    response = await getAppSources();
  } catch (err) {
    el.error.textContent = err instanceof ApiError
      ? (err.message || 'Could not load available languages')
      : `Could not reach the autoWordle API at ${window.location.origin} (${err.message}). ` +
        'Is the app running, and are you loading this page through its server rather than opening the file directly?';
    el.error.hidden = false;
    return;
  }

  appSources = response.app_sources;
  el.tries.value = DEFAULT_MAX_TRIES;
  el.resumeUuid.value = '';
  el.resumeStart.disabled = false;
  el.resumeError.hidden = true;

  populateLangs();
  populateLengths();
  populateModes();
  applySelection(preferredSelection);
  updateAvailabilityGate();
}

async function resumeSession() {
  const uuid = el.resumeUuid.value.trim();
  el.resumeError.hidden = true;

  if (!uuid) {
    el.resumeError.textContent = 'Enter a session ID first';
    el.resumeError.hidden = false;
    return;
  }

  el.resumeStart.disabled = true;
  try {
    const response = await getGameSessionStats(uuid);
    const stats = response.session_stats;

    saveSession({
      session_uuid: uuid,
      lang: stats.lang,
      word_length: stats.word_length,
      game_mode: stats.game_mode,
      max_tries: stats.max_tries,
    });

    onSessionCreated();
  } catch (err) {
    // Either way (backend says unknown, or a network failure) it means the
    // same thing to the user here - the backend's own message for "session
    // not found" is a generic INTERNAL_ERROR, not worth surfacing verbatim.
    el.resumeError.textContent = err instanceof ApiError
      ? 'No session found with that ID - double check it and try again'
      : `Could not reach the server (${err.message})`;
    el.resumeError.hidden = false;
    el.resumeStart.disabled = false;
  }
}

export function mountSetup(callback) {
  onSessionCreated = callback;

  el.lang.addEventListener('change', () => {
    populateLengths();
    updateAvailabilityGate();
  });
  el.length.addEventListener('change', updateAvailabilityGate);
  el.mode.addEventListener('change', updateAvailabilityGate);

  el.start.addEventListener('click', async () => {
    el.error.hidden = true;
    el.start.disabled = true;

    try {
      const maxTries = Number(el.tries.value) || DEFAULT_MAX_TRIES;
      const response = await createGameSession(el.lang.value, Number(el.length.value), el.mode.value, maxTries);

      saveSession({
        session_uuid: response.session_uuid,
        lang: el.lang.value,
        word_length: Number(el.length.value),
        game_mode: el.mode.value,
        max_tries: maxTries,
      });

      onSessionCreated();
    } catch (err) {
      el.error.textContent = err.message;
      el.error.hidden = false;
      el.start.disabled = false;
    }
  });

  el.precomputeStart.addEventListener('click', () => {
    el.precomputeStart.disabled = true;
    runPrecompute(el.lang.value, Number(el.length.value), {
      barEl: el.progressBar,
      fillEl: el.progressFill,
      statusEl: el.precomputeStatus,
      onDone: async () => {
        el.precomputeStart.disabled = false;
        await refreshSetup(currentSelection());
      },
      onError: (message) => {
        el.precomputeStart.disabled = false;
        el.precomputeStatus.textContent = `Error: ${message}`;
      },
    });
  });

  el.resumeStart.addEventListener('click', resumeSession);
  el.resumeUuid.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') resumeSession();
  });
}
