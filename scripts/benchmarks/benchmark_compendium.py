#!/usr/bin/env python3
"""Before/after benchmark harness for the pattern-compendium / entropy pipeline.

Builds a pattern compendium, populates a SQLite cache, and computes word
entropy ("best opening") information for controlled synthetic word lists and
the real bundled ``wordle`` answer list, reporting wall time, file size, and
peak RSS for each stage. Used to compare optimization changes objectively
instead of assuming they help.

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

from autoWordle.modules import compendium_cache, computing, entropy, word_codec

SHIFT = ord('a') - 10


def make_synthetic_words(n: int, length: int = 5, seed: int = 0) -> set[tuple[int, ...]]:
    """Generate `n` distinct random lowercase words encoded as shifted-ordinal tuples.

    Args:
        n: Number of distinct words to generate.
        length: Word length.
        seed: RNG seed, for reproducibility across runs.

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


def bench_build_compendium(words: set[tuple[int, ...]]) -> tuple[dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]], float]:
    """Time `computing.build_pattern_compendium` for a word pool.

    Args:
        words: Word pool.

    Returns:
        tuple: The built compendium and elapsed wall time in seconds.
    """
    tic = time.perf_counter()
    compendium = computing.build_pattern_compendium(words)
    tac = time.perf_counter() - tic
    return compendium, tac


def bench_cache_population(compendium: dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]],
                           db_path: pathlib.Path) -> tuple[float, float]:
    """Time populating a fresh SQLite cache from a compendium.

    Args:
        compendium: Pattern -> {(guess, word)} mapping to persist.
        db_path: Where to create the SQLite database (should not pre-exist).

    Returns:
        tuple[float, float]: Elapsed wall time in seconds, resulting file size in MB.
    """
    tic = time.perf_counter()

    patterns = [word_codec.tord_to_int(pattern, 10) for pattern in compendium]
    cache = compendium_cache.CacheDB(db_path, patterns, build_mode=True)

    for pattern, combinations in zip(patterns, compendium.values(), strict=True):
        guesses, c_words = zip(*combinations, strict=True)
        _ = cache.add_entries(pattern,
                              guess=[word_codec.tord_to_int(guess) for guess in guesses],
                              word=[word_codec.tord_to_int(word) for word in c_words])

    cache.close()
    tac = time.perf_counter() - tic
    size_mb = db_path.stat().st_size / (1024 * 1024)
    return tac, size_mb


def bench_words_information(words: set[tuple[int, ...]],
                            compendium: dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]],
                            threads: int = 0) -> float:
    """Time `entropy.compute_words_information` for a word pool.

    Args:
        words: Word pool.
        compendium: Pre-built pattern compendium for `words`.
        threads: Worker count (0 = use all CPUs).

    Returns:
        float: Elapsed wall time in seconds.
    """
    tic = time.perf_counter()
    _ = entropy.compute_words_information(words, compendium, threads)
    return time.perf_counter() - tic


def run_size(n: int) -> None:
    """Run and print the full benchmark for one synthetic word pool size.

    Args:
        n: Number of distinct synthetic words to generate.
    """
    words = make_synthetic_words(n)
    print(f"--- synthetic n={n} ---")

    compendium, t_build = bench_build_compendium(words)
    print(f"build_pattern_compendium:   {t_build:8.3f}s  ({len(compendium)} patterns, "
          + f"{sum(len(v) for v in compendium.values())} pairs)")

    with tempfile.TemporaryDirectory() as tmp:
        t_cache, size_mb = bench_cache_population(compendium, pathlib.Path(tmp) / 'bench.sqlite')
        print(f"cache population:           {t_cache:8.3f}s  ({size_mb:.2f} MB)")

    t_info = bench_words_information(words, compendium)
    print(f"compute_words_information:  {t_info:8.3f}s")
    print(f"peak RSS so far:             {peak_rss_mb():8.1f} MB")
    print()


def run_real(word_file: pathlib.Path) -> None:
    """Run and print the full benchmark against a real word list file.

    Args:
        word_file: Path to a newline-delimited word list.
    """
    words = word_codec.get_words_list(word_file, 5, SHIFT)
    print(f"--- real file={word_file.name} n={len(words)} ---")

    compendium, t_build = bench_build_compendium(words)
    print(f"build_pattern_compendium:   {t_build:8.3f}s  ({len(compendium)} patterns, "
          + f"{sum(len(v) for v in compendium.values())} pairs)")

    with tempfile.TemporaryDirectory() as tmp:
        t_cache, size_mb = bench_cache_population(compendium, pathlib.Path(tmp) / 'bench.sqlite')
        print(f"cache population:           {t_cache:8.3f}s  ({size_mb:.2f} MB)")

    t_info = bench_words_information(words, compendium)
    print(f"compute_words_information:  {t_info:8.3f}s")
    print(f"peak RSS so far:             {peak_rss_mb():8.1f} MB")
    print()


def main() -> None:
    """Parse CLI args and run the requested benchmark sizes."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument('--sizes', type=int, nargs='*', default=[500, 1000])
    _ = parser.add_argument('--real-file', type=str, default='')
    args = parser.parse_args()

    for n in args.sizes:
        run_size(n)

    if args.real_file:
        run_real(pathlib.Path(args.real_file))


if __name__ == '__main__':
    main()
