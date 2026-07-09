#!/usr/bin/env python3
"""Tests for `autoWordle.modules.computing`."""

#===================================================================================================
from autoWordle.modules import computing, statics

#===================================================================================================

MISS = statics.StatusLetter.MISS.value
MISPLACED = statics.StatusLetter.MISPLACED.value
EXACT = statics.StatusLetter.EXACT.value


def test_compute_pattern_exact_match() -> None:
    word = (1, 2, 3, 4, 5)
    assert computing.compute_pattern(guess=word, word=word) == (EXACT,) * 5


def test_compute_pattern_no_overlap() -> None:
    word = (1, 2, 3, 4, 5)
    guess = (6, 7, 8, 9, 10)
    assert computing.compute_pattern(guess=guess, word=word) == (MISS,) * 5


def test_compute_pattern_duplicate_letter_not_overcounted() -> None:
    # Guess has two '1's, word has only one: only the exact-position one should count.
    word = (1, 2, 3, 4, 5)
    guess = (1, 1, 6, 7, 8)
    assert computing.compute_pattern(guess=guess, word=word) == (EXACT, MISS, MISS, MISS, MISS)


def test_compute_pattern_duplicate_letter_misplaced() -> None:
    # Guess has two '1's, word has two '1's too (one at the same position, one elsewhere):
    # the guess's other '1' should register as misplaced.
    word = (1, 1, 2, 3, 4)
    guess = (1, 5, 1, 6, 7)
    assert computing.compute_pattern(guess=guess, word=word) == (EXACT, MISS, MISPLACED, MISS, MISS)


def test_compute_pattern_misplaced_survives_later_exact_match_on_same_letter() -> None:
    # Regression test: guess="jelly" (19,14,21,21,34), word="allay" (10,21,21,10,34)
    # (shifted ordinals, shift = ord('a') - 10). `allay` has two 'l's; `jelly`'s
    # first 'l' (index 2) is an exact match, but its *second* 'l' (index 3)
    # should still register as misplaced against `allay`'s other, otherwise
    # unused 'l' - a word-order/`.index()`-based implementation can instead
    # "spend" that leftover 'l' on index 2 before learning index 2 is exact,
    # permanently losing it and leaving index 3 as MISS instead.
    guess = (19, 14, 21, 21, 34)
    word = (10, 21, 21, 10, 34)
    assert computing.compute_pattern(guess=guess, word=word) == (MISS, MISS, EXACT, MISPLACED, EXACT)


def test_build_letter_extractor_and_update() -> None:
    guess = (1, 2, 3, 4, 5)
    pattern = (EXACT, MISS, MISPLACED, MISS, EXACT)

    extractor = computing.build_letter_extractor(guess, pattern)
    assert extractor.incl == {1: 1, 3: 1, 5: 1}
    assert extractor.excl == {2: 1, 4: 1}

    merged = computing.update_letter_extractor(computing.LetterExtractor(incl={1: 1}), extractor)
    assert merged.incl == {1: 2, 3: 1, 5: 1}
    assert merged.excl == {2: 1, 4: 1}


def test_gather_pool_letters_detects_dupes() -> None:
    # Once a word has any duplicated letter, every unique letter in that word
    # gets a recorded count (not just the duplicated one) - the second word
    # here has no duplicates at all, so it contributes no entries.
    pool = [((1, 1, 2, 3, 4), 1.0), ((5, 6, 7, 8, 9), 1.0)]
    pool_letters, dupes = computing.gather_pool_letters(pool)

    assert pool_letters == {1, 2, 3, 4, 5, 6, 7, 8, 9}
    assert dupes == {1: 2, 2: 1, 3: 1, 4: 1}
