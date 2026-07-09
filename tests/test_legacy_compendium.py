#!/usr/bin/env python3
"""Tests for `autoWordle.modules.legacy_compendium`.

These functions aren't called by the running app anymore (see the module's
docstring) - `build_pattern_compendium` is exercised here, and elsewhere as a
brute-force reference oracle for `vectorized_compendium`, purely to keep that
role honest.
"""

#===================================================================================================
from autoWordle.modules import entropy, legacy_compendium

#===================================================================================================


def test_build_pattern_compendium_pair_count() -> None:
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (11, 12, 13, 14, 15), (16, 17, 18, 19, 20), (21, 22, 23, 24, 25)}
    compendium = legacy_compendium.build_pattern_compendium(words)

    total_pairs = sum(len(combinations) for combinations in compendium.values())
    assert total_pairs == len(words) * (len(words) - 1)


def test_compute_words_information_is_sorted_and_complete() -> None:
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (1, 7, 3, 9, 5), (6, 2, 8, 4, 10)}
    compendium = legacy_compendium.build_pattern_compendium(words)

    info = legacy_compendium.compute_words_information(words, compendium, threads=1)

    assert {word for word, _ in info} == words
    entropies = [word_entropy for _, word_entropy in info]
    assert entropies == sorted(entropies, reverse=True)


def test_compute_words_information_matches_serial_computation() -> None:
    words = {(1, 2, 3, 4, 5), (6, 7, 8, 9, 10), (1, 7, 3, 9, 5), (6, 2, 8, 4, 10), (2, 4, 6, 8, 10)}
    compendium = legacy_compendium.build_pattern_compendium(words)
    word_counter_by_pattern = legacy_compendium.compute_word_counter_by_pattern(compendium)

    serial = sorted(((word, entropy.compute_word_entropy(word, word_counter_by_pattern, len(words))) for word in words),
                    key=lambda x: x[1], reverse=True)
    parallel = legacy_compendium.compute_words_information(words, compendium, threads=2)

    assert serial == parallel
