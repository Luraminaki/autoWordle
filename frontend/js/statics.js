// Mirrors autoWordle/modules/statics.py: shared enums and the pattern<->emoji mapping.

export const GameMode = {
  PLAY: 'GAME_MODE_PLAY',
  SOLVE: 'GAME_MODE_SOLVE',
  ASSISTED: 'GAME_MODE_ASSISTED',
};

export const PrecomputeStatus = {
  QUEUED: 'queued',
  RUNNING: 'running',
  DONE: 'done',
  FAILED: 'failed',
};

// Every API response envelope's `status` field (webapp/api_schemas.py's StatusResponse).
export const StatusFunction = {
  SUCCESS: 'SUCCESS',
  FAIL: 'FAIL',
  ONGOING: 'ONGOING',
  DONE: 'DONE',
  ERROR: 'ERROR',
  WARNING: 'WARNING',
};

const MODE_PREFIX = 'GAME_MODE_';

export function formatModeLabel(value) {
  const word = value.startsWith(MODE_PREFIX) ? value.slice(MODE_PREFIX.length).toLowerCase() : value.toLowerCase();
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export const StatusLetter = {
  MISS: 1,
  MISPLACED: 2,
  EXACT: 3,
};

const PATTERN_TO_EMOJI = {
  [StatusLetter.MISS]: '⬛',
  [StatusLetter.MISPLACED]: '🟨',
  [StatusLetter.EXACT]: '🟩',
};

const EMOJI_TO_STATUS = Object.fromEntries(
  Object.entries(PATTERN_TO_EMOJI).map(([status, emoji]) => [emoji, Number(status)]),
);

// Text equivalent of a tile/key's color, for screen readers - the color
// itself (miss/misplaced/exact) is otherwise the only signal.
const STATUS_LABELS = {
  [StatusLetter.MISS]: 'not in word',
  [StatusLetter.MISPLACED]: 'wrong spot',
  [StatusLetter.EXACT]: 'correct spot',
};

export function statusLabel(status) {
  return STATUS_LABELS[status];
}

function statusToEmoji(status) {
  return PATTERN_TO_EMOJI[status];
}

export function emojiToStatus(emoji) {
  return EMOJI_TO_STATUS[emoji];
}

export function patternToEmoji(statuses) {
  return statuses.map(statusToEmoji).join('');
}

export function emojiToStatuses(pattern) {
  return [...pattern].map(emojiToStatus);
}

export function isWinningPattern(pattern) {
  return [...pattern].every((emoji) => emoji === PATTERN_TO_EMOJI[StatusLetter.EXACT]);
}

// Shared by board.js (live guesses) and solve.js (manual entries) so the
// spoken-announcement sentence isn't built twice in slightly different ways.
export function describeGuess(word, pattern) {
  const statuses = emojiToStatuses(pattern);
  return [...word].map((letter, i) => `${letter} ${statusLabel(statuses[i])}`).join(', ');
}
