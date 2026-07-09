#!/usr/bin/env python3
"""Superseded pure-Python pattern-compendium/entropy pipeline.

Nothing in the running app calls this anymore - `vectorized_compendium` +
`entropy.rank_words_by_entropy` replaced it (faster, and used directly by
`wordle.Wordle`/`helpers.LangLauncher`). Kept only because:

- Tests use `build_pattern_compendium` as a brute-force reference oracle to
  verify the vectorized implementation matches it exactly.
- `scripts/benchmarks/benchmark_compendium.py` uses this whole module as the
  "before" side of its before/after comparison.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import itertools
from collections import Counter

from autoWordle.modules import entropy
from autoWordle.modules.computing import PatternCompendium, Tord, WordCounterByPattern, WordsInformation, compute_pattern


def build_pattern_compendium(pool_words: set[Tord]) -> PatternCompendium:
    """Bucket every ordered `(word, guess)` pair in `pool_words` by resulting pattern.

    `O(n**2)` in both time and memory: every ordered pair of distinct words is
    evaluated once. Superseded by `vectorized_compendium`'s numpy-batched
    equivalent, which is significantly faster at real word-list sizes.

    Args:
        pool_words (set[Tord]): Candidate words to cross-evaluate.

    Returns:
        PatternCompendium: Pattern -> set of `(guess, word)` pairs producing it.
    """
    pattern_compendium: PatternCompendium = {}

    for word, guess in itertools.permutations(pool_words, 2):
        if word == guess:
            continue

        pattern = compute_pattern(guess=guess, word=word)

        if pattern not in pattern_compendium:
            pattern_compendium[pattern] = {(guess, word)}
            continue

        pattern_compendium[pattern].add((guess, word))

    return pattern_compendium


def compute_word_counter_by_pattern(pattern_compendium: PatternCompendium) -> WordCounterByPattern:
    """Count, per pattern, how many times each guess produces it.

    Args:
        pattern_compendium (PatternCompendium): Pattern -> set of `(guess, word)` pairs.

    Returns:
        WordCounterByPattern: Pattern -> {guess: occurrence count}.
    """
    word_counter_by_pattern: WordCounterByPattern = {}

    for pattern, compendium in pattern_compendium.items():
        pattern_words = [guess for guess, _ in compendium]
        word_counter_by_pattern[pattern] = dict(Counter(pattern_words))

    return word_counter_by_pattern


def compute_words_information(pool_words: set[Tord], pattern_compendium: PatternCompendium, threads: int = 0) -> WordsInformation:
    """Rank every word in a pool by its entropy against that pool, in parallel.

    Args:
        pool_words (set[Tord]): Candidate words to rank.
        pattern_compendium (PatternCompendium): Pre-built pattern compendium for `pool_words`. Only
            used to derive `word_counter_by_pattern`.
        threads (int): Worker process count. `<= 0` or greater than the CPU count uses all CPUs.

    Returns:
        WordsInformation: `(word, entropy)` pairs sorted by entropy, descending.
    """
    word_counter_by_pattern = compute_word_counter_by_pattern(pattern_compendium)
    return entropy.rank_words_by_entropy(pool_words, word_counter_by_pattern, threads)
