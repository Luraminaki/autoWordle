#!/usr/bin/env python3
"""Before/after benchmark harness for the pattern-compendium / entropy pipeline.

Builds a pattern compendium, populates a SQLite cache, and computes word
entropy ("best opening") information for controlled synthetic word lists and
the real bundled ``wordle`` answer list, reporting wall time, file size, and
peak RSS for each stage - once for the original pure-Python pipeline
(``legacy_compendium.build_pattern_compendium`` + ``legacy_compendium.compute_words_information``,
no longer used by the real app but kept as the historical baseline) and once
for the current one (``vectorized_compendium.stream_pattern_compendium_to_cache``
+ ``entropy.rank_words_by_entropy``), so the comparison this script exists
for stays meaningful instead of only measuring the side nothing uses anymore.

Run with: ``python -m scripts.benchmarks.benchmark_compendium`` from the repository root.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import argparse
import pathlib
import random
import resource
import string
import tempfile
import time

from autoWordle.modules import compendium_cache, entropy, legacy_compendium, statics, vectorized_compendium, word_codec

SHIFT = ord('a') - 10


def make_synthetic_words(n: int, length: int = 5, seed: int = 0) -> set[tuple[int, ...]]:
    """Generate `n` distinct random lowercase words encoded as shifted-ordinal tuples.

    Args:
        n (int): Number of distinct words to generate.
        length (int): Word length.
        seed (int): RNG seed, for reproducibility across runs.

    Returns:
        set[tuple[int, ...]]: Synthetic word pool.
    """
    rng = random.Random(seed)
    words: set[tuple[int, ...]] = set()

    while len(words) < n:
        words.add(tuple(ord(rng.choice(string.ascii_lowercase)) - SHIFT for _ in range(length)))

    return words


def peak_rss_mb() -> float:
    """Report this process's peak resident set size so far.

    Returns:
        float: Peak RSS in megabytes.
    """
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def bench_old_pipeline(words: set[tuple[int, ...]]) -> None:
    """Time the original pure-Python pipeline.

    No longer used by the real app, kept as the historical "before" baseline
    this script's comparison needs.

    Args:
        words (set[tuple[int, ...]]): Word pool.
    """
    tic = time.perf_counter()
    compendium = legacy_compendium.build_pattern_compendium(words)
    t_build = time.perf_counter() - tic
    print(f"  [old] build_pattern_compendium:   {t_build:8.3f}s  ({len(compendium)} patterns, "
          + f"{sum(len(v) for v in compendium.values())} pairs)")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = pathlib.Path(tmp) / 'bench_old.sqlite'
        tic = time.perf_counter()

        patterns = [word_codec.tord_to_int(pattern, 10) for pattern in compendium]
        cache = compendium_cache.CacheDB(db_path, patterns, build_mode=True)

        for pattern, combinations in zip(patterns, compendium.values(), strict=True):
            guesses, c_words = zip(*combinations, strict=True)
            _ = cache.add_entries(pattern,
                                  guess=[word_codec.tord_to_int(guess) for guess in guesses],
                                  word=[word_codec.tord_to_int(word) for word in c_words])

        cache.close()
        t_cache = time.perf_counter() - tic
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  [old] cache population:           {t_cache:8.3f}s  ({size_mb:.2f} MB)")

    tic = time.perf_counter()
    _ = legacy_compendium.compute_words_information(words, compendium)
    t_info = time.perf_counter() - tic
    print(f"  [old] compute_words_information:  {t_info:8.3f}s")
    print(f"  [old] total:                      {t_build + t_cache + t_info:8.3f}s")


def bench_vectorized_pipeline(words: set[tuple[int, ...]], word_length: int) -> None:
    """Time the current pipeline: what `helpers.LangLauncher`/`wordle.Wordle` actually use.

    Args:
        words (set[tuple[int, ...]]): Word pool.
        word_length (int): Word length (needed to pre-create the right pattern tables).
    """
    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(word_length)]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = pathlib.Path(tmp) / 'bench_vectorized.sqlite'
        cache = compendium_cache.CacheDB(db_path, patterns, build_mode=True)

        tic = time.perf_counter()
        counter = vectorized_compendium.stream_pattern_compendium_to_cache(words, cache)
        t_stream = time.perf_counter() - tic

        cache.close()
        size_mb = db_path.stat().st_size / (1024 * 1024)
        pairs = sum(sum(guess_counts.values()) for guess_counts in counter.values())
        print(f"  [vectorized] stream_pattern_compendium_to_cache: {t_stream:8.3f}s  ({len(counter)} patterns, "
              + f"{pairs} pairs, {size_mb:.2f} MB)")

    tic = time.perf_counter()
    _ = entropy.rank_words_by_entropy(words, counter, nbr_words=len(words))
    t_info = time.perf_counter() - tic
    print(f"  [vectorized] rank_words_by_entropy:               {t_info:8.3f}s")
    print(f"  [vectorized] total:                               {t_stream + t_info:8.3f}s")


def run_size(n: int, word_length: int = 5) -> None:
    """Run and print both pipelines' benchmarks for one synthetic word pool size.

    Args:
        n (int): Number of distinct synthetic words to generate.
        word_length (int): Word length.
    """
    words = make_synthetic_words(n, word_length)
    print(f"--- synthetic n={n} ---")
    bench_old_pipeline(words)
    bench_vectorized_pipeline(words, word_length)
    print(f"peak RSS so far:             {peak_rss_mb():8.1f} MB")
    print()


def run_real(word_file: pathlib.Path, word_length: int = 5) -> None:
    """Run and print both pipelines' benchmarks against a real word list file.

    Args:
        word_file (pathlib.Path): Path to a newline-delimited word list.
        word_length (int): Word length to filter to.
    """
    words = word_codec.get_words_list(word_file, word_length, SHIFT)
    print(f"--- real file={word_file.name} n={len(words)} ---")
    bench_old_pipeline(words)
    bench_vectorized_pipeline(words, word_length)
    print(f"peak RSS so far:             {peak_rss_mb():8.1f} MB")
    print()


def main() -> None:
    """Parse CLI args and run the requested benchmark sizes."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument('--sizes', type=int, nargs='*', default=[500, 1000])
    _ = parser.add_argument('--real-file', type=str, default='')
    _ = parser.add_argument('--word-length', type=int, default=5)
    args = parser.parse_args()

    for n in args.sizes:
        run_size(n, args.word_length)

    if args.real_file:
        run_real(pathlib.Path(args.real_file), args.word_length)


if __name__ == '__main__':
    main()
