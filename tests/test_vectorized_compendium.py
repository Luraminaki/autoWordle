#!/usr/bin/env python3
"""Tests for `autoWordle.modules.vectorized_compendium`."""

#===================================================================================================
import pathlib

import numpy as np
import pytest

from autoWordle.modules import compendium_cache, computing, entropy, statics, vectorized_compendium, word_codec

#===================================================================================================

MISS = statics.StatusLetter.MISS.value
MISPLACED = statics.StatusLetter.MISPLACED.value
EXACT = statics.StatusLetter.EXACT.value


@pytest.mark.parametrize(('guess', 'word', 'expected'), [
    # Values must fall in the word_codec shift range [10, 36) -
    # `_compute_patterns_for_guess`, unlike `computing.compute_pattern`, isn't
    # alphabet-agnostic (see its docstring).
    ((10, 11, 12, 13, 14), (10, 11, 12, 13, 14), (EXACT,) * 5),
    ((15, 16, 17, 18, 19), (10, 11, 12, 13, 14), (MISS,) * 5),
    ((10, 10, 15, 16, 17), (10, 11, 12, 13, 14), (EXACT, MISS, MISS, MISS, MISS)),
    ((10, 14, 10, 15, 16), (10, 10, 11, 12, 13), (EXACT, MISS, MISPLACED, MISS, MISS)),
    # Regression case: a guess's *second* occurrence of a repeated letter
    # must still register as misplaced even though the *first* occurrence is
    # an independent exact match elsewhere in the word (see `computing.compute_pattern`).
    ((19, 14, 21, 21, 34), (10, 21, 21, 10, 34), (MISS, MISS, EXACT, MISPLACED, EXACT)),
])
def test_compute_patterns_for_guess_matches_reference(guess: tuple[int, ...], word: tuple[int, ...],
                                                       expected: tuple[int, ...]) -> None:
    words_arr = np.array([word], dtype=np.int16)
    guess_arr = np.array(guess, dtype=np.int16)

    pattern_ints = vectorized_compendium._compute_patterns_for_guess(guess_arr, words_arr)  # pyright: ignore[reportPrivateUsage]

    assert int(pattern_ints[0]) == word_codec.tord_to_int(expected, 10)


def test_compute_patterns_for_guess_exhaustive_against_reference(mini_words_file: pathlib.Path) -> None:
    words = list(word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10))
    words_arr = np.array(words, dtype=np.int16)

    for gi, guess in enumerate(words):
        pattern_ints = vectorized_compendium._compute_patterns_for_guess(words_arr[gi], words_arr)  # pyright: ignore[reportPrivateUsage]

        for wi, word in enumerate(words):
            if word == guess:
                continue

            expected = word_codec.tord_to_int(computing.compute_pattern(guess=guess, word=word), 10)
            assert int(pattern_ints[wi]) == expected


def test_stream_pattern_compendium_matches_full_compendium(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Regression test: `stream_pattern_compendium_to_cache` must produce the
    # exact same `word_counter_by_pattern` tally and cache contents as the
    # old two-step `build_pattern_compendium` -> `compute_word_counter_by_pattern`
    # pipeline it replaced, despite never materializing the full `O(n**2)`
    # compendium at once and computing patterns via vectorized array ops.
    words = word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10)

    expected_compendium = computing.build_pattern_compendium(words)
    expected_counter = entropy.compute_word_counter_by_pattern(expected_compendium)

    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(5)]
    cache = compendium_cache.CacheDB(tmp_path / 'stream.sqlite', patterns, build_mode=True)
    actual_counter = vectorized_compendium.stream_pattern_compendium_to_cache(words, cache)

    assert actual_counter == expected_counter

    for pattern, combinations in expected_compendium.items():
        expected_pairs = {(word_codec.tord_to_int(guess), word_codec.tord_to_int(word)) for guess, word in combinations}
        actual_pairs = set(cache.get_entries(word_codec.tord_to_int(pattern, 10)))
        assert actual_pairs == expected_pairs

    cache.close()


def test_stream_pattern_compendium_rejects_out_of_range_letters(tmp_path: pathlib.Path) -> None:
    # Regression guard: `_compute_patterns_for_guess` indexes a fixed-size
    # 26-column array by `letter - 10` with no bounds check, so an
    # out-of-range letter would otherwise silently wrap to an unrelated
    # column instead of failing loudly.
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10)}
    cache = compendium_cache.CacheDB(tmp_path / 'out_of_range.sqlite', [], build_mode=True)

    with pytest.raises(ValueError, match='shifted-ordinal'):
        _ = vectorized_compendium.stream_pattern_compendium_to_cache(words, cache)

    cache.close()


def test_stream_pattern_compendium_flushes_in_small_batches(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Same equivalence check, forced through multiple flush cycles (default
    # batch_size is 200_000, far larger than this tiny word list would ever
    # need) to make sure batching doesn't drop or duplicate entries.
    words = word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10)

    expected_compendium = computing.build_pattern_compendium(words)
    expected_counter = entropy.compute_word_counter_by_pattern(expected_compendium)

    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(5)]
    cache = compendium_cache.CacheDB(tmp_path / 'stream_small_batch.sqlite', patterns, build_mode=True)
    actual_counter = vectorized_compendium.stream_pattern_compendium_to_cache(words, cache, batch_size=3)

    assert actual_counter == expected_counter
    cache.close()
