#!/usr/bin/env python3
"""Tests for `autoWordle.modules.statics`."""

#===================================================================================================
import itertools

from autoWordle.modules import statics

#===================================================================================================


def test_pattern_to_emoji_known_values() -> None:
    pattern = (statics.StatusLetter.EXACT.value, statics.StatusLetter.MISS.value,
              statics.StatusLetter.MISPLACED.value, statics.StatusLetter.MISS.value, statics.StatusLetter.MISS.value)

    assert statics.pattern_to_emoji(pattern) == '🟩⬛🟨⬛⬛'


def test_emoji_to_pattern_known_values() -> None:
    assert statics.emoji_to_pattern('🟩⬛🟨⬛⬛') == '31211'


def test_pattern_emoji_round_trip() -> None:
    for pattern in itertools.product([statics.StatusLetter.MISS.value, statics.StatusLetter.MISPLACED.value,
                                      statics.StatusLetter.EXACT.value], repeat=5):
        emoji = statics.pattern_to_emoji(pattern)
        back = tuple(int(digit) for digit in statics.emoji_to_pattern(emoji))
        assert back == pattern


def test_pattern_permutations_count() -> None:
    assert len(statics.pattern_permutations(5)) == 3 ** 5


def test_game_mode_is_plain_string() -> None:
    assert statics.GameMode.GAME_MODE_PLAY == 'GAME_MODE_PLAY'
    assert statics.GameMode.GAME_MODE_PLAY.value == statics.GameMode.GAME_MODE_PLAY.name


def test_status_function_is_plain_string() -> None:
    assert statics.StatusFunction.SUCCESS == 'SUCCESS'
    assert statics.StatusFunction.SUCCESS.value == statics.StatusFunction.SUCCESS.name
