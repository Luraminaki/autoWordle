#!/usr/bin/env python3
"""Tests for `autoWordle.modules.entropy`."""

#===================================================================================================
from autoWordle.modules import computing, entropy

#===================================================================================================


def test_compute_words_information_is_sorted_and_complete() -> None:
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (1, 7, 3, 9, 5), (6, 2, 8, 4, 10)}
    compendium = computing.build_pattern_compendium(words)

    info = entropy.compute_words_information(words, compendium, threads=1)

    assert {word for word, _ in info} == words
    entropies = [word_entropy for _, word_entropy in info]
    assert entropies == sorted(entropies, reverse=True)


def test_compute_words_information_matches_serial_computation() -> None:
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (1, 7, 3, 9, 5), (6, 2, 8, 4, 10), (2, 4, 6, 8, 10)}
    compendium = computing.build_pattern_compendium(words)
    word_counter_by_pattern = entropy.compute_word_counter_by_pattern(compendium)

    serial = sorted(((word, entropy.compute_word_entropy(word, word_counter_by_pattern, len(words))) for word in words),
                    key=lambda x: x[1], reverse=True)
    parallel = entropy.compute_words_information(words, compendium, threads=2)

    assert serial == parallel


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
