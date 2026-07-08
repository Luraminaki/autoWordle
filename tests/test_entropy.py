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
