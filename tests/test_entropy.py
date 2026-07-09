#!/usr/bin/env python3
"""Tests for `autoWordle.modules.entropy`."""

#===================================================================================================
import pytest

from autoWordle.modules import entropy, legacy_compendium

#===================================================================================================


def test_rank_words_by_entropy_uses_explicit_nbr_words_not_pool_size() -> None:
    # Regression test for the full-dictionary-vs-narrowed-pool fallback
    # (wordle.py): when `pool_words` (the guesses to rank) isn't the same set
    # as the actual target pool, `nbr_words` must drive the probability
    # denominator - not `len(pool_words)`, which would silently use the wrong
    # pool size whenever the two differ.
    guesses = {(1, 2, 3), (4, 5, 6)}
    word_counter_by_pattern = {
        (1, 1, 1): {(1, 2, 3): 3, (4, 5, 6): 7},
        (2, 2, 2): {(1, 2, 3): 7, (4, 5, 6): 3},
    }
    explicit_nbr_words = 10  # deliberately different from len(guesses) == 2

    actual = entropy.rank_words_by_entropy(guesses, word_counter_by_pattern, threads=1, nbr_words=explicit_nbr_words)

    expected = sorted(
        ((word, entropy.compute_word_entropy(word, word_counter_by_pattern, explicit_nbr_words)) for word in guesses),
        key=lambda x: x[1], reverse=True)
    assert actual == expected

    # Sanity check that the denominator actually matters here (otherwise this
    # test wouldn't catch a regression back to always using len(pool_words)).
    wrong_denominator = sorted(
        ((word, entropy.compute_word_entropy(word, word_counter_by_pattern, len(guesses))) for word in guesses),
        key=lambda x: x[1], reverse=True)
    assert actual != wrong_denominator


def test_rank_words_by_entropy_serial_matches_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test for the size-gated serial fallback: below
    # `_SERIAL_THRESHOLD`, rank_words_by_entropy skips ProcessPoolExecutor
    # entirely (process fork/IPC overhead dwarfs the actual computation for
    # small pools - benchmarked ~1.4-450x slower depending on pool size) but
    # must produce byte-identical results to the parallel path.
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (1, 7, 3, 9, 5), (6, 2, 8, 4, 10), (2, 4, 6, 8, 10)}
    compendium = legacy_compendium.build_pattern_compendium(words)
    word_counter_by_pattern = legacy_compendium.compute_word_counter_by_pattern(compendium)

    monkeypatch.setattr(entropy, '_SERIAL_THRESHOLD', 0)
    parallel = entropy.rank_words_by_entropy(words, word_counter_by_pattern, threads=2)

    monkeypatch.setattr(entropy, '_SERIAL_THRESHOLD', 1_000_000)
    serial = entropy.rank_words_by_entropy(words, word_counter_by_pattern, threads=2)

    assert serial == parallel


def test_rank_words_by_entropy_below_threshold_does_not_use_process_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    # Confirms the gate actually skips ProcessPoolExecutor below the
    # threshold, not just that results happen to match.
    words = {(1, 2, 3), (4, 5, 6)}
    word_counter_by_pattern = {(1, 1, 1): {(1, 2, 3): 1, (4, 5, 6): 1}}

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('ProcessPoolExecutor should not be used below _SERIAL_THRESHOLD')

    monkeypatch.setattr(entropy, '_SERIAL_THRESHOLD', 1_000_000)
    monkeypatch.setattr(entropy, 'ProcessPoolExecutor', _boom)

    result = entropy.rank_words_by_entropy(words, word_counter_by_pattern, threads=1)

    assert {word for word, _ in result} == words
