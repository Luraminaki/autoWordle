#!/usr/bin/env python3
"""Shared enums and pattern/emoji conversion helpers.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import enum
import itertools as it


class StatusLetter(enum.IntEnum):
    """Per-letter guess evaluation, as an ordered int enum (used as pattern digits)."""

    MISS = 1
    MISPLACED = 2
    EXACT = 3


class GameMode(enum.StrEnum):
    """Game session mode.

    A `str` enum so it round-trips as a plain string over the API/JSON boundary
    and through FastAPI/Pydantic validation without extra conversion.
    """

    GAME_MODE_PLAY = 'GAME_MODE_PLAY'
    GAME_MODE_SOLVE = 'GAME_MODE_SOLVE'
    GAME_MODE_ASSISTED = 'GAME_MODE_ASSISTED'


class StatusFunction(enum.StrEnum):
    """Outcome status reported back by API handlers.

    A `str` enum for the same reason as `GameMode`: it must serialize as the
    plain status name (e.g. `"SUCCESS"`), not an opaque integer.
    """

    SUCCESS = 'SUCCESS'
    FAIL = 'FAIL'
    ONGOING = 'ONGOING'
    DONE = 'DONE'
    ERROR = 'ERROR'
    WARNING = 'WARNING'


class PrecomputeStatus(enum.StrEnum):
    """A precompute job's lifecycle state, as tracked by `app.precompute_store`.

    A `str` enum for the same reason as `GameMode`/`StatusFunction`: it's
    stored as plain text in SQLite and serialized as-is over the API/SSE
    boundary, with no separate mapping needed either direction.
    """

    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


_PATTERN_TO_EMOJI = {
    StatusLetter.MISS: '⬛',
    StatusLetter.MISPLACED: '🟨',
    StatusLetter.EXACT: '🟩',
}
_EMOJI_TO_PATTERN = {emoji: status.value for status, emoji in _PATTERN_TO_EMOJI.items()}


def pattern_to_emoji(pattern: tuple[int, ...]) -> str:
    """Convert a numeric guess pattern into its emoji representation.

    Args:
        pattern: Sequence of `StatusLetter` values, one per letter.

    Returns:
        str: Emoji string (e.g. `"🟩⬛🟨⬛⬛"`).
    """
    return ''.join(_PATTERN_TO_EMOJI[StatusLetter(x)] for x in pattern)


def emoji_to_pattern(pattern: str) -> str:
    """Convert an emoji guess pattern back into its digit-string representation.

    Args:
        pattern: Emoji string (e.g. `"🟩⬛🟨⬛⬛"`).

    Returns:
        str: Digit string (e.g. `"31211"`), one `StatusLetter` value per character.
    """
    return ''.join(str(_EMOJI_TO_PATTERN[x]) for x in pattern)


def pattern_permutations(word_length: int = 5) -> set[tuple[int, ...]]:
    """Build every possible guess pattern for a given word length.

    Args:
        word_length: Number of letters in the word.

    Returns:
        set[tuple[int, ...]]: All `3 ** word_length` possible patterns.
    """
    return set(it.product([StatusLetter.MISS, StatusLetter.MISPLACED, StatusLetter.EXACT], repeat=word_length))
