#!/usr/bin/env python3
"""Entropy ranking of candidate words, parallelized across a `ProcessPoolExecutor`.

Split out from `computing` because this is a distinct concern from
pattern/candidate-pool logic: statistics (Shannon entropy) plus the
multiprocessing machinery needed to compute it fast over large word pools.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count

from autoWordle.modules.computing import PatternCompendium, Tord, WordCounterByPattern, WordsInformation, safe_log2


def compute_word_counter_by_pattern(pattern_compendium: PatternCompendium) -> WordCounterByPattern:
    """Count, per pattern, how many times each guess produces it.

    Args:
        pattern_compendium: Pattern -> set of `(guess, word)` pairs.

    Returns:
        WordCounterByPattern: Pattern -> {guess: occurrence count}.
    """
    word_counter_by_pattern: WordCounterByPattern = {}

    for pattern, compendium in pattern_compendium.items():
        pattern_words = [guess for guess, _ in compendium]
        word_counter_by_pattern[pattern] = dict(Counter(pattern_words))

    return word_counter_by_pattern


def compute_word_entropy(word: Tord, word_counter_by_pattern: WordCounterByPattern, nbr_words: int) -> float:
    """Compute the Shannon entropy (in bits) of guessing `word` against a pool.

    Args:
        word: Candidate guess.
        word_counter_by_pattern: Pattern -> {guess: occurrence count}.
        nbr_words: Total number of words in the pool `word_counter_by_pattern` was built from.

    Returns:
        float: Expected information gain, in bits.
    """
    entropy = 0.0

    for compendium_word_count in word_counter_by_pattern.values():
        match_probability = compendium_word_count.get(word, 0) / nbr_words
        entropy += (match_probability * -safe_log2(match_probability))

    return entropy


# Populated once per worker process by `_entropy_worker_init` and read by
# `_entropy_worker`, instead of passing `word_counter_by_pattern` through a
# `multiprocessing.Manager` proxy (which round-trips every dict write through
# a manager server process - much slower than returning plain values).
_worker_word_counter_by_pattern: WordCounterByPattern = {}
_worker_nbr_words: int = 0


def _entropy_worker_init(word_counter_by_pattern: WordCounterByPattern, nbr_words: int) -> None:
    """Initialize a `ProcessPoolExecutor` worker with its (large, read-only) shared state.

    Args:
        word_counter_by_pattern: Pattern -> {guess: occurrence count}.
        nbr_words: Total number of words in the pool being ranked.
    """
    global _worker_word_counter_by_pattern, _worker_nbr_words
    _worker_word_counter_by_pattern = word_counter_by_pattern
    _worker_nbr_words = nbr_words


def _entropy_worker(word: Tord) -> tuple[Tord, float]:
    """Compute one word's entropy against this worker's shared state.

    Args:
        word: Candidate guess.

    Returns:
        tuple[Tord, float]: `(word, entropy)`.
    """
    return word, compute_word_entropy(word, _worker_word_counter_by_pattern, _worker_nbr_words)


def rank_words_by_entropy(pool_words: set[Tord], word_counter_by_pattern: WordCounterByPattern,
                         threads: int = 0, nbr_words: int | None = None) -> WordsInformation:
    """Rank every word in a pool by its entropy against a target pool, in parallel.

    Args:
        pool_words: Candidate words to rank as guesses.
        word_counter_by_pattern: Pre-built pattern -> {guess: occurrence count}.
            Callers that already have this (e.g. `helpers`'s streaming
            precomputation, which builds it directly without ever
            materializing a full `PatternCompendium`) should call this
            directly instead of `compute_words_information`.
        threads: Worker process count. `<= 0` or greater than the CPU count uses all CPUs.
        nbr_words: Size of the *target* pool the entropy probabilities are
            computed against. Defaults to `len(pool_words)`, correct when
            `pool_words` is both the guesses being ranked and the possible
            targets (every caller before the full-dictionary-vs-narrowed-pool
            fallback in `wordle.py`) - pass this explicitly when `pool_words`
            (guesses) and the actual target pool are different sets.

    Returns:
        WordsInformation: `(word, entropy)` pairs sorted by entropy, descending.
    """
    if not 0 < threads <= cpu_count():
        threads = cpu_count()

    if nbr_words is None:
        nbr_words = len(pool_words)

    chunksize = max(1, len(pool_words) // (threads * 4) or 1)

    with ProcessPoolExecutor(max_workers=threads, initializer=_entropy_worker_init,
                             initargs=(word_counter_by_pattern, nbr_words)) as executor:
        results = list(executor.map(_entropy_worker, pool_words, chunksize=chunksize))

    return sorted(results, key=lambda x: x[1], reverse=True)


def compute_words_information(pool_words: set[Tord], pattern_compendium: PatternCompendium, threads: int = 0) -> WordsInformation:
    """Rank every word in a pool by its entropy against that pool, in parallel.

    Args:
        pool_words: Candidate words to rank.
        pattern_compendium: Pre-built pattern compendium for `pool_words`. Only
            used to derive `word_counter_by_pattern` - for a pool small enough
            to hold the full compendium in memory (e.g. `wordle.Wordle`'s
            per-guess narrowing, where the pool has already shrunk). For the
            full word list, use `helpers`'s streaming precomputation and
            `rank_words_by_entropy` directly instead.
        threads: Worker process count. `<= 0` or greater than the CPU count uses all CPUs.

    Returns:
        WordsInformation: `(word, entropy)` pairs sorted by entropy, descending.
    """
    word_counter_by_pattern = compute_word_counter_by_pattern(pattern_compendium)
    return rank_words_by_entropy(pool_words, word_counter_by_pattern, threads)
