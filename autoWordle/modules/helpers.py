#!/usr/bin/env python3
"""Per-language orchestration: `LangLauncher` and multi-language app-source wiring.

Low-level word-list loading, int-packing codec, and CSV sidecar I/O live in
the companion `word_codec` module instead.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import logging
import pathlib
import time
from collections.abc import Callable
from typing import override

from autoWordle.modules import compendium_cache, computing, entropy, statics, vectorized_compendium, word_codec

logger = logging.getLogger(__name__)


class LangLauncher:
    """Loads a language's word list and (optionally) its precomputed solver data."""

    def __init__(self, words_path: str | pathlib.Path,
                compute_best_opening: bool = False,
                word_length: int = 5,
                threads: int = 0,
                progress_callback: Callable[[float, float], None] | None = None) -> None:
        """Load the word list and, if requested/available, exhaustive solver data.

        Args:
            words_path: Path to a newline-delimited word list file.
            compute_best_opening: Whether to compute (and persist) exhaustive
                entropy/pattern-cache data if it isn't already on disk.
            word_length: Word length to filter the list to.
            threads: Worker process count for entropy computation (0 = all CPUs).
            progress_callback: If given and a build actually runs, called with
                `(fraction_done, eta_seconds)` periodically - see
                `vectorized_compendium.stream_pattern_compendium_to_cache`.

        Raises:
            ValueError: If no word matches `word_length` in `words_path`.
        """
        tic = time.perf_counter()

        self.word_length: int = word_length
        self.threads: int = threads
        self.shift: int = ord('a') - 10

        logger.info("Acquiring file %s...", words_path)
        self.words_file: pathlib.Path = pathlib.Path(words_path).expanduser() if isinstance(words_path, str) else words_path

        logger.info("Building word list...")
        self.words: set[computing.Tord] = word_codec.get_words_list(self.words_file, self.word_length, self.shift)
        if not self.words:
            raise ValueError(f"No {self.word_length}-letter word found in {self.words_file}")
        logger.info("Found %d words...", len(self.words))

        self.cache: compendium_cache.CacheDB | None = None
        self.words_information: computing.WordsInformation = self.compute_words_information(compute_best_opening, progress_callback)

        tac = time.perf_counter() - tic
        logger.info("Language launcher for %s initialised in %s second(s)", self.words_file.name, round(tac, 2))


    @override
    def __str__(self) -> str:
        """Return the class name (used as a client-safe placeholder for this instance)."""
        return self.__class__.__name__


    def get_matching_words(self, guess: computing.Tord, pattern: computing.Tord) -> set[computing.Tord]:
        """Look up every word that would produce `pattern` if `guess` were played against it.

        Filters by `guess` inside the cache lookup itself (server-side, in
        SQLite) rather than fetching every pair ever recorded for `pattern`
        (across every guess in the source pool - tens of thousands of rows
        for a real word list) and filtering in Python: profiled as the
        dominant cost of live per-guess pool narrowing when this instead
        unpacked every row via `word_codec.tord_from_int` only to discard
        all but a handful that didn't match `guess`.

        Args:
            guess: Guess actually played.
            pattern: Resulting pattern for `guess`.

        Returns:
            set[Tord]: Matching target words, empty if no cache is loaded or none match.
        """
        if self.cache is None:
            return set()

        guess_int = word_codec.tord_to_int(guess)
        pattern_int = word_codec.tord_to_int(pattern, 10)

        return {word_codec.tord_from_int(word, self.word_length)
               for word in self.cache.get_words_for_guess(pattern_int, guess_int)}


    def _build_cache(self, path: pathlib.Path,
                     progress_callback: Callable[[float, float], None] | None = None,
                     ) -> tuple[compendium_cache.CacheDB, computing.WordCounterByPattern]:
        """Build a fresh pattern cache for `self.words`, streaming pairs in as they're computed.

        Pre-creates a table for every one of the `3 ** word_length` possible
        patterns upfront (see `statics.pattern_permutations`), so no
        discovery pass over the word pool is needed first to know which
        tables to create.

        Args:
            path: SQLite cache file path (must not exist yet).
            progress_callback: Forwarded to
                `vectorized_compendium.stream_pattern_compendium_to_cache`.

        Returns:
            tuple[compendium_cache.CacheDB, computing.WordCounterByPattern]: The
            newly built cache, and the pattern -> {guess: count} tally
            accumulated for free along the way (used for entropy ranking when
            the caller needs it, ignored otherwise).
        """
        logger.info("Building cache compendium...")
        patterns = [word_codec.tord_to_int(pattern, 10) for pattern in statics.pattern_permutations(self.word_length)]
        cache = compendium_cache.CacheDB(path, patterns, build_mode=True)

        tic = time.perf_counter()
        word_counter_by_pattern = vectorized_compendium.stream_pattern_compendium_to_cache(
            self.words, cache, progress_callback=progress_callback)
        tac = time.perf_counter() - tic
        logger.info("Built cache compendium in %s second(s)...", round(tac, 2))

        return cache, word_counter_by_pattern


    def compute_words_information(self, compute_best_opening: bool,
                                  progress_callback: Callable[[float, float], None] | None = None,
                                  ) -> computing.WordsInformation:
        """Load or compute this language's entropy ranking and pattern cache.

        Args:
            compute_best_opening: Whether to compute (and persist) exhaustive
                data if it isn't already on disk.
            progress_callback: Forwarded to `_build_cache` if a build actually runs.

        Returns:
            computing.WordsInformation: Words ranked by entropy, descending
            (empty if neither precomputed data exists nor `compute_best_opening` is set).
        """
        words_information: computing.WordsInformation = []
        cache_file, words_information_file = word_codec.get_data_paths(self.words_file, self.word_length)

        if words_information_file.exists():
            logger.info("Loading exhaustive information for best opening...")
            words_information = word_codec.load_words_information(words_information_file, self.shift)

            if cache_file.exists():
                self.cache = compendium_cache.CacheDB(cache_file)
            else:
                self.cache, _ = self._build_cache(cache_file, progress_callback)

        elif compute_best_opening:
            logger.info("Computing and saving exhaustive information for best opening...")
            self.cache, word_counter_by_pattern = self._build_cache(cache_file, progress_callback)
            words_information = entropy.rank_words_by_entropy(self.words, word_counter_by_pattern, self.threads)
            word_codec.save_words_information(words_information_file, words_information, self.shift)

        else:
            logger.info("Nothing to do, 'words_information' and 'cache' are empty, solver is thus unavailable...")

        return words_information


def init_lang_app_data(lang_files: list[pathlib.Path],
                       exhaustive_files: list[pathlib.Path],
                       default_word_lengths: list[int] | tuple[int, ...] = (5,),
                       compute_best_opening: bool = False,
                       client: bool = False) -> dict[str, dict]:
    """Build the raw (pre-Pydantic) app source mapping for every language found.

    Every language always gets a `LangLauncher` for `default_word_lengths`, in
    addition to any length discovered via an existing `*_info.csv` marker.
    Without this, a fresh install with no precomputed sidecars yet would never
    build a `LangLauncher` for any language/length at all - not even for
    `GAME_MODE_PLAY`, which needs nothing but the plain word list - since the
    only other source of word lengths to build is markers *produced by*
    already having built one.

    `compute_best_opening` (expensive: `O(n**2)` in the word count) is only
    ever honored for a length that already has a discovered marker - i.e. one
    some prior run was deliberately asked to precompute. A `default_word_lengths`
    entry with no marker yet always gets a cheap, bare `LangLauncher` (plain
    word list only, no exhaustive data), regardless of `compute_best_opening`.
    Otherwise, turning `compute_best_opening` on would silently make *every*
    language eagerly precompute exhaustive data for `default_word_lengths` on
    first boot - fine for a small curated answer list, but multi-minute and
    multi-gigabyte for a large dictionary that was never meant to get it.

    Args:
        lang_files: Plain word list files (one language each).
        exhaustive_files: `*_info.csv` markers of completed exhaustive precomputation.
        default_word_lengths: Word lengths to always build a `LangLauncher` for.
        compute_best_opening: Whether to compute (and persist) exhaustive data
            for language/length combinations that already have a marker but are
            missing their sidecar files.
        client: When `True`, produce a JSON-serializable view (no live
            `LangLauncher` instances) suitable for `schemas.LangSource.model_validate`.

    Returns:
        dict[str, dict]: `{lang_stem: {"path", "pre_computed": {word_length: {...}}}}`.
    """
    app_sources: dict[str, dict] = {}

    for lang_file in lang_files:
        logger.info("Found language <%s>...", lang_file.stem)
        app_sources[lang_file.stem] = {'path': lang_file if not client else lang_file.name,
                                       'pre_computed': {}}

        discovered_lengths = {int(exhaustive_file.stem.split('_')[1])
                              for exhaustive_file in exhaustive_files if lang_file.stem in exhaustive_file.stem}

        for word_length in discovered_lengths | set(default_word_lengths):
            build_exhaustive = compute_best_opening if word_length in discovered_lengths else False

            pre_computed = {'path': lang_file if not client else lang_file.name,
                            'length': word_length,
                            # `str(LangLauncher)` (the class, not an instance) never actually
                            # invokes `LangLauncher.__str__` - it gives "<class '...'>". Use
                            # `__name__` directly for the intended plain "LangLauncher" placeholder.
                            'lang_launcher': LangLauncher(lang_file, build_exhaustive, word_length) if not client else LangLauncher.__name__}
            app_sources[lang_file.stem]['pre_computed'][str(word_length)] = pre_computed

    return app_sources
