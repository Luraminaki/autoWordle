// Play/Assisted screen controller: wires board + keyboard [+ hints panel].

import { submitGuess, getWordToGuess, getGuessStats, getInitialHints, resetGameSession, deleteGameSession, ApiError } from './api.js';
import { createBoard } from './board.js';
import { createKeyboard, KeyboardLayout } from './keyboard.js';
import { renderHints } from './hints.js';
import { GameMode, isWinningPattern, emojiToStatus, formatModeLabel } from './statics.js';
import { saveSession, clearSession, getKeyboardLayout, setKeyboardLayout } from './storage.js';
import { showToast } from './toast.js';
import { copyToClipboard } from './clipboard.js';

const el = {
  badgeMode: document.getElementById('game-badge-mode'),
  badgeLang: document.getElementById('game-badge-lang'),
  badgeTries: document.getElementById('game-badge-tries'),
  reset: document.getElementById('game-reset'),
  newGame: document.getElementById('game-new'),
  keyboardToggle: document.getElementById('game-keyboard-layout'),
  sessionId: document.getElementById('game-session-id'),
  copySessionId: document.getElementById('game-copy-session-id'),
  banner: document.getElementById('game-banner'),
  board: document.getElementById('board'),
  keyboard: document.getElementById('keyboard'),
  hints: document.getElementById('hints-panel'),
};

let session = null;
let board = null;
let keyboard = null;
let finished = false;
let isSubmitting = false;
let currentTries = 0;
let onExit = null;
// Bumped by showGame() every time it (re)initializes the board/keyboard/
// session - handleEnter() captures the value in effect when it starts and
// re-checks it after every await, so a guess submission still in flight when
// the user hits Reset/New Game (which don't otherwise coordinate with it)
// discards its stale result instead of writing into the freshly-reset or
// brand-new game.
let gameGeneration = 0;
// Full guess history, kept in sync alongside board/keyboard state - needed to
// replay key statuses onto a freshly-rebuilt keyboard when the layout toggle
// swaps QWERTY<->AZERTY mid-game.
let guessHistory = { words: [], patterns: [] };

function updateBadges() {
  el.badgeMode.textContent = formatModeLabel(session.game_mode);
  el.badgeLang.textContent = `${session.lang} · ${session.word_length} letters`;
  el.badgeTries.textContent = `${currentTries}/${session.max_tries}`;
}

function showBanner(kind, message) {
  el.banner.hidden = false;
  el.banner.className = `banner ${kind}`;
  el.banner.textContent = message;
}

function hideBanner() {
  el.banner.hidden = true;
}

function applyKeyStatuses(words, patterns) {
  words.forEach((word, idx) => {
    [...patterns[idx]].forEach((emoji, i) => keyboard.setKeyStatus(word[i], emojiToStatus(emoji)));
  });
}

function updateKeyboardToggleLabel() {
  el.keyboardToggle.textContent = getKeyboardLayout() === KeyboardLayout.AZERTY ? 'AZERTY' : 'QWERTY';
}

function keyboardCallbacks() {
  return {
    onLetter: (letter) => !finished && board.typeLetter(letter),
    onEnter: handleEnter,
    onBackspace: () => !finished && board.backspace(),
  };
}

async function showInitialHints(myGeneration) {
  try {
    const response = await getInitialHints(session.session_uuid);
    if (myGeneration !== gameGeneration) return; // stale by the time the request resolved
    renderHints(el.hints, response.guess_stats);
  } catch (err) {
    if (myGeneration !== gameGeneration) return;
    renderHints(el.hints, null);
    if (!(err instanceof ApiError)) showToast(`Could not load hints (${err.message})`);
  }
}

async function updateHintsPanel(word, pattern, myGeneration) {
  if (session.game_mode !== GameMode.ASSISTED) return;

  try {
    const response = await getGuessStats(session.session_uuid, word, pattern);
    if (myGeneration !== gameGeneration) return; // stale by the time the request resolved
    renderHints(el.hints, response.guess_stats);
  } catch (err) {
    if (myGeneration !== gameGeneration) return;
    renderHints(el.hints, null);
    // ApiError here just means "no hints for this guess" (a normal case,
    // e.g. an empty candidate pool) - a network/timeout failure is a
    // different situation the user should know about, not a silently
    // blanked panel indistinguishable from that normal case.
    if (!(err instanceof ApiError)) showToast(`Could not refresh hints (${err.message})`);
  }
}

async function handleEnter() {
  // Guards against a double Enter (key repeat, fast double-click on the
  // on-screen key) firing a second submitGuess while the first is still
  // in flight - without this, two overlapping guesses could both resolve
  // and desync currentTries from the board's actual row count.
  if (finished || isSubmitting) return;

  if (!board.isCurrentRowFull()) {
    board.shakeCurrentRow();
    showToast('Not enough letters');
    return;
  }

  const myGeneration = gameGeneration;
  isSubmitting = true;
  try {
    const word = board.getCurrentGuess();
    let response;
    try {
      response = await submitGuess(session.session_uuid, word);
    } catch (err) {
      if (myGeneration !== gameGeneration) return; // Reset/New Game ran while this was in flight - discard
      // ApiError means the backend was reached and rejected the guess
      // (invalid word, or no tries left) - that's the row's fault, shake it.
      // Anything else (network/timeout) isn't the guess's fault.
      if (err instanceof ApiError) board.shakeCurrentRow();
      showToast(err.message);
      return;
    }

    if (myGeneration !== gameGeneration) return;

    const pattern = response.pattern;
    const statuses = await board.commitGuess(word, pattern);
    if (myGeneration !== gameGeneration) return;
    statuses.forEach((status, i) => keyboard.setKeyStatus(word[i], status));
    guessHistory.words.push(word);
    guessHistory.patterns.push(pattern);
    currentTries += 1;
    updateBadges();

    if (isWinningPattern(pattern)) {
      finished = true;
      board.popWinningRow();
      showBanner('win', `You won! The word was ${word.toUpperCase()}.`);
    } else if (currentTries >= session.max_tries) {
      finished = true;
      try {
        const wordResponse = await getWordToGuess(session.session_uuid);
        if (myGeneration !== gameGeneration) return;
        showBanner('lose', `Out of tries. The word was ${(wordResponse.word || '?').toUpperCase()}.`);
      } catch {
        if (myGeneration !== gameGeneration) return;
        showBanner('lose', 'Out of tries.');
      }
    }

    await updateHintsPanel(word, pattern, myGeneration);
  } finally {
    // Don't clear the flag on behalf of a generation that's no longer
    // current - the newer generation manages its own isSubmitting state
    // (showGame() already reset it when it started).
    if (myGeneration === gameGeneration) isSubmitting = false;
  }
}

function isGameFinished(stats) {
  if (stats.patterns.length && isWinningPattern(stats.patterns[stats.patterns.length - 1])) {
    return { finished: true, won: true };
  }
  if (stats.current_tries >= stats.max_tries) {
    return { finished: true, won: false };
  }
  return { finished: false, won: false };
}

export function mountGame({ onExit: exitCallback }) {
  onExit = exitCallback;

  el.reset.addEventListener('click', async () => {
    el.reset.disabled = true;
    try {
      // reset_game_session returns the freshly-reset session_stats directly -
      // no second round trip, so there's no window where the server has
      // reset but the client doesn't know the new state yet.
      const response = await resetGameSession(session.session_uuid, session.game_mode, session.max_tries);
      await showGame(session, response.session_stats);
    } catch (err) {
      showToast(`Could not reset the game (${err.message}). Try again.`);
    } finally {
      el.reset.disabled = false;
    }
  });

  el.newGame.addEventListener('click', async () => {
    // Unlike Reset, this doesn't call showGame() (it navigates away to the
    // setup screen instead) - bump the generation here too, or a guess
    // submission still in flight would resume after this handler and act on
    // now-destroyed/stale board/keyboard/session state.
    gameGeneration += 1;
    el.newGame.disabled = true;
    try {
      await deleteGameSession(session.session_uuid);
    } catch {
      // best-effort - fall through to local cleanup regardless
    }
    clearSession();
    if (keyboard) keyboard.destroy();
    el.newGame.disabled = false;
    onExit();
  });

  el.keyboardToggle.addEventListener('click', () => {
    const next = getKeyboardLayout() === KeyboardLayout.AZERTY ? KeyboardLayout.QWERTY : KeyboardLayout.AZERTY;
    setKeyboardLayout(next);
    updateKeyboardToggleLabel();

    keyboard.destroy();
    keyboard = createKeyboard(el.keyboard, keyboardCallbacks(), next);
    applyKeyStatuses(guessHistory.words, guessHistory.patterns);
  });

  el.copySessionId.addEventListener('click', async () => {
    try {
      await copyToClipboard(session.session_uuid);
      showToast('Session ID copied to clipboard');
    } catch (err) {
      showToast(`Could not copy (${err.message}) - select the ID text and copy it manually`);
    }
  });
}

export async function showGame(sessionInfo, stats) {
  gameGeneration += 1;
  const myGeneration = gameGeneration;
  session = {
    session_uuid: sessionInfo.session_uuid,
    lang: stats.lang,
    word_length: stats.word_length,
    game_mode: stats.game_mode,
    max_tries: stats.max_tries,
  };
  saveSession(session);
  el.sessionId.textContent = session.session_uuid;

  currentTries = stats.current_tries;
  finished = false;
  isSubmitting = false;
  guessHistory = { words: [...stats.guesses], patterns: [...stats.patterns] };
  hideBanner();

  if (keyboard) keyboard.destroy();
  board = createBoard(el.board, session.word_length, session.max_tries);
  keyboard = createKeyboard(el.keyboard, keyboardCallbacks(), getKeyboardLayout());
  updateKeyboardToggleLabel();

  // Always explicitly set the panel's content below, one way or another -
  // never leave whatever a *previous* game (or a stale Reset) left in there.
  // A fresh/just-reset game (no guesses yet) gets the precomputed best-opening
  // hints immediately; a resumed mid-game session's hints stay cleared for
  // now (game.best_guesses isn't persisted across sessions, so there's
  // nothing correct to show until the next guess recomputes it).
  el.hints.hidden = session.game_mode !== GameMode.ASSISTED;
  if (session.game_mode === GameMode.ASSISTED && stats.guesses.length === 0) {
    await showInitialHints(myGeneration);
  } else {
    el.hints.innerHTML = '';
  }

  board.rehydrate(stats.guesses, stats.patterns);
  applyKeyStatuses(stats.guesses, stats.patterns);

  updateBadges();

  const { finished: isFinished, won } = isGameFinished(stats);
  if (isFinished) {
    finished = true;
    const lastWord = stats.guesses[stats.guesses.length - 1];
    if (won) {
      showBanner('win', `You won! The word was ${lastWord.toUpperCase()}.`);
    } else {
      try {
        const wordResponse = await getWordToGuess(session.session_uuid);
        showBanner('lose', `Out of tries. The word was ${(wordResponse.word || '?').toUpperCase()}.`);
      } catch {
        showBanner('lose', 'Out of tries.');
      }
    }
  }
}
