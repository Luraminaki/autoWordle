// Guess grid: maxTries rows x wordLength tiles. One instance per active
// Play/Assisted game screen.

import { emojiToStatuses, statusLabel, describeGuess } from './statics.js';
import { announce } from './announce.js';

const REVEAL_STAGGER_MS = 150;
const WIN_POP_STAGGER_MS = 100;

// Single source of truth is the CSS custom property (--tile-reveal-ms in
// style.css's :root), which also drives .tile.reveal's actual animation
// duration - reading it here instead of a second hardcoded constant means
// the two can never drift out of sync.
const REVEAL_DURATION_MS = Number(
  getComputedStyle(document.documentElement).getPropertyValue('--tile-reveal-ms'),
) || 500;

export function createBoard(container, wordLength, maxTries) {
  container.innerHTML = '';
  const rows = [];

  for (let r = 0; r < maxTries; r += 1) {
    const rowEl = document.createElement('div');
    rowEl.className = 'board-row';
    const tiles = [];

    for (let c = 0; c < wordLength; c += 1) {
      const tile = document.createElement('div');
      tile.className = 'tile';
      rowEl.appendChild(tile);
      tiles.push(tile);
    }

    container.appendChild(rowEl);
    rows.push({ el: rowEl, tiles });
  }

  let currentRow = 0;
  let currentGuess = [];

  function renderCurrentRow() {
    const { tiles } = rows[currentRow];
    tiles.forEach((tile, i) => {
      tile.textContent = currentGuess[i] || '';
      tile.classList.toggle('filled', Boolean(currentGuess[i]));
    });
  }

  // Internal only - no caller outside this module needs to know the row
  // count directly, they call typeLetter/backspace/commitGuess and let the
  // board enforce its own bounds.
  function isGameOver() {
    return currentRow >= maxTries;
  }

  return {
    getCurrentGuess() {
      return currentGuess.join('');
    },

    isCurrentRowFull() {
      return currentGuess.length === wordLength;
    },

    typeLetter(letter) {
      if (isGameOver() || currentGuess.length >= wordLength) return;
      currentGuess.push(letter);
      renderCurrentRow();
    },

    backspace() {
      if (isGameOver() || currentGuess.length === 0) return;
      currentGuess.pop();
      renderCurrentRow();
    },

    shakeCurrentRow() {
      const { el } = rows[currentRow];
      el.classList.remove('shake');
      // eslint-disable-next-line no-void
      void el.offsetWidth; // restart animation
      el.classList.add('shake');
    },

    /** Reveals `word`/`pattern` (emoji string) on the current row, then advances. Resolves with per-letter statuses once the flip animation finishes. */
    commitGuess(word, pattern) {
      const statuses = emojiToStatuses(pattern);
      const { tiles } = rows[currentRow];

      tiles.forEach((tile, i) => {
        tile.textContent = word[i];
        tile.setAttribute('aria-label', `${word[i]}: ${statusLabel(statuses[i])}`);
        setTimeout(() => {
          tile.classList.add('reveal', `status-${statuses[i]}`);
        }, i * REVEAL_STAGGER_MS);
      });

      announce(`Guess ${word}: ${describeGuess(word, pattern)}.`);

      currentRow += 1;
      currentGuess = [];

      const totalMs = (wordLength - 1) * REVEAL_STAGGER_MS + REVEAL_DURATION_MS;
      return new Promise((resolve) => setTimeout(() => resolve(statuses), totalMs));
    },

    popWinningRow() {
      const { tiles } = rows[currentRow - 1];
      tiles.forEach((tile, i) => {
        setTimeout(() => tile.classList.add('win-pop'), i * WIN_POP_STAGGER_MS);
      });
    },

    /** Replays past guesses/patterns instantly (no animation) - used to resume a session. */
    rehydrate(guesses, patterns) {
      guesses.forEach((word, idx) => {
        const pattern = patterns[idx];
        const statuses = emojiToStatuses(pattern);
        const { tiles } = rows[idx];

        tiles.forEach((tile, i) => {
          tile.textContent = word[i];
          tile.setAttribute('aria-label', `${word[i]}: ${statusLabel(statuses[i])}`);
          tile.classList.add('filled', `status-${statuses[i]}`);
        });
      });

      currentRow = guesses.length;
      currentGuess = [];
    },
  };
}
