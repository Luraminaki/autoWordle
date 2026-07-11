// Solve screen controller: manual word + pattern entry for an external
// puzzle, guess history, solver hints.

import { getGuessStats, deleteGameSession } from './api.js';
import { renderHints } from './hints.js';
import { StatusLetter, patternToEmoji, emojiToStatuses, statusLabel, describeGuess } from './statics.js';
import { saveSession, clearSession } from './storage.js';
import { announce } from './announce.js';
import { showToast } from './toast.js';
import { copyToClipboard } from './clipboard.js';

const el = {
  badgeLang: document.getElementById('solve-badge-lang'),
  newGame: document.getElementById('solve-new'),
  sessionId: document.getElementById('solve-session-id'),
  copySessionId: document.getElementById('solve-copy-session-id'),
  history: document.getElementById('solve-history'),
  inputRow: document.getElementById('solve-input-row'),
  patternRow: document.getElementById('solve-pattern-row'),
  submit: document.getElementById('solve-submit'),
  error: document.getElementById('solve-error'),
  hints: document.getElementById('solve-hints-panel'),
};

const NEXT_STATUS = {
  [StatusLetter.MISS]: StatusLetter.MISPLACED,
  [StatusLetter.MISPLACED]: StatusLetter.EXACT,
  [StatusLetter.EXACT]: StatusLetter.MISS,
};

let session = null;
let letterInputs = [];
let patternTiles = [];
let patternStatuses = [];
let onExit = null;

function buildInputRow(wordLength) {
  el.inputRow.innerHTML = '';
  letterInputs = [];

  for (let i = 0; i < wordLength; i += 1) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'solve-letter';
    input.maxLength = 1;
    input.setAttribute('aria-label', `Letter ${i + 1}`);

    input.addEventListener('input', () => {
      input.value = input.value.replace(/[^a-zA-Z]/g, '').toLowerCase();
      if (input.value && i < wordLength - 1) letterInputs[i + 1].focus();
    });

    input.addEventListener('keydown', (event) => {
      if (event.key === 'Backspace' && !input.value && i > 0) {
        letterInputs[i - 1].focus();
      } else if (event.key === 'Enter') {
        handleSubmit();
      }
    });

    el.inputRow.appendChild(input);
    letterInputs.push(input);
  }
}

function buildPatternRow(wordLength) {
  el.patternRow.innerHTML = '';
  patternTiles = [];
  patternStatuses = new Array(wordLength).fill(StatusLetter.MISS);

  for (let i = 0; i < wordLength; i += 1) {
    const tile = document.createElement('button');
    tile.type = 'button';
    tile.className = `pattern-tile status-${StatusLetter.MISS}`;
    tile.title = 'Click to cycle: miss / misplaced / exact';
    setPatternTileLabel(tile, i, StatusLetter.MISS);
    tile.addEventListener('click', () => {
      patternStatuses[i] = NEXT_STATUS[patternStatuses[i]];
      tile.className = `pattern-tile status-${patternStatuses[i]}`;
      setPatternTileLabel(tile, i, patternStatuses[i]);
    });
    el.patternRow.appendChild(tile);
    patternTiles.push(tile);
  }
}

function setPatternTileLabel(tile, index, status) {
  tile.setAttribute('aria-label', `Letter ${index + 1} pattern: ${statusLabel(status)}`);
}

function resetInputs() {
  letterInputs.forEach((input) => {
    input.value = '';
  });
  patternStatuses.fill(StatusLetter.MISS);
  patternTiles.forEach((tile, i) => {
    tile.className = `pattern-tile status-${StatusLetter.MISS}`;
    setPatternTileLabel(tile, i, StatusLetter.MISS);
  });
  if (letterInputs[0]) letterInputs[0].focus();
}

function appendHistoryRow(word, pattern) {
  const statuses = emojiToStatuses(pattern);
  const row = document.createElement('div');
  row.className = 'solve-history-row';

  [...word].forEach((letter, i) => {
    const tile = document.createElement('div');
    tile.className = `tile filled status-${statuses[i]}`;
    tile.textContent = letter;
    tile.setAttribute('aria-label', `${letter}: ${statusLabel(statuses[i])}`);
    row.appendChild(tile);
  });

  el.history.appendChild(row);
}

async function handleSubmit() {
  // The Enter key (pressed from a letter box) calls this directly, bypassing
  // whatever triggered the click handler - guard on the button's own disabled
  // state so a fast Enter-then-click (or repeated Enter) can't fire a second
  // overlapping getGuessStats call while the first is still in flight.
  if (el.submit.disabled) return;

  el.error.hidden = true;

  const word = letterInputs.map((input) => input.value).join('');
  if (word.length !== session.word_length) {
    el.error.textContent = 'Enter all letters before submitting';
    el.error.hidden = false;
    return;
  }

  const pattern = patternToEmoji(patternStatuses);

  el.submit.disabled = true;
  try {
    const response = await getGuessStats(session.session_uuid, word, pattern);

    if (!response.guess_stats) {
      el.error.textContent = 'No matching candidates - check the word and pattern';
      el.error.hidden = false;
      return;
    }

    appendHistoryRow(word, pattern);
    announce(`Guess ${word}: ${describeGuess(word, pattern)}. ${response.guess_stats.pool_words.length} candidates remaining.`);
    renderHints(el.hints, response.guess_stats);
    resetInputs();
  } catch (err) {
    el.error.textContent = err.message;
    el.error.hidden = false;
  } finally {
    el.submit.disabled = false;
  }
}

export function mountSolve({ onExit: exitCallback }) {
  onExit = exitCallback;

  el.submit.addEventListener('click', handleSubmit);

  el.newGame.addEventListener('click', async () => {
    el.newGame.disabled = true;
    try {
      await deleteGameSession(session.session_uuid);
    } catch {
      // best-effort - fall through to local cleanup regardless
    }
    clearSession();
    el.newGame.disabled = false;
    onExit();
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

export function showSolve(sessionInfo, stats) {
  session = {
    session_uuid: sessionInfo.session_uuid,
    lang: stats.lang,
    word_length: stats.word_length,
    game_mode: stats.game_mode,
    max_tries: stats.max_tries,
  };
  saveSession(session);
  el.sessionId.textContent = session.session_uuid;

  el.badgeLang.textContent = `${session.lang} · ${session.word_length} letters`;
  el.error.hidden = true;
  el.hints.hidden = true;
  el.hints.innerHTML = '';

  el.history.innerHTML = '';
  stats.guesses.forEach((word, idx) => appendHistoryRow(word, stats.patterns[idx]));

  buildInputRow(session.word_length);
  buildPatternRow(session.word_length);
  resetInputs();
}
