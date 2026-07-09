#!/usr/bin/env python3
"""Entropy ranking of candidate words, parallelized across a `ProcessPoolExecutor`.

Split out from `computing` because this is a distinct concern from
pattern/candidate-pool logic: statistics (Shannon entropy) plus the
multiprocessing machinery needed to compute it fast over large word pools.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count

from autoWordle.modules.computing import Tord, WordCounterByPattern, WordsInformation, safe_log2

# Below this many candidate guesses, computing entropy serially (a plain loop
# in the current process) beats spinning up a ProcessPoolExecutor - benchmarked
# on real word-list data: process fork/IPC overhead is a near-fixed ~7-15ms
# regardless of pool size, while the actual per-word computation is
# sub-millisecond up to a few hundred words. Parallelism only pays off once
# the pool is close to a real dictionary's full size (confirmed ~24% faster
# at 2315 words on the bundled wordle.txt, but ~1.4-4x *slower* at 500-1500) -
# i.e. essentially only the one-time full-list precompute and a game's very
# first guess, not the narrowed pools every later guess in a game works with.
_SERIAL_THRESHOLD = 2000


def compute_word_entropy(word: Tord, word_counter_by_pattern: WordCounterByPattern, nbr_words: int) -> float:
    """Compute the Shannon entropy (in bits) of guessing `word` against a pool.

    Args:
        word (Tord): Candidate guess.
        word_counter_by_pattern (WordCounterByPattern): Pattern -> {guess: occurrence count}.
        nbr_words (int): Total number of words in the pool `word_counter_by_pattern` was built from.

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
        word_counter_by_pattern (WordCounterByPattern): Pattern -> {guess: occurrence count}.
        nbr_words (int): Total number of words in the pool being ranked.
    """
    global _worker_word_counter_by_pattern, _worker_nbr_words
    _worker_word_counter_by_pattern = word_counter_by_pattern
    _worker_nbr_words = nbr_words


def _entropy_worker(word: Tord) -> tuple[Tord, float]:
    """Compute one word's entropy against this worker's shared state.

    Args:
        word (Tord): Candidate guess.

    Returns:
        tuple[Tord, float]: `(word, entropy)`.
    """
    return word, compute_word_entropy(word, _worker_word_counter_by_pattern, _worker_nbr_words)


def _rank_words_by_entropy_serial(pool_words: set[Tord], word_counter_by_pattern: WordCounterByPattern,
                                  nbr_words: int) -> WordsInformation:
    """Rank every word in a pool by its entropy, in the current process - no worker pool.

    Args:
        pool_words (set[Tord]): Candidate words to rank as guesses.
        word_counter_by_pattern (WordCounterByPattern): Pre-built pattern -> {guess: occurrence count}.
        nbr_words (int): Size of the target pool the entropy probabilities are computed against.

    Returns:
        WordsInformation: `(word, entropy)` pairs sorted by entropy, descending.
    """
    results = [(word, compute_word_entropy(word, word_counter_by_pattern, nbr_words)) for word in pool_words]
    return sorted(results, key=lambda x: x[1], reverse=True)


def rank_words_by_entropy(pool_words: set[Tord], word_counter_by_pattern: WordCounterByPattern,
                          threads: int = 0, nbr_words: int | None = None) -> WordsInformation:
    """Rank every word in a pool by its entropy against a target pool.

    Args:
        pool_words (set[Tord]): Candidate words to rank as guesses.
        word_counter_by_pattern (WordCounterByPattern): Pre-built pattern -> {guess: occurrence count}.
            Callers that already have this (e.g. `helpers`'s streaming
            precomputation, which builds it directly without ever
            materializing a full `PatternCompendium`) should call this
            directly instead of `legacy_compendium.compute_words_information`.
        threads (int): Worker process count for pools at/above `_SERIAL_THRESHOLD`
            (ignored below it, see that constant). `<= 0` or greater than
            the CPU count uses all CPUs.
        nbr_words (int | None): Size of the *target* pool the entropy probabilities are
            computed against. Defaults to `len(pool_words)`, correct when
            `pool_words` is both the guesses being ranked and the possible
            targets (every caller before the full-dictionary-vs-narrowed-pool
            fallback in `wordle.py`) - pass this explicitly when `pool_words`
            (guesses) and the actual target pool are different sets.

    Returns:
        WordsInformation: `(word, entropy)` pairs sorted by entropy, descending.
    """
    if nbr_words is None:
        nbr_words = len(pool_words)

    if len(pool_words) < _SERIAL_THRESHOLD:
        return _rank_words_by_entropy_serial(pool_words, word_counter_by_pattern, nbr_words)

    if not 0 < threads <= cpu_count():
        threads = cpu_count()

    chunksize = max(1, len(pool_words) // (threads * 4) or 1)

    with ProcessPoolExecutor(max_workers=threads, initializer=_entropy_worker_init,
                             initargs=(word_counter_by_pattern, nbr_words)) as executor:
        results = list(executor.map(_entropy_worker, pool_words, chunksize=chunksize))

    return sorted(results, key=lambda x: x[1], reverse=True)
