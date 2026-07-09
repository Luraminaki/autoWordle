#!/usr/bin/env python3
"""Numpy-vectorized pattern-compendium building.

Computes the same `O(n**2)` `(guess, word)` pairs as
`legacy_compendium.build_pattern_compendium`, but every guess's patterns against the
full word pool are computed in a handful of vectorized array operations
instead of one Python-level `computing.compute_pattern` call per pair - a
large constant-factor speedup that grows with pool size (benchmarked: ~30%
faster than the pure-Python streaming builder it replaces for the bundled
2315-word `wordle.txt`, ~2x faster for a 7452-word list at `word_length=6`).

Peak memory stays bounded per guess (`O(n)`, not `O(n**2)`): only one guess's
`(n, word_length)` working arrays are ever held at once, and matches are
streamed straight to the SQLite cache in bounded batches - the same
memory-bounding design as the pure-Python streaming builder this replaces,
just with a vectorized inner loop.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import logging
import time
from collections import Counter
from collections.abc import Callable

import numpy as np

from autoWordle.modules import compendium_cache, statics, word_codec
from autoWordle.modules.computing import Tord, WordCounterByPattern

logger = logging.getLogger(__name__)

# How often (in wall-clock seconds) to log build progress - time-based rather
# than every-N-guesses so the log cadence stays reasonable regardless of pool
# size or machine speed (a 2315-word list finishes in seconds; a 7452-word
# one at word_length=6 takes minutes).
_PROGRESS_LOG_INTERVAL_SECONDS = 5.0

# `word_codec` encodes letters as `ord(letter) - shift` with `shift = ord('a') - 10`,
# i.e. every letter (already normalized to lowercase a-z by `unidecode` in
# `word_codec.get_words_list`) packs into 10..35 - the 26-letter range this
# module's per-letter counting loop is sized for.
_ALPHABET_MIN = 10
_ALPHABET_SIZE = 26

_MISS = int(statics.StatusLetter.MISS)
_MISPLACED = int(statics.StatusLetter.MISPLACED)
_EXACT = int(statics.StatusLetter.EXACT)

# Flush a pattern's buffered (guess, word) pairs to the cache once its buffer
# reaches this size - bounds peak memory independent of word-list size,
# instead of accumulating every pair for every pattern before writing any of
# them out (what `legacy_compendium.build_pattern_compendium` does).
_STREAM_BATCH_SIZE = 200_000


def _compute_patterns_for_guess(guess_row: np.ndarray, words_arr: np.ndarray) -> np.ndarray:
    """Pattern of one guess against every row of `words_arr`, vectorized.

    Same result as calling `computing.compute_pattern(guess, word)` once per
    row of `words_arr`, packed the same way as `word_codec.tord_to_int(pattern,
    10)` - but computed for every word at once via array operations instead
    of one Python-level call per word.

    Args:
        guess_row (np.ndarray): Shape `(word_length,)` int array, one guess's letters.
        words_arr (np.ndarray): Shape `(n, word_length)` int array, every candidate word's letters.

    Returns:
        np.ndarray: Shape `(n,)` int array of packed pattern ints.
    """
    n, length = words_arr.shape
    exact = words_arr == guess_row[None, :]

    # Per-letter count remaining in each word after removing letters already
    # spent on an exact match - the budget the second pass below draws down.
    remaining = np.zeros((n, _ALPHABET_SIZE), dtype=np.int16)
    for offset in range(_ALPHABET_SIZE):
        is_letter: np.ndarray = words_arr == (_ALPHABET_MIN + offset)
        remaining[:, offset] = is_letter.sum(axis=1) - (is_letter & exact).sum(axis=1)

    pattern = np.full((n, length), _MISS, dtype=np.int8)
    pattern[exact] = _EXACT

    # Misplaced letters are assigned left-to-right in *guess* order, budgeted
    # by `remaining` - inherently sequential (an earlier position's
    # assignment changes what's left for a later position with the same
    # letter), so this loop runs `length` times (5-6), never `n` times.
    for pos in range(length):
        offset = int(guess_row[pos]) - _ALPHABET_MIN
        can_be_misplaced = (~exact[:, pos]) & (remaining[:, offset] > 0)
        pattern[can_be_misplaced, pos] = _MISPLACED
        remaining[can_be_misplaced, offset] -= 1

    units = (10 ** np.arange(length - 1, -1, -1)).astype(np.int64)
    return pattern.astype(np.int64) @ units


def compute_word_counter_by_pattern_cross(guesses: set[Tord], targets: set[Tord]) -> WordCounterByPattern:
    """Tally, per pattern, how many `targets` each of `guesses` would match.

    Unlike `stream_pattern_compendium_to_cache` (one shared set, used as both
    guesses and targets, streamed to a persisted SQLite cache), `guesses` and
    `targets` are different sets here - e.g. the full word list scored
    against a narrowed candidate pool (see `wordle.Wordle.submit_guess_and_pattern`'s
    full-dictionary fallback) - and the result is purely an in-memory,
    ephemeral ranking input for one live decision, never written to a cache.

    A guess that happens to also be a member of `targets` is *not* excluded
    (unlike `legacy_compendium.build_pattern_compendium`'s self-pair skip): guessing
    a word that could itself be the answer legitimately produces the
    all-EXACT pattern, and that's meaningful information to keep, not a
    redundant self-comparison to discard.

    Args:
        guesses (set[Tord]): Candidate guesses to evaluate (e.g. the full word list).
        targets (set[Tord]): Possible remaining answers (e.g. the current narrowed pool).

    Returns:
        WordCounterByPattern: Pattern -> {guess: occurrence count against `targets`}.
    """
    targets_arr = np.array(list(targets), dtype=np.int16)
    word_length = targets_arr.shape[1]

    word_counter_by_pattern: WordCounterByPattern = {}

    for guess in guesses:
        pattern_ints = _compute_patterns_for_guess(np.array(guess, dtype=np.int16), targets_arr)

        for pattern_int, count in Counter(int(p) for p in pattern_ints).items():
            pattern_tuple = word_codec.tord_from_int(pattern_int, word_length, units=10)
            word_counter_by_pattern.setdefault(pattern_tuple, {})[guess] = count

    return word_counter_by_pattern


def stream_pattern_compendium_to_cache(pool_words: set[Tord], cache: compendium_cache.CacheDB,
                                       batch_size: int = _STREAM_BATCH_SIZE,
                                       progress_callback: Callable[[float, float], None] | None = None) -> WordCounterByPattern:
    """Cross-evaluate every ordered pair in `pool_words`, one guess at a time, vectorized.

    Same `(guess, word)` pairs as `legacy_compendium.build_pattern_compendium`, but
    each guess's patterns against the full pool are computed in one batch of
    array operations (see `_compute_patterns_for_guess`) instead of one
    Python-level `computing.compute_pattern` call per pair, and matches are
    written to `cache` in bounded batches instead of being held in a full
    `O(n**2)` `PatternCompendium` first.

    Logs progress (`% complete`, ETA) and, if given, calls `progress_callback`
    with the same numbers, at most once every `_PROGRESS_LOG_INTERVAL_SECONDS`
    - each guess does essentially equal work (same vectorized computation
    size every iteration), so the linear `elapsed / fraction_done`
    extrapolation is accurate here, unlike most progress estimates.

    Args:
        pool_words (set[Tord]): Candidate words to cross-evaluate. Every letter must fall
            in the `word_codec` shift range `[10, 36)` - i.e. `pool_words`
            must come from `word_codec.get_words_list`/`tord_from_int`, not
            arbitrary int tuples - `_compute_patterns_for_guess` indexes a
            fixed-size 26-column array by `letter - 10` with no bounds check,
            so an out-of-range letter would silently corrupt results (wrap to
            an unrelated column) rather than fail loudly.
        cache (compendium_cache.CacheDB): Cache to write matches into; must already have a table for
            every possible pattern (see `statics.pattern_permutations`).
        batch_size (int): Flush buffered pairs to `cache` once at least this many
            are pending - bounds peak memory independent of word-list size.
        progress_callback (Callable[[float, float], None] | None): If given, called with `(fraction_done, eta_seconds)`
            on the same cadence as the progress log line - e.g. to publish
            progress somewhere observable across processes (see
            `app.precompute_store`), rather than just the local log.

    Returns:
        WordCounterByPattern: Pattern -> {guess: occurrence count}.

    Raises:
        ValueError: If any letter falls outside `[_ALPHABET_MIN, _ALPHABET_MIN + _ALPHABET_SIZE)`.
    """
    words_list = list(pool_words)
    words_arr = np.array(words_list, dtype=np.int16)

    if words_arr.size and (int(words_arr.min()) < _ALPHABET_MIN or int(words_arr.max()) >= _ALPHABET_MIN + _ALPHABET_SIZE):
        alphabet_range = f"[{_ALPHABET_MIN}, {_ALPHABET_MIN + _ALPHABET_SIZE})"
        actual_range = f"min={int(words_arr.min())}, max={int(words_arr.max())}"
        raise ValueError(f"Letters must be shifted-ordinal values in {alphabet_range} (see word_codec) - got {actual_range}")

    word_ints = np.array([word_codec.tord_to_int(word) for word in words_list], dtype=np.int64)
    word_length = words_arr.shape[1]

    word_counter_by_pattern: WordCounterByPattern = {}
    pending: dict[int, tuple[list[int], list[int]]] = {}
    pending_count = 0

    def flush() -> None:
        nonlocal pending_count
        if pending:
            _ = cache.add_entries_batch(pending)
        pending.clear()
        pending_count = 0

    total_words = len(words_list)
    tic = time.perf_counter()
    last_log = tic

    for gi, guess in enumerate(words_list):
        pattern_ints = _compute_patterns_for_guess(words_arr[gi], words_arr)

        now = time.perf_counter()
        if now - last_log >= _PROGRESS_LOG_INTERVAL_SECONDS:
            elapsed = now - tic
            fraction_done = (gi + 1) / total_words
            eta_seconds = (elapsed / fraction_done) - elapsed
            logger.info("Building pattern compendium: %.1f%% (%d/%d guesses), ~%.0fs remaining",
                        fraction_done * 100, gi + 1, total_words, eta_seconds)
            if progress_callback is not None:
                progress_callback(fraction_done, eta_seconds)
            last_log = now

        order = np.argsort(pattern_ints, kind='stable')
        sorted_patterns = pattern_ints[order]
        sorted_word_ints = word_ints[order]
        self_mask = order == gi

        boundaries = np.nonzero(np.diff(sorted_patterns))[0] + 1
        starts = np.concatenate(([0], boundaries))
        ends = np.concatenate((boundaries, [len(sorted_patterns)]))

        guess_int = int(word_ints[gi])

        for start, end in zip(starts, ends, strict=True):
            pattern_val = int(sorted_patterns[start])
            group_word_ints = sorted_word_ints[start:end]
            group_self_mask: np.ndarray = self_mask[start:end]

            if group_self_mask.any():
                # Excludes the (guess, guess) self-pair, matching
                # `legacy_compendium.build_pattern_compendium`'s `word == guess` skip.
                group_word_ints = group_word_ints[~group_self_mask]

            count = len(group_word_ints)
            if count == 0:
                continue

            pattern_tuple = word_codec.tord_from_int(pattern_val, word_length, units=10)
            word_counter_by_pattern.setdefault(pattern_tuple, {})[guess] = count

            bucket = pending.setdefault(pattern_val, ([], []))
            bucket[0].extend([guess_int] * count)
            bucket[1].extend(int(w) for w in group_word_ints)
            pending_count += count

        if pending_count >= batch_size:
            flush()

    flush()
    return word_counter_by_pattern
