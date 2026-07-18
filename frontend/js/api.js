// Thin fetch wrappers for every autoWordle/webapp/api_views.py route.
// Every response has {status, error, ...}; this layer normalizes every way a
// call can fail (network/timeout, non-2xx HTTP, or a 200 OK that itself
// reports failure) into a single thrown error, so callers only ever need one
// try/catch instead of a catch block *plus* a separate `response.status`
// check. `ApiError` specifically marks "the backend was reached and it says
// this failed" - distinct from a network/timeout error - for callers that
// need to react differently to those two cases (see app.js's session-resume
// logic: a dead session should be discarded, a network blip shouldn't be).

import { StatusFunction } from './statics.js';

const BASE = '/api/app';

// get_guess_stats runs real entropy computation server-side and can take a
// couple of seconds on a large pool - generous enough to cover that without
// leaving the UI stuck indefinitely if the server hangs entirely.
const REQUEST_TIMEOUT_MS = 20000;

const OK_STATUSES = new Set([StatusFunction.SUCCESS, StatusFunction.DONE, StatusFunction.ONGOING]);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    if (err.name === 'TimeoutError') {
      throw new Error(`${method} ${path} timed out after ${REQUEST_TIMEOUT_MS / 1000}s`);
    }
    throw err;
  }

  if (!res.ok) {
    // Best-effort: FastAPI's default error shape is {detail: "..."} (e.g. a
    // 429 from the rate limiter, or a 422 validation error) - surface that
    // instead of a bare status code when it's there.
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      // body wasn't JSON (or was empty) - fall through to the generic message
    }
    throw new Error(detail || `${method} ${path} failed: HTTP ${res.status}`);
  }

  const data = await res.json();

  if (!OK_STATUSES.has(data.status)) {
    throw new ApiError(data.error || `${method} ${path} reported status ${data.status}`, data.status);
  }

  return data;
}

const get = (path) => request('GET', path);
const post = (path, body) => request('POST', path, body);

export const getVersion = () => get('/version');
export const getActiveGames = () => get('/get_active_games');
export const getAppSources = () => get('/get_app_sources');

export const createGameSession = (lang, wordLength, gameMode, maxTries) =>
  post('/create_game_session', { lang, word_length: wordLength, game_mode: gameMode, max_tries: maxTries });

export const resetGameSession = (sessionUuid, gameMode, maxTries) =>
  post('/reset_game_session', { session_uuid: sessionUuid, game_mode: gameMode, max_tries: maxTries });

export const deleteGameSession = (sessionUuid) =>
  post('/delete_game_session', { session_uuid: sessionUuid });

export const getGameSessionStats = (sessionUuid) =>
  post('/get_game_session_stats', { session_uuid: sessionUuid });

export const getWordToGuess = (sessionUuid) =>
  post('/get_word_to_guess', { session_uuid: sessionUuid });

export const getGuessStats = (sessionUuid, word, pattern) =>
  post('/get_guess_stats', { session_uuid: sessionUuid, word, pattern });

export const getInitialHints = (sessionUuid) =>
  post('/get_initial_hints', { session_uuid: sessionUuid });

export const submitGuess = (sessionUuid, word) =>
  post('/submit_guess', { session_uuid: sessionUuid, word });

export const requestPrecompute = (lang, wordLength) =>
  post('/precompute', { lang, word_length: wordLength });

export const precomputeProgressUrl = (lang, wordLength) =>
  `${BASE}/precompute_progress?lang=${encodeURIComponent(lang)}&word_length=${encodeURIComponent(wordLength)}`;
