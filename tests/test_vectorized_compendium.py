#!/usr/bin/env python3
"""Tests for `autoWordle.modules.vectorized_compendium`."""

#===================================================================================================
import pathlib

import numpy as np
import pytest

from autoWordle.modules import compendium_cache, computing, legacy_compendium, statics, vectorized_compendium, word_codec

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
    letter_counts = vectorized_compendium._compute_letter_counts(words_arr)  # pyright: ignore[reportPrivateUsage]

    pattern_ints = vectorized_compendium._compute_patterns_for_guess(guess_arr, words_arr, letter_counts)  # pyright: ignore[reportPrivateUsage]

    assert int(pattern_ints[0]) == word_codec.tord_to_int(expected, 10)


def test_compute_patterns_for_guess_exhaustive_against_reference(mini_words_file: pathlib.Path) -> None:
    words = list(word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10))
    words_arr = np.array(words, dtype=np.int16)
    letter_counts = vectorized_compendium._compute_letter_counts(words_arr)  # pyright: ignore[reportPrivateUsage]

    for gi, guess in enumerate(words):
        pattern_ints = vectorized_compendium._compute_patterns_for_guess(words_arr[gi], words_arr, letter_counts)  # pyright: ignore[reportPrivateUsage]

        for wi, word in enumerate(words):
            if word == guess:
                continue

            expected = word_codec.tord_to_int(computing.compute_pattern(guess=guess, word=word), 10)
            assert int(pattern_ints[wi]) == expected


def test_compute_letter_counts_tallies_every_letter_per_word() -> None:
    # word_codec shift: 'a'=10, so (10,10,11,12,13) is "aabcd".
    words_arr = np.array([(10, 10, 11, 12, 13), (14, 15, 16, 17, 18)], dtype=np.int16)

    letter_counts = vectorized_compendium._compute_letter_counts(words_arr)  # pyright: ignore[reportPrivateUsage]

    assert letter_counts[0, 10 - 10] == 2  # word 0 has two 'a's (offset 0)
    assert letter_counts[0, 11 - 10] == 1  # and one 'b' (offset 1)
    assert letter_counts[1, 10 - 10] == 0  # word 1 has no 'a' at all
    assert letter_counts.sum() == 10  # 2 words * 5 letters each, every letter counted exactly once


def test_reused_letter_counts_gives_same_results_across_different_guesses(mini_words_file: pathlib.Path) -> None:
    # Regression test: letter_counts is computed once and reused for every
    # guess in the real callers (stream_pattern_compendium_to_cache,
    # compute_word_counter_by_pattern_cross) - confirm reusing the same
    # precomputed array for multiple, different guesses against the same
    # pool still gives each guess its own correct, independent pattern
    # (nothing about the shared `letter_counts` leaks between guesses).
    words = list(word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10))
    words_arr = np.array(words, dtype=np.int16)
    letter_counts = vectorized_compendium._compute_letter_counts(words_arr)  # pyright: ignore[reportPrivateUsage]

    for guess in words[:5]:
        guess_arr = np.array(guess, dtype=np.int16)
        actual = vectorized_compendium._compute_patterns_for_guess(guess_arr, words_arr, letter_counts)  # pyright: ignore[reportPrivateUsage]

        for wi, word in enumerate(words):
            if word == guess:
                continue
            expected = word_codec.tord_to_int(computing.compute_pattern(guess=guess, word=word), 10)
            assert int(actual[wi]) == expected


def test_compute_word_counter_by_pattern_cross_matches_brute_force(mini_words_file: pathlib.Path) -> None:
    words = list(word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10))
    guesses = set(words)
    targets = set(words[:6])  # a narrowed pool subset, distinct from the full guess set

    actual = vectorized_compendium.compute_word_counter_by_pattern_cross(guesses, targets)

    expected: dict[tuple[int, ...], dict[tuple[int, ...], int]] = {}
    for guess in guesses:
        for target in targets:
            pattern = computing.compute_pattern(guess=guess, word=target)
            expected.setdefault(pattern, {})[guess] = expected.get(pattern, {}).get(guess, 0) + 1

    assert actual == expected


def test_compute_word_counter_by_pattern_cross_includes_self_match(mini_words_file: pathlib.Path) -> None:
    # Unlike `legacy_compendium.build_pattern_compendium`'s self-pair skip, a guess
    # that's also a target should register its own all-EXACT match - that's
    # meaningful information (this guess could itself be the answer), not a
    # redundant self-comparison to discard.
    words = list(word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10))
    target = words[0]

    counter = vectorized_compendium.compute_word_counter_by_pattern_cross({target}, {target})

    all_exact = (statics.StatusLetter.EXACT.value,) * 5
    assert counter[all_exact][target] == 1


def test_stream_pattern_compendium_matches_full_compendium(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Regression test: `stream_pattern_compendium_to_cache` must produce the
    # exact same `word_counter_by_pattern` tally and cache contents as the
    # old two-step `build_pattern_compendium` -> `compute_word_counter_by_pattern`
    # pipeline it replaced, despite never materializing the full `O(n**2)`
    # compendium at once and computing patterns via vectorized array ops.
    words = word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10)

    expected_compendium = legacy_compendium.build_pattern_compendium(words)
    expected_counter = legacy_compendium.compute_word_counter_by_pattern(expected_compendium)

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


def test_stream_pattern_compendium_calls_progress_callback(tmp_path: pathlib.Path, mini_words_file: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the callback to fire on every guess (instead of waiting
    # `_PROGRESS_LOG_INTERVAL_SECONDS` between calls) so this test doesn't
    # depend on wall-clock timing.
    monkeypatch.setattr(vectorized_compendium, '_PROGRESS_LOG_INTERVAL_SECONDS', 0.0)

    words = word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10)
    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(5)]
    cache = compendium_cache.CacheDB(tmp_path / 'progress.sqlite', patterns, build_mode=True)

    calls: list[tuple[float, float]] = []
    _ = vectorized_compendium.stream_pattern_compendium_to_cache(
        words, cache, progress_callback=lambda fraction_done, eta_seconds: calls.append((fraction_done, eta_seconds)))

    assert len(calls) == len(words)
    assert all(0.0 < fraction_done <= 1.0 for fraction_done, _ in calls)
    assert all(eta_seconds >= 0.0 for _, eta_seconds in calls)
    assert calls[-1][0] == 1.0  # last call is 100% done

    cache.close()


def test_stream_pattern_compendium_flushes_in_small_batches(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Same equivalence check, forced through multiple flush cycles (default
    # batch_size is 200_000, far larger than this tiny word list would ever
    # need) to make sure batching doesn't drop or duplicate entries.
    words = word_codec.get_words_list(mini_words_file, word_length=5, shift=ord('a') - 10)

    expected_compendium = legacy_compendium.build_pattern_compendium(words)
    expected_counter = legacy_compendium.compute_word_counter_by_pattern(expected_compendium)

    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(5)]
    cache = compendium_cache.CacheDB(tmp_path / 'stream_small_batch.sqlite', patterns, build_mode=True)
    actual_counter = vectorized_compendium.stream_pattern_compendium_to_cache(words, cache, batch_size=3)

    assert actual_counter == expected_counter
    cache.close()
